"""Tests for the AWS backend, run entirely offline.

Nothing here reaches AWS. The read side of S3 goes through
``botocore.stub.Stubber``, which validates every request against the real
service model, so a malformed call fails here rather than in production. The
write side and DynamoDB go through recording fakes, because what matters there
is the exact request shape -- the projection expression, the aliased attribute
names, the pagination key -- and a fake can assert on it directly.

The properties pinned here are the ones a migration depends on: values written
on AWS read back as the values that were written, and pagination state survives
a round trip through an opaque cursor.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

boto3 = pytest.importorskip("boto3")
pytest.importorskip("botocore")

from botocore.exceptions import ClientError  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from inferq.remote import decode_cursor, encode_cursor  # noqa: E402
from inferq.remote.metadata import encode_fields  # noqa: E402
from inferq.remote.providers.aws import (  # noqa: E402
    PARTITION_ATTRIBUTE,
    SORT_ATTRIBUTE,
    TIMESTAMP_ATTRIBUTE,
    AwsCredentials,
    AwsCredentialsError,
    DynamoDbMetadataStore,
    S3ObjectStore,
    from_dynamo,
    to_dynamo,
)

# -- Value coercion -----------------------------------------------------------


@pytest.mark.parametrize("value", [0.0, 1.25, 0.1, -3.5e-9, 1e20])
def test_floats_round_trip_through_decimal(value):
    """DynamoDB has no float type, so every float is stored as a decimal.

    Going through ``str`` rather than ``Decimal(float)`` is what makes this
    exact: the binary expansion of 0.1 would otherwise come back as a
    seventeen-digit decimal that no longer compares equal.
    """
    stored = to_dynamo(value)
    assert isinstance(stored, Decimal)
    assert from_dynamo(stored) == value


def test_integers_stay_integers():
    assert from_dynamo(to_dynamo(7)) == 7
    assert isinstance(from_dynamo(to_dynamo(7)), int)


def test_numpy_scalars_are_reduced_to_natives():
    """Feature extraction emits numpy types; boto3 refuses them outright."""
    assert from_dynamo(to_dynamo(np.int64(12))) == 12
    assert from_dynamo(to_dynamo(np.float64(1.5))) == 1.5
    assert to_dynamo(np.bool_(True)) is True
    assert from_dynamo(to_dynamo(np.array([1, 2, 3]))) == [1, 2, 3]


def test_numpy_floats_do_not_arrive_as_floats():
    assert isinstance(to_dynamo(np.float32(0.5)), Decimal)


def test_booleans_are_not_treated_as_numbers():
    """``bool`` is an ``int`` subclass; storing True as 1 would lose the type."""
    assert to_dynamo(True) is True
    assert to_dynamo(False) is False


def test_structures_are_json_encoded_by_the_neutral_layer():
    """Nested values become JSON strings before a provider ever sees them."""
    encoded = encode_fields({"depths": [1, 2], "counts": {"h": 2}})
    assert encoded["depths"] == "[1, 2]"
    assert json.loads(encoded["counts"]) == {"h": 2}
    assert to_dynamo(encoded["depths"]) == "[1, 2]"


def test_nested_structures_handed_straight_to_the_store_still_convert():
    stored = to_dynamo({"a": [1.5, 2], "b": {"c": 0.25}})
    assert stored == {"a": [Decimal("1.5"), 2], "b": {"c": Decimal("0.25")}}
    assert from_dynamo(stored) == {"a": [1.5, 2], "b": {"c": 0.25}}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_have_no_representation(value):
    assert to_dynamo(value) is None


def test_non_finite_attributes_are_dropped_with_a_warning(caplog):
    """A failed simulation must not poison a whole record.

    The attribute is left absent, which reads back as 'not measured' rather
    than as a wrong number, and the record still lands.
    """
    table = FakeTable()
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    with caplog.at_level("WARNING"):
        store.put_record("circuits", "aa", {"fidelity": math.nan, "num_qubits": 3})

    item = table.put_items[-1]
    assert "fidelity" not in item
    assert item["num_qubits"] == 3
    assert "fidelity" in caplog.text


def test_empty_strings_are_stored():
    """Empty strings are legal in non-key attributes and carry meaning."""
    table = FakeTable()
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    store.put_record("circuits", "aa", {"note": ""})
    assert table.put_items[-1]["note"] == ""


# -- DynamoDB fakes -----------------------------------------------------------


class FakeDynamoClient:
    """Records control-plane calls; raises whatever a test asks it to."""

    def __init__(self, *, create_error: ClientError | None = None):
        self.create_error = create_error
        self.created: list[dict] = []
        self.waited: list[str] = []
        self.described: list[str] = []

    def create_table(self, **kwargs):
        if self.create_error is not None:
            raise self.create_error
        self.created.append(kwargs)
        return {}

    def get_waiter(self, name):
        client = self

        class Waiter:
            def wait(self, TableName):  # noqa: N803 - boto3 spelling
                client.waited.append(TableName)

        return Waiter()

    def describe_table(self, TableName):  # noqa: N803 - boto3 spelling
        self.described.append(TableName)
        return {}


class FakeTable:
    """Records data-plane calls and replays canned responses."""

    name = "circuits"

    def __init__(self, *, items=None, pages=None):
        self.items = items or {}
        self.pages = list(pages or [])
        self.put_items: list[dict] = []
        self.updates: list[dict] = []
        self.deletes: list[dict] = []
        self.requests: list[dict] = []

    def put_item(self, Item):  # noqa: N803 - boto3 spelling
        self.put_items.append(Item)

    def update_item(self, **kwargs):
        self.updates.append(kwargs)

    def delete_item(self, Key):  # noqa: N803 - boto3 spelling
        self.deletes.append(Key)

    def get_item(self, Key):  # noqa: N803 - boto3 spelling
        item = self.items.get((Key[PARTITION_ATTRIBUTE], Key[SORT_ATTRIBUTE]))
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        self.requests.append(kwargs)
        return self.pages.pop(0) if self.pages else {"Items": []}

    scan = query


# -- DynamoDB behaviour -------------------------------------------------------


def test_put_record_writes_the_key_schema_and_a_timestamp():
    table = FakeTable()
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    store.put_record("circuits", "aa", {"num_qubits": 3})

    item = table.put_items[-1]
    assert item[PARTITION_ATTRIBUTE] == "circuits"
    assert item[SORT_ATTRIBUTE] == "aa"
    # An ISO-8601 UTC string, so the attribute sorts lexicographically and
    # reads the same on either cloud.
    parsed = datetime.fromisoformat(item[TIMESTAMP_ATTRIBUTE])
    assert parsed.utcoffset() == UTC.utcoffset(None)


def test_merge_record_aliases_every_attribute_name():
    """Every name is aliased, not only the ones that look reserved.

    DynamoDB's reserved-word list includes ordinary words like ``size`` and
    ``status``, which is exactly the vocabulary feature extraction produces.
    Aliasing unconditionally removes the whole class of failure.
    """
    table = FakeTable()
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    store.merge_record("circuits", "aa", {"size": 4, "status": "done"})

    update = table.updates[-1]
    assert update["Key"] == {PARTITION_ATTRIBUTE: "circuits", SORT_ATTRIBUTE: "aa"}
    assert update["UpdateExpression"].startswith("SET ")
    # No raw attribute name may appear in the expression itself.
    assert "size" not in update["UpdateExpression"]
    assert "status" not in update["UpdateExpression"]
    assert set(update["ExpressionAttributeNames"].values()) == {
        "size",
        "status",
        TIMESTAMP_ATTRIBUTE,
    }
    assert {4, "done"} <= set(update["ExpressionAttributeValues"].values())


def test_merge_record_with_nothing_to_write_touches_nothing():
    """An empty update must not create a record or move its timestamp."""
    table = FakeTable()
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    store.merge_record("circuits", "aa", {})
    assert table.updates == []


def test_get_record_separates_fields_from_addressing():
    now = datetime.now(UTC).isoformat()
    table = FakeTable(
        items={
            ("circuits", "aa"): {
                PARTITION_ATTRIBUTE: "circuits",
                SORT_ATTRIBUTE: "aa",
                TIMESTAMP_ATTRIBUTE: now,
                "num_qubits": Decimal("3"),
                "fidelity": Decimal("0.5"),
            }
        }
    )
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    record = store.get_record("circuits", "aa")

    assert record is not None
    assert record.partition == "circuits"
    assert record.key == "aa"
    assert record.fields == {"num_qubits": 3, "fidelity": 0.5}
    assert record.timestamp == datetime.fromisoformat(now)


def test_get_record_returns_none_when_absent():
    store = DynamoDbMetadataStore(FakeTable(), client=FakeDynamoClient())
    assert store.get_record("circuits", "missing") is None


def test_unparseable_timestamp_does_not_break_a_read():
    table = FakeTable(
        items={
            ("circuits", "aa"): {
                PARTITION_ATTRIBUTE: "circuits",
                SORT_ATTRIBUTE: "aa",
                TIMESTAMP_ATTRIBUTE: "not a date",
            }
        }
    )
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    record = store.get_record("circuits", "aa")
    assert record is not None
    assert record.timestamp is None


def test_list_records_projects_only_what_it_needs():
    table = FakeTable(pages=[{"Items": [{SORT_ATTRIBUTE: "aa", "num_qubits": Decimal("3")}]}])
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    records = list(store.list_records("circuits", select=("num_qubits",), limit=10))

    request = table.requests[-1]
    projected = set(request["ExpressionAttributeNames"].values())
    # The addressing attributes are always projected: without them a row could
    # not say which circuit it describes.
    assert projected == {PARTITION_ATTRIBUTE, SORT_ATTRIBUTE, TIMESTAMP_ATTRIBUTE, "num_qubits"}
    assert "num_qubits" not in request["ProjectionExpression"]
    assert request["Limit"] == 10
    assert [r.fields for r in records] == [{"num_qubits": 3}]


def test_list_records_uses_a_query_when_a_partition_is_named():
    """A keyed read, not a table scan: the catalogue lives in one partition."""
    table = FakeTable(pages=[{"Items": []}])
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    list(store.list_records("circuits"))
    assert table.requests[-1]["KeyConditionExpression"] == "#pk = :pk"
    assert table.requests[-1]["ExpressionAttributeValues"] == {":pk": "circuits"}


def test_list_records_stops_at_the_limit_across_pages():
    table = FakeTable(
        pages=[
            {"Items": [{SORT_ATTRIBUTE: "a"}, {SORT_ATTRIBUTE: "b"}], "LastEvaluatedKey": {"x": 1}},
            {"Items": [{SORT_ATTRIBUTE: "c"}, {SORT_ATTRIBUTE: "d"}]},
        ]
    )
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    assert [r.key for r in store.list_records("circuits", limit=3)] == ["a", "b", "c"]


def test_scan_records_round_trips_its_pagination_key():
    """The DynamoDB ``LastEvaluatedKey`` survives as an opaque cursor.

    A resumable export checkpoints the cursor between pages, so it has to be a
    plain string on both clouds, and handing it back has to resume exactly
    where the previous page stopped.
    """
    last_key = {PARTITION_ATTRIBUTE: "circuits", SORT_ATTRIBUTE: "aa"}
    table = FakeTable(
        pages=[
            {"Items": [{SORT_ATTRIBUTE: "aa"}], "LastEvaluatedKey": last_key},
            {"Items": [{SORT_ATTRIBUTE: "bb"}]},
        ]
    )
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())

    first = next(iter(store.scan_records("circuits", page_size=1)))
    assert [r.key for r in first.records] == ["aa"]
    assert first.cursor is not None
    assert decode_cursor(first.cursor) == {"LastEvaluatedKey": last_key}

    second = next(iter(store.scan_records("circuits", page_size=1, cursor=first.cursor)))
    assert table.requests[-1]["ExclusiveStartKey"] == last_key
    assert second.cursor is None


def test_scan_cursor_is_a_plain_string_a_checkpoint_can_hold():
    cursor = encode_cursor({"LastEvaluatedKey": {"pk": "circuits", "sk": "ff" * 32}})
    assert json.loads(json.dumps({"cursor": cursor}))["cursor"] == cursor


def test_scan_records_yields_one_page_per_call_to_the_service():
    """Pagination is the caller's, so it can checkpoint between pages."""
    table = FakeTable(pages=[{"Items": [], "LastEvaluatedKey": {"k": 1}}])
    store = DynamoDbMetadataStore(table, client=FakeDynamoClient())
    pages = list(store.scan_records("circuits", page_size=5))
    assert len(pages) == 1
    assert len(table.requests) == 1


def test_ensure_table_creates_on_demand_and_waits():
    """A CREATING table rejects writes, so the first upload would otherwise fail."""
    client = FakeDynamoClient()
    store = DynamoDbMetadataStore(FakeTable(), client=client)

    store.ensure_table()

    assert client.created[0]["BillingMode"] == "PAY_PER_REQUEST"
    assert client.created[0]["KeySchema"] == [
        {"AttributeName": PARTITION_ATTRIBUTE, "KeyType": "HASH"},
        {"AttributeName": SORT_ATTRIBUTE, "KeyType": "RANGE"},
    ]
    assert client.waited == ["circuits"]


def test_ensure_table_is_idempotent():
    error = ClientError({"Error": {"Code": "ResourceInUseException"}}, "CreateTable")
    client = FakeDynamoClient(create_error=error)
    DynamoDbMetadataStore(FakeTable(), client=client).ensure_table()
    assert client.waited == []


def test_ensure_table_reraises_anything_else():
    error = ClientError({"Error": {"Code": "AccessDeniedException"}}, "CreateTable")
    client = FakeDynamoClient(create_error=error)
    with pytest.raises(ClientError):
        DynamoDbMetadataStore(FakeTable(), client=client).ensure_table()


# -- S3 -----------------------------------------------------------------------


@pytest.fixture
def s3_client():
    return boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def test_object_url_is_virtual_hosted_style():
    store = S3ObjectStore(None, "inferq-circuits", region="eu-west-1")
    assert (
        store.object_url("ab/abcd.qpy")
        == "https://inferq-circuits.s3.eu-west-1.amazonaws.com/ab/abcd.qpy"
    )


def test_object_url_falls_back_to_path_style_behind_a_custom_endpoint():
    """LocalStack and MinIO do not resolve per-bucket hostnames."""
    store = S3ObjectStore(None, "bucket", region="us-east-1", endpoint_url="http://localhost:4566/")
    assert store.object_url("ab/cd.qpy") == "http://localhost:4566/bucket/ab/cd.qpy"


def test_upload_uses_the_multipart_transfer_config():
    """Large circuits are split and uploaded concurrently, as on Azure."""
    from inferq.remote.providers.aws import _MULTIPART_THRESHOLD, _TRANSFER_CONFIG

    assert _TRANSFER_CONFIG.multipart_threshold == _MULTIPART_THRESHOLD == 4 * 1024 * 1024
    assert _TRANSFER_CONFIG.max_request_concurrency == 4


def test_put_object_sanitises_metadata_to_ascii():
    """S3 sends user metadata as HTTP headers, which cannot carry non-ASCII.

    Left alone, a stray character fails the request at signing time with an
    error that says nothing about which value caused it.
    """

    class RecordingClient:
        def __init__(self):
            self.calls = []

        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs, Config):  # noqa: N803
            self.calls.append((fileobj.read(), bucket, key, ExtraArgs, Config))

    client = RecordingClient()
    store = S3ObjectStore(client, "bucket", region="us-east-1")

    url = store.put_object(
        "ab/cd.qpy",
        b"payload",
        content_type="application/octet-stream",
        metadata={"format": "qpy", "label": "état"},
    )

    data, bucket, key, extra, config = client.calls[0]
    assert (data, bucket, key) == (b"payload", "bucket", "ab/cd.qpy")
    assert extra["ContentType"] == "application/octet-stream"
    assert extra["Metadata"]["format"] == "qpy"
    assert extra["Metadata"]["label"].isascii()
    assert config.max_request_concurrency == 4
    assert url == store.object_url("ab/cd.qpy")


def test_exists_is_false_for_a_missing_key(s3_client):
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
        assert store.exists("ab/cd.qpy") is False


def test_exists_propagates_a_permission_error(s3_client):
    """A 403 is not 'absent'; treating it as absent would mask a misconfiguration."""
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_client_error("head_object", service_error_code="403", http_status_code=403)
        with pytest.raises(ClientError):
            store.exists("ab/cd.qpy")


def test_get_object_reads_the_body(s3_client):
    from io import BytesIO

    from botocore.response import StreamingBody

    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(b"circuit"), 7)},
            {"Bucket": "bucket", "Key": "ab/cd.qpy"},
        )
        assert store.get_object("ab/cd.qpy") == b"circuit"


def test_list_objects_follows_the_paginator(s3_client):
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    modified = datetime.now(UTC)
    with Stubber(s3_client) as stub:
        stub.add_response(
            "list_objects_v2",
            {
                "Contents": [{"Key": "ab/one.qpy", "Size": 10, "LastModified": modified}],
                "IsTruncated": True,
                "NextContinuationToken": "t",
            },
            {"Bucket": "bucket", "Prefix": "ab/"},
        )
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "ab/two.qpy", "Size": 20, "LastModified": modified}]},
            {"Bucket": "bucket", "Prefix": "ab/", "ContinuationToken": "t"},
        )
        infos = list(store.list_objects("ab/"))

    assert [info.key for info in infos] == ["ab/one.qpy", "ab/two.qpy"]
    assert [info.size for info in infos] == [10, 20]
    assert infos[0].metadata == {}


def test_listing_metadata_costs_one_head_per_key(s3_client):
    """S3 listings do not carry user metadata; document the cost in a test."""
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "ab/one.qpy", "Size": 1}]},
            {"Bucket": "bucket"},
        )
        stub.add_response(
            "head_object",
            {"Metadata": {"sha256": "abc", "format": "qpy"}},
            {"Bucket": "bucket", "Key": "ab/one.qpy"},
        )
        infos = list(store.list_objects(include_metadata=True))
        stub.assert_no_pending_responses()

    assert infos[0].metadata == {"sha256": "abc", "format": "qpy"}


def test_a_key_deleted_mid_listing_does_not_abort_the_listing(s3_client):
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_response(
            "list_objects_v2", {"Contents": [{"Key": "ab/one.qpy"}]}, {"Bucket": "bucket"}
        )
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
        infos = list(store.list_objects(include_metadata=True))
    assert [info.key for info in infos] == ["ab/one.qpy"]
    assert infos[0].metadata == {}


def test_ping_checks_the_bucket(s3_client):
    store = S3ObjectStore(s3_client, "bucket", region="us-east-1")
    with Stubber(s3_client) as stub:
        stub.add_response("head_bucket", {}, {"Bucket": "bucket"})
        store.ping()
        stub.assert_no_pending_responses()


# -- Credentials --------------------------------------------------------------


def _clear_aws_env(monkeypatch):
    for name in (
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_S3_BUCKET",
        "AWS_DYNAMODB_TABLE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ENDPOINT_URL",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    # ``.env`` is read by the loader; neutralise it so a developer's own file
    # cannot decide whether these tests pass.
    monkeypatch.setattr("inferq.remote.providers.aws.load_dotenv", lambda *a, **k: None)


def test_missing_settings_are_reported_all_at_once(monkeypatch):
    """One run, one fix: an operator should not discover these one at a time."""
    _clear_aws_env(monkeypatch)

    with pytest.raises(AwsCredentialsError) as excinfo:
        AwsCredentials.from_env({})

    message = str(excinfo.value)
    assert "AWS_REGION" in message
    assert "AWS_S3_BUCKET" in message
    assert "AWS_DYNAMODB_TABLE" in message


def test_the_region_alias_is_accepted(monkeypatch):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DYNAMODB_TABLE", "table")

    assert AwsCredentials.from_env({}).region == "us-west-2"


def test_configuration_wins_over_the_environment(monkeypatch):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("AWS_S3_BUCKET", "from-env")

    credentials = AwsCredentials.from_env(
        {"region": "eu-central-1", "bucket": "from-config", "table": "table"}
    )
    assert credentials.bucket == "from-config"


def test_no_keys_means_the_default_credential_chain(monkeypatch):
    """A deployment inside AWS authenticates by IAM role, with no secrets set."""
    _clear_aws_env(monkeypatch)
    credentials = AwsCredentials.from_env({"region": "us-east-1", "bucket": "b", "table": "t"})
    assert credentials.access_key_id is None
    assert credentials.session().region_name == "us-east-1"


def test_explicit_keys_override_the_chain(monkeypatch):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token")

    credentials = AwsCredentials.from_env({"region": "us-east-1", "bucket": "b", "table": "t"})
    resolved = credentials.session().get_credentials()
    assert resolved.access_key == "AKIAEXAMPLE"
    assert resolved.token == "token"


def test_the_aws_provider_is_registered():
    from inferq.remote import available_providers, connection_class

    assert "aws" in available_providers()
    assert connection_class("aws").provider == "aws"
