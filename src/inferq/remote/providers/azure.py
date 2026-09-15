"""Azure backend: Blob Storage objects and Table Storage records.

Credentials are read when a connection is constructed, never at import time,
so importing this module in a test or offline environment is safe.

Authentication prefers the account key when one is available, because it is
the only method that reliably authorizes Table operations, and falls back to
the SAS token otherwise. That preference, and the SAS fallbacks around it, are
load-bearing against the production account and are preserved exactly as they
were before the provider split.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from azure.core.credentials import AzureSasCredential
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableClient, TableServiceClient
from azure.storage.blob import ContainerClient, ContentSettings
from dotenv import load_dotenv

from inferq.remote.base import (
    DEFAULT_BUCKET_NAME,
    DEFAULT_TABLE_NAME,
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

logger = logging.getLogger(__name__)

PROVIDER = "azure"

#: Entity keys Azure owns; they are addressing or bookkeeping, never metadata.
_SYSTEM_KEYS = frozenset({"PartitionKey", "RowKey", "Timestamp", "etag"})

#: Parallel block count for blob uploads. Blobs over 4 MiB are split
#: automatically and the blocks go up concurrently.
_UPLOAD_CONCURRENCY = 4


class AzureCredentialsError(CloudCredentialsError):
    """Raised when required Azure environment variables are missing.

    Subclasses the provider-neutral error so that callers can catch either.
    """


@dataclass(frozen=True)
class AzureCredentials:
    """Azure storage credentials resolved from the environment."""

    storage_account_name: str
    sas_token: str
    container_sas_url: str
    account_key: str | None

    #: Environment variables that must be set for any Azure access.
    REQUIRED_VARS = (
        "AZURE_STORAGE_ACCOUNT",
        "AZURE_STORAGE_SAS_TOKEN",
        "AZURE_CONTAINER_SAS_URL",
    )

    @classmethod
    def from_env(cls) -> AzureCredentials:
        """Load credentials from the environment, consulting a local .env file.

        Raises:
            AzureCredentialsError: if any required variable is unset, naming
                all of the missing ones at once.
        """
        load_dotenv()
        missing = [var for var in cls.REQUIRED_VARS if not os.environ.get(var)]
        if missing:
            raise AzureCredentialsError(
                "Missing required Azure environment variables: "
                f"{', '.join(missing)}. See .env.example."
            )
        return cls(
            storage_account_name=os.environ["AZURE_STORAGE_ACCOUNT"],
            sas_token=os.environ["AZURE_STORAGE_SAS_TOKEN"],
            container_sas_url=os.environ["AZURE_CONTAINER_SAS_URL"],
            account_key=os.environ.get("AZURE_STORAGE_ACCOUNT_KEY"),
        )

    @property
    def blob_endpoint(self) -> str:
        return f"https://{self.storage_account_name}.blob.core.windows.net"

    @property
    def table_endpoint(self) -> str:
        return f"https://{self.storage_account_name}.table.core.windows.net"

    @property
    def connection_string(self) -> str:
        """Account-key connection string. Only valid when ``account_key`` is set."""
        return (
            "DefaultEndpointsProtocol=https;"
            f"AccountName={self.storage_account_name};"
            f"AccountKey={self.account_key};"
            "EndpointSuffix=core.windows.net"
        )

    @property
    def table_endpoint_with_sas(self) -> str:
        """Table endpoint with the SAS token inlined, for the credential-object fallback."""
        token = self.sas_token if self.sas_token.startswith("?") else f"?{self.sas_token}"
        return f"{self.table_endpoint}{token}"

    @property
    def sas_credential(self) -> AzureSasCredential:
        return AzureSasCredential(self.sas_token.lstrip("?"))


def _entity_timestamp(entity: Any) -> datetime | None:
    """Best-effort write time for a table entity.

    Azure surfaces it either as a selected ``Timestamp`` property or on the
    entity's ``metadata`` mapping, depending on the query. Neither is
    guaranteed, so both are probed and a missing timestamp is ``None`` rather
    than an error.
    """
    timestamp = entity.get("Timestamp")
    if isinstance(timestamp, datetime):
        return timestamp
    entity_metadata = getattr(entity, "metadata", None)
    if isinstance(entity_metadata, Mapping):
        from_metadata = entity_metadata.get("timestamp")
        if isinstance(from_metadata, datetime):
            return from_metadata
    return None


def _entity_to_record(entity: Any, partition_fallback: str) -> Record:
    """Convert a table entity into a provider-neutral :class:`Record`."""
    fields = {key: value for key, value in entity.items() if key not in _SYSTEM_KEYS}
    return Record(
        partition=entity.get("PartitionKey", partition_fallback),
        key=entity.get("RowKey", ""),
        fields=fields,
        timestamp=_entity_timestamp(entity),
    )


class AzureObjectStore(ObjectStore):
    """:class:`~inferq.remote.base.ObjectStore` over a blob container."""

    def __init__(self, container_client: ContainerClient):
        self._client = container_client

    @property
    def name(self) -> str:
        return self._client.container_name

    @property
    def container_client(self) -> ContainerClient:
        """The underlying SDK client, for Azure-specific work."""
        return self._client

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        blob_client = self._client.get_blob_client(key)
        blob_client.upload_blob(
            data,
            overwrite=True,
            max_concurrency=_UPLOAD_CONCURRENCY,
            content_settings=ContentSettings(content_type=content_type),
            metadata=dict(metadata or {}),
        )
        return blob_client.url

    def get_object(self, key: str) -> bytes:
        return self._client.get_blob_client(key).download_blob().readall()

    def object_url(self, key: str) -> str:
        return self._client.get_blob_client(key).url

    def list_objects(
        self, prefix: str | None = None, *, include_metadata: bool = False
    ) -> Iterator[ObjectInfo]:
        # Azure returns user metadata inline when asked, so this costs nothing
        # beyond a slightly larger listing response.
        include = ["metadata"] if include_metadata else None
        for blob in self._client.list_blobs(name_starts_with=prefix, include=include):
            yield ObjectInfo(
                key=blob.name,
                size=getattr(blob, "size", None),
                metadata=dict(getattr(blob, "metadata", None) or {}),
                last_modified=getattr(blob, "last_modified", None),
            )

    def exists(self, key: str) -> bool:
        return bool(self._client.get_blob_client(key).exists())

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_blob(key)
        except ResourceNotFoundError:
            logger.debug("Blob %s already absent", key)

    def ping(self) -> None:
        self._client.get_container_properties()


class AzureMetadataStore(MetadataStore):
    """:class:`~inferq.remote.base.MetadataStore` over a storage table."""

    def __init__(self, table_client: TableClient):
        self._client = table_client

    @property
    def name(self) -> str:
        return self._client.table_name

    @property
    def table_client(self) -> TableClient:
        """The underlying SDK client, for Azure-specific work."""
        return self._client

    def ensure_table(self) -> None:
        try:
            self._client.create_table()
            logger.info("Created table: %s", self.name)
        except Exception as exc:  # noqa: BLE001 - the SDK's error type varies by auth mode
            if "TableAlreadyExists" in str(exc) or "already exists" in str(exc).lower():
                logger.debug("Table %s already exists", self.name)
            else:
                logger.warning("Error creating table %s: %s", self.name, exc)

    def _entity(self, partition: str, key: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        entity: dict[str, Any] = {"PartitionKey": partition, "RowKey": key}
        entity.update(fields)
        return entity

    def put_record(self, partition: str, key: str, fields: Mapping[str, Any]) -> None:
        entity = self._entity(partition, key, fields)
        entity["Timestamp"] = datetime.now(UTC)
        try:
            self._client.create_entity(entity)
        except ResourceExistsError:
            self._client.update_entity(entity, mode="replace")

    def merge_record(self, partition: str, key: str, updates: Mapping[str, Any]) -> None:
        self._client.update_entity(self._entity(partition, key, updates), mode="merge")

    def get_record(self, partition: str, key: str) -> Record | None:
        try:
            entity = self._client.get_entity(partition_key=partition, row_key=key)
        except ResourceNotFoundError:
            return None
        return _entity_to_record(entity, partition)

    def list_records(
        self,
        partition: str | None = None,
        *,
        select: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        # A projection must carry the addressing columns, or the resulting
        # records could not identify themselves.
        projection = None
        if select is not None:
            projection = list(dict.fromkeys(["PartitionKey", "RowKey", "Timestamp", *select]))

        if partition is None:
            entities = self._client.list_entities(select=projection)
        else:
            entities = self._client.query_entities(
                query_filter="PartitionKey eq @partition",
                parameters={"partition": partition},
                select=projection,
            )

        for index, entity in enumerate(entities):
            if limit is not None and index >= limit:
                return
            yield _entity_to_record(entity, partition or "")

    def scan_records(
        self,
        partition: str | None = None,
        *,
        page_size: int = 1000,
        cursor: str | None = None,
    ) -> Iterator[RecordPage]:
        if partition is None:
            query = self._client.list_entities(results_per_page=page_size)
        else:
            query = self._client.query_entities(
                query_filter="PartitionKey eq @partition",
                parameters={"partition": partition},
                results_per_page=page_size,
            )

        token = decode_cursor(cursor).get("continuation_token") if cursor else None
        pages = query.by_page(continuation_token=token)
        for page in pages:
            records = [_entity_to_record(entity, partition or "") for entity in page]
            next_token = pages.continuation_token
            yield RecordPage(
                records=records,
                cursor=encode_cursor({"continuation_token": next_token}) if next_token else None,
            )

    def delete_record(self, partition: str, key: str) -> None:
        try:
            self._client.delete_entity(partition_key=partition, row_key=key)
        except ResourceNotFoundError:
            logger.debug("Entity %s/%s already absent", partition, key)

    def ping(self) -> None:
        next(iter(self._client.list_entities(results_per_page=1)), None)


class AzureConnection(CloudConnection):
    """Blob container and Table clients for the configured storage account.

    Besides the neutral :attr:`objects` and :attr:`metadata` stores, the raw
    SDK clients stay reachable. That is deliberate: research scripts under
    ``experiments/`` drive the Azure SDK directly, and forcing them through the
    neutral interface would buy nothing while losing capability.
    """

    provider = PROVIDER

    def __init__(
        self, credentials: AzureCredentials | None = None, config: Mapping[str, Any] | None = None
    ):
        if config is None:
            from inferq.config import get_azure_config

            config = get_azure_config()
        self.azure_config = dict(config)
        self.credentials = credentials or AzureCredentials.from_env()

        self.container_client = self.create_container_client()
        self.table_service_client = self.create_table_service_client()
        self.circuits_table_client = self.create_circuits_table_client()

        self._objects = AzureObjectStore(self.container_client)
        self._metadata = AzureMetadataStore(self.circuits_table_client)

    @classmethod
    def from_env(cls, config: Mapping[str, Any] | None = None) -> AzureConnection:
        return cls(config=config)

    @property
    def objects(self) -> AzureObjectStore:
        return self._objects

    @property
    def metadata(self) -> AzureMetadataStore:
        return self._metadata

    def create_container_client(self) -> ContainerClient:
        """Create the blob container client for the configured container."""
        creds = self.credentials
        container_name = self.azure_config.get("container_name") or DEFAULT_BUCKET_NAME

        # A container-scoped SAS URL already names its container, so it can only
        # be used when it refers to the container we actually want.
        if creds.container_sas_url and container_name in creds.container_sas_url:
            return ContainerClient.from_container_url(creds.container_sas_url)
        if creds.account_key:
            return ContainerClient.from_connection_string(
                creds.connection_string, container_name=container_name
            )
        return ContainerClient(
            account_url=creds.blob_endpoint,
            container_name=container_name,
            credential=creds.sas_credential,
        )

    def create_table_service_client(self) -> TableServiceClient:
        """Create the Table service client."""
        creds = self.credentials
        if creds.account_key:
            return TableServiceClient.from_connection_string(creds.connection_string)
        try:
            return TableServiceClient(
                endpoint=creds.table_endpoint, credential=creds.sas_credential
            )
        except Exception as e:  # noqa: BLE001 - fall back to the inline-SAS endpoint
            logger.warning("SAS credential authentication failed: %s", e)
            return TableServiceClient(endpoint=creds.table_endpoint_with_sas)

    def create_circuits_table_client(self) -> TableClient:
        """Create the circuits Table client, creating the table if absent."""
        creds = self.credentials
        table_name = self.azure_config.get("table_name") or DEFAULT_TABLE_NAME

        if creds.account_key:
            table_client = TableClient.from_connection_string(
                creds.connection_string, table_name=table_name
            )
        else:
            try:
                table_client = TableClient(
                    endpoint=creds.table_endpoint,
                    table_name=table_name,
                    credential=creds.sas_credential,
                )
            except Exception as e:  # noqa: BLE001 - fall back to the inline-SAS endpoint
                logger.warning("SAS credential authentication failed: %s", e)
                table_client = TableClient(
                    endpoint=creds.table_endpoint_with_sas, table_name=table_name
                )

        AzureMetadataStore(table_client).ensure_table()
        return table_client

    def get_container_client(self) -> ContainerClient:
        """Return the blob container client."""
        return self.container_client

    def get_table_service_client(self) -> TableServiceClient:
        """Return the Table service client."""
        return self.table_service_client

    def get_circuits_table_client(self) -> TableClient:
        """Return the circuits Table client."""
        return self.circuits_table_client


__all__ = [
    "AzureConnection",
    "AzureCredentials",
    "AzureCredentialsError",
    "AzureMetadataStore",
    "AzureObjectStore",
    "PROVIDER",
]
