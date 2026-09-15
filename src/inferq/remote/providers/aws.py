"""AWS backend: S3 objects and DynamoDB records.

Credentials are resolved when a connection is constructed, never at import
time, so importing this module offline is safe.

Authentication goes through boto3's default credential chain -- IAM role,
instance profile, SSO, shared config, environment -- which is what a deployment
running inside AWS should use, and what makes the migration target need no
secrets at all. Explicit ``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY``
override it when set, for local development and CI. ``AWS_ENDPOINT_URL``
redirects both services at a local stand-in such as LocalStack or MinIO.

Two details are load-bearing for a migration that has to be reversible:

* attribute names come from :func:`inferq.remote.base.field_safe`, the same
  helper the Azure backend uses, so records written on either cloud carry
  identical attribute names;
* pagination state is handed out as the same opaque cursor string on both
  sides, so a resumable export survives a change of provider mid-run.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from urllib.parse import quote

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from inferq.remote.base import (
    CloudConnection,
    CloudCredentialsError,
    MetadataStore,
    ObjectInfo,
    ObjectStore,
    Record,
    RecordPage,
    decode_cursor,
    encode_cursor,
)
from inferq.remote.metadata import coerce_native

logger = logging.getLogger(__name__)

PROVIDER = "aws"

#: DynamoDB key schema. A single partition holds the whole circuit catalogue
#: (see ``CIRCUITS_PARTITION``), with the circuit hash as the sort key, which
#: matches how the catalogue is read: by hash, or by full scan.
PARTITION_ATTRIBUTE = "pk"
SORT_ATTRIBUTE = "sk"
TIMESTAMP_ATTRIBUTE = "timestamp"

#: Attributes the store owns. They are addressing or bookkeeping, and are kept
#: out of a :class:`Record`'s fields the same way Azure's system keys are.
#: Ordered, because they are also projected by name and an expression has to
#: be reproducible.
_SYSTEM_ATTRIBUTES = (PARTITION_ATTRIBUTE, SORT_ATTRIBUTE, TIMESTAMP_ATTRIBUTE)

#: Upload tuning chosen to match the Azure backend's behaviour: objects larger
#: than 4 MiB are split, and the parts go up four at a time. S3 requires parts
#: of at least 5 MiB, so the chunk size is the smallest legal value above the
#: threshold.
_UPLOAD_CONCURRENCY = 4
_MULTIPART_THRESHOLD = 4 * 1024 * 1024
_MULTIPART_CHUNKSIZE = 8 * 1024 * 1024

_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=_MULTIPART_THRESHOLD,
    multipart_chunksize=_MULTIPART_CHUNKSIZE,
    max_concurrency=_UPLOAD_CONCURRENCY,
    use_threads=True,
)


class AwsCredentialsError(CloudCredentialsError):
    """Raised when required AWS environment variables are missing.

    Subclasses the provider-neutral error so that callers can catch either.
    """


@dataclass(frozen=True)
class AwsCredentials:
    """AWS settings resolved from the environment.

    Only the three *placement* variables are required -- which region, which
    bucket, which table. Authentication deliberately is not: on an EC2
    instance, an ECS task or a Lambda the credential chain supplies it, and
    demanding an access key there would be a step backwards.
    """

    region: str
    bucket: str
    table: str
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    endpoint_url: str | None = None
    profile: str | None = None

    #: Environment variables that must be set, each with the aliases accepted
    #: for it. The first name is the one quoted back at an operator.
    REQUIRED_VARS = (
        ("AWS_REGION", "AWS_DEFAULT_REGION"),
        ("AWS_S3_BUCKET",),
        ("AWS_DYNAMODB_TABLE",),
    )

    @classmethod
    def from_env(cls, config: Mapping[str, Any] | None = None) -> AwsCredentials:
        """Load settings from ``config``, falling back to the environment.

        Raises:
            AwsCredentialsError: if any required setting is unresolved, naming
                all of the missing variables at once so that an operator fixes
                their environment in a single pass.
        """
        load_dotenv()
        config = config or {}

        resolved: dict[str, str | None] = {}
        missing: list[str] = []
        for names, configured in zip(
            cls.REQUIRED_VARS,
            (config.get("region"), config.get("bucket"), config.get("table")),
            strict=True,
        ):
            value = configured or next((os.environ[n] for n in names if os.environ.get(n)), None)
            if value:
                resolved[names[0]] = value
            else:
                missing.append(" or ".join(names))

        if missing:
            raise AwsCredentialsError(
                f"Missing required AWS environment variables: {', '.join(missing)}. "
                "See .env.example."
            )

        return cls(
            region=str(resolved["AWS_REGION"]),
            bucket=str(resolved["AWS_S3_BUCKET"]),
            table=str(resolved["AWS_DYNAMODB_TABLE"]),
            access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            session_token=os.environ.get("AWS_SESSION_TOKEN"),
            endpoint_url=config.get("endpoint_url") or os.environ.get("AWS_ENDPOINT_URL"),
            profile=config.get("profile") or os.environ.get("AWS_PROFILE"),
        )

    def session(self) -> boto3.session.Session:
        """Build the boto3 session these settings describe.

        An explicit access key wins when one is set; otherwise the session is
        left to resolve credentials itself, which is what picks up an IAM role,
        an SSO login or an instance profile.
        """
        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.profile:
            kwargs["profile_name"] = self.profile
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
            if self.session_token:
                kwargs["aws_session_token"] = self.session_token
        else:
            logger.debug("No explicit AWS keys set; using the default credential chain")
        return boto3.session.Session(**kwargs)


# ── S3 ────────────────────────────────────────────────────────────────────────


def _ascii_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Reduce user metadata to what S3 can carry.

    S3 sends user metadata as HTTP headers, which are ASCII; a non-ASCII
    character makes the request fail at signing time rather than surfacing as
    a useful error. Circuit metadata is hashes, integers and format names, so
    replacing the occasional stray character costs nothing and avoids a class
    of upload failure that is very hard to diagnose from the wire.
    """
    cleaned: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        safe_key = str(key).encode("ascii", "ignore").decode("ascii")
        safe_value = "".join(
            character if character.isprintable() and character.isascii() else "?"
            for character in str(value)
        )
        if not safe_key:
            logger.debug("Dropping object metadata key %r: no ASCII characters", key)
            continue
        if safe_value != str(value):
            logger.debug("Sanitised non-ASCII object metadata for %r", safe_key)
        cleaned[safe_key] = safe_value
    return cleaned


def _is_not_found(error: ClientError) -> bool:
    """Whether a ClientError means 'no such object', across S3's spellings."""
    response = error.response or {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


class S3ObjectStore(ObjectStore):
    """:class:`~inferq.remote.base.ObjectStore` over an S3 bucket."""

    def __init__(self, client: Any, bucket: str, *, region: str, endpoint_url: str | None = None):
        self._client = client
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url.rstrip("/") if endpoint_url else None

    @property
    def name(self) -> str:
        return self._bucket

    @property
    def client(self) -> Any:
        """The underlying boto3 S3 client, for AWS-specific work."""
        return self._client

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        # upload_fileobj rather than put_object: it applies the transfer
        # config, so a large circuit is split into parts and uploaded
        # concurrently instead of being pushed as one request.
        self._client.upload_fileobj(
            BytesIO(data),
            self._bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": _ascii_metadata(metadata),
            },
            Config=_TRANSFER_CONFIG,
        )
        return self.object_url(key)

    def get_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def object_url(self, key: str) -> str:
        """Virtual-hosted-style URL, or a path-style one behind a custom endpoint.

        A custom endpoint (LocalStack, MinIO) generally does not resolve
        per-bucket hostnames, so the bucket goes in the path there.
        """
        encoded = quote(key, safe="/")
        if self._endpoint_url:
            return f"{self._endpoint_url}/{self._bucket}/{encoded}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{encoded}"

    def list_objects(
        self, prefix: str | None = None, *, include_metadata: bool = False
    ) -> Iterator[ObjectInfo]:
        """List the bucket, optionally with each object's user metadata.

        ``include_metadata=True`` is expensive: unlike Azure, S3 does not
        return user metadata in a listing, so it costs one ``head_object`` per
        key. Ask for it only when the metadata is actually read.
        """
        paginator = self._client.get_paginator("list_objects_v2")
        kwargs: dict[str, Any] = {"Bucket": self._bucket}
        if prefix:
            kwargs["Prefix"] = prefix

        for page in paginator.paginate(**kwargs):
            for entry in page.get("Contents", []):
                key = entry["Key"]
                metadata: dict[str, str] = {}
                if include_metadata:
                    try:
                        metadata = dict(
                            self._client.head_object(Bucket=self._bucket, Key=key).get(
                                "Metadata", {}
                            )
                        )
                    except ClientError as error:
                        # A key can disappear between the listing and the head.
                        logger.debug("Could not read metadata for %s: %s", key, error)
                yield ObjectInfo(
                    key=key,
                    size=entry.get("Size"),
                    metadata=metadata,
                    last_modified=entry.get("LastModified"),
                )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True

    def delete_object(self, key: str) -> None:
        # S3 deletes are idempotent: removing an absent key is a success.
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def ping(self) -> None:
        self._client.head_bucket(Bucket=self._bucket)


# ── DynamoDB ──────────────────────────────────────────────────────────────────


def to_dynamo(value: Any) -> Any:
    """Convert a Python value into something DynamoDB accepts.

    DynamoDB has no floating-point type: numbers are decimals, and boto3
    refuses a ``float`` outright rather than rounding one silently. Floats go
    through ``Decimal(str(value))``, which reproduces the shortest
    representation that round-trips, so a value read back compares equal to
    the one written.

    ``NaN`` and the infinities have no DynamoDB representation at all. They
    come out of failed simulations often enough to matter, so they are dropped
    with a warning rather than failing a whole record: the attribute is absent,
    which reads back as "not measured" instead of as a wrong number.

    Numpy types are reduced first by the shared
    :func:`~inferq.remote.metadata.coerce_native`, so that a feature value is
    converted in exactly the same way whichever cloud stores it.
    """
    value = coerce_native(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(str(value))
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [converted for item in value if (converted := to_dynamo(item)) is not None]
    if isinstance(value, Mapping):
        return {
            str(k): converted for k, v in value.items() if (converted := to_dynamo(v)) is not None
        }
    return value


def from_dynamo(value: Any) -> Any:
    """Undo :func:`to_dynamo`, turning decimals back into ints and floats."""
    if isinstance(value, Decimal):
        # An integral decimal came from an int; anything else from a float.
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [from_dynamo(item) for item in value]
    if isinstance(value, dict):
        return {key: from_dynamo(item) for key, item in value.items()}
    return value


def _encode_item(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a field mapping into DynamoDB attributes, dropping the unstorable."""
    item: dict[str, Any] = {}
    for key, value in fields.items():
        converted = to_dynamo(value)
        if converted is None and value is not None:
            logger.warning("Dropping attribute %r: %r has no DynamoDB representation", key, value)
            continue
        if converted is None:
            continue
        item[key] = converted
    return item


def _item_to_record(item: Mapping[str, Any], partition_fallback: str) -> Record:
    """Convert a DynamoDB item into a provider-neutral :class:`Record`."""
    fields = {
        key: from_dynamo(value) for key, value in item.items() if key not in _SYSTEM_ATTRIBUTES
    }
    return Record(
        partition=str(item.get(PARTITION_ATTRIBUTE, partition_fallback)),
        key=str(item.get(SORT_ATTRIBUTE, "")),
        fields=fields,
        timestamp=_parse_timestamp(item.get(TIMESTAMP_ATTRIBUTE)),
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse the stored ISO-8601 timestamp, tolerating anything unexpected."""
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.debug("Unparseable timestamp attribute: %r", raw)
        return None


def _aliased(names: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Map attribute names to ``#n0``-style placeholders.

    Every name is aliased, never just the ones that look reserved: DynamoDB's
    reserved-word list is long and grows, and a feature name like ``size`` or
    ``status`` is exactly the kind of thing feature extraction produces.
    """
    aliases = {f"#n{index}": name for index, name in enumerate(names)}
    return aliases, list(aliases)


class DynamoDbMetadataStore(MetadataStore):
    """:class:`~inferq.remote.base.MetadataStore` over a DynamoDB table."""

    def __init__(self, table: Any, *, client: Any | None = None):
        self._table = table
        self._client = client if client is not None else table.meta.client

    @property
    def name(self) -> str:
        return self._table.name

    @property
    def table(self) -> Any:
        """The underlying boto3 Table resource, for AWS-specific work."""
        return self._table

    def ensure_table(self) -> None:
        """Create the table if it is absent, and wait until it can be written.

        On-demand billing rather than provisioned throughput: the write rate
        here is a pipeline's batch uploads, which are bursty and idle most of
        the time -- the shape on-demand exists for.
        """
        try:
            self._client.create_table(
                TableName=self.name,
                KeySchema=[
                    {"AttributeName": PARTITION_ATTRIBUTE, "KeyType": "HASH"},
                    {"AttributeName": SORT_ATTRIBUTE, "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": PARTITION_ATTRIBUTE, "AttributeType": "S"},
                    {"AttributeName": SORT_ATTRIBUTE, "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ResourceInUseException":
                logger.debug("Table %s already exists", self.name)
                return
            raise

        logger.info("Created table: %s", self.name)
        # A freshly created table is CREATING for a few seconds and rejects
        # writes until it is ACTIVE, so the first upload after creation would
        # otherwise fail.
        self._client.get_waiter("table_exists").wait(TableName=self.name)

    def put_record(self, partition: str, key: str, fields: Mapping[str, Any]) -> None:
        item = _encode_item(fields)
        item[PARTITION_ATTRIBUTE] = partition
        item[SORT_ATTRIBUTE] = key
        item[TIMESTAMP_ATTRIBUTE] = datetime.now(UTC).isoformat()
        self._table.put_item(Item=item)

    def merge_record(self, partition: str, key: str, updates: Mapping[str, Any]) -> None:
        """Set the given attributes, leaving every other attribute untouched."""
        attributes = _encode_item(updates)
        if not attributes:
            # Nothing storable to write; do not create an empty record or move
            # the timestamp of an existing one.
            return
        attributes[TIMESTAMP_ATTRIBUTE] = datetime.now(UTC).isoformat()

        names = list(attributes)
        aliases, placeholders = _aliased(names)
        values = {f":v{index}": attributes[name] for index, name in enumerate(names)}
        assignments = ", ".join(
            f"{placeholder} = :v{index}" for index, placeholder in enumerate(placeholders)
        )

        self._table.update_item(
            Key={PARTITION_ATTRIBUTE: partition, SORT_ATTRIBUTE: key},
            UpdateExpression=f"SET {assignments}",
            ExpressionAttributeNames=aliases,
            ExpressionAttributeValues=values,
        )

    def get_record(self, partition: str, key: str) -> Record | None:
        response = self._table.get_item(Key={PARTITION_ATTRIBUTE: partition, SORT_ATTRIBUTE: key})
        item = response.get("Item")
        return _item_to_record(item, partition) if item else None

    def _projection(self, select: Sequence[str] | None) -> dict[str, Any]:
        """Build the projection arguments for a query or scan.

        The addressing attributes are always projected: without them a record
        could not say which circuit it describes.
        """
        if select is None:
            return {}
        names = list(dict.fromkeys([*_SYSTEM_ATTRIBUTES, *select]))
        aliases, placeholders = _aliased(names)
        return {
            "ProjectionExpression": ", ".join(placeholders),
            "ExpressionAttributeNames": aliases,
        }

    def list_records(
        self,
        partition: str | None = None,
        *,
        select: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        """Iterate records, following pagination until ``limit`` is reached.

        ``limit`` is pushed down as the request's ``Limit`` as well as being
        enforced here, so a catalogue listing of 100 rows does not read the
        whole table before discarding the rest.
        """
        yielded = 0
        for page in self._pages(partition, select=select, page_size=limit):
            for item in page.get("Items", []):
                yield _item_to_record(item, partition or "")
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

    def scan_records(
        self,
        partition: str | None = None,
        *,
        page_size: int = 1000,
        cursor: str | None = None,
    ) -> Iterator[RecordPage]:
        start_key = decode_cursor(cursor).get("LastEvaluatedKey") if cursor else None
        for page in self._pages(
            partition, select=None, page_size=page_size, start_key=start_key, single_page=True
        ):
            last_key = page.get("LastEvaluatedKey")
            yield RecordPage(
                records=[_item_to_record(item, partition or "") for item in page.get("Items", [])],
                cursor=encode_cursor({"LastEvaluatedKey": last_key}) if last_key else None,
            )

    def _pages(
        self,
        partition: str | None,
        *,
        select: Sequence[str] | None,
        page_size: int | None,
        start_key: Mapping[str, Any] | None = None,
        single_page: bool = False,
    ) -> Iterator[Mapping[str, Any]]:
        """Iterate raw response pages from a Query (or a Scan without a partition).

        A Query is a keyed read of one partition; a Scan reads the whole table.
        Querying whenever a partition is named is what keeps the catalogue read
        cheap, since every circuit lives in one partition.

        ``single_page`` stops after one response, for the cursor-driven
        :meth:`scan_records`, where the *caller* drives pagination and needs
        the chance to checkpoint between pages.
        """
        kwargs: dict[str, Any] = dict(self._projection(select))
        if page_size is not None:
            kwargs["Limit"] = page_size
        if start_key:
            kwargs["ExclusiveStartKey"] = dict(start_key)

        if partition is not None:
            # The partition attribute is aliased here too. Defining a name that
            # no expression uses is a validation error, so this alias exists
            # only because the key condition below uses it.
            names = dict(kwargs.get("ExpressionAttributeNames", {}))
            names["#pk"] = PARTITION_ATTRIBUTE
            kwargs["ExpressionAttributeNames"] = names
            kwargs["KeyConditionExpression"] = "#pk = :pk"
            kwargs["ExpressionAttributeValues"] = {":pk": partition}
            operation = self._table.query
        else:
            operation = self._table.scan

        while True:
            response = operation(**kwargs)
            yield response
            last_key = response.get("LastEvaluatedKey")
            if not last_key or single_page:
                return
            kwargs["ExclusiveStartKey"] = last_key

    def delete_record(self, partition: str, key: str) -> None:
        # DynamoDB deletes are idempotent: removing an absent item succeeds.
        self._table.delete_item(Key={PARTITION_ATTRIBUTE: partition, SORT_ATTRIBUTE: key})

    def ping(self) -> None:
        self._client.describe_table(TableName=self.name)


class AwsConnection(CloudConnection):
    """S3 bucket and DynamoDB table clients for the configured account.

    Both clients are built eagerly, so a misconfigured region or a missing
    credential chain surfaces when the connection is created rather than on
    the first upload, halfway through a pipeline run.
    """

    provider = PROVIDER

    def __init__(
        self, credentials: AwsCredentials | None = None, config: Mapping[str, Any] | None = None
    ):
        if config is None:
            from inferq.config import get_aws_config

            config = get_aws_config()
        self.aws_config = dict(config)
        self.credentials = credentials or AwsCredentials.from_env(self.aws_config)

        creds = self.credentials
        self.session = creds.session()
        endpoint = creds.endpoint_url

        self.s3_client = self.session.client("s3", endpoint_url=endpoint)
        self.dynamodb_resource = self.session.resource("dynamodb", endpoint_url=endpoint)
        self.circuits_table = self.dynamodb_resource.Table(creds.table)

        self._objects = S3ObjectStore(
            self.s3_client, creds.bucket, region=creds.region, endpoint_url=endpoint
        )
        self._metadata = DynamoDbMetadataStore(self.circuits_table)

    @classmethod
    def from_env(cls, config: Mapping[str, Any] | None = None) -> AwsConnection:
        return cls(config=config)

    @property
    def objects(self) -> S3ObjectStore:
        return self._objects

    @property
    def metadata(self) -> DynamoDbMetadataStore:
        return self._metadata

    def get_s3_client(self) -> Any:
        """Return the boto3 S3 client, for AWS-specific work."""
        return self.s3_client

    def get_dynamodb_resource(self) -> Any:
        """Return the boto3 DynamoDB resource, for AWS-specific work."""
        return self.dynamodb_resource

    def get_circuits_table(self) -> Any:
        """Return the boto3 DynamoDB Table resource for the circuits table."""
        return self.circuits_table


__all__ = [
    "PROVIDER",
    "AwsConnection",
    "AwsCredentials",
    "AwsCredentialsError",
    "DynamoDbMetadataStore",
    "S3ObjectStore",
    "from_dynamo",
    "to_dynamo",
]
