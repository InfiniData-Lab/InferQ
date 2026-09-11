"""Azure Blob and Table client construction for InferQ.

Credentials are read lazily, when a connection is first constructed, rather than
at import time. Importing this module (directly, or transitively via
``utils.table_storage``) therefore never requires Azure configuration, so the
package remains importable in test and offline environments.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from azure.core.credentials import AzureSasCredential
from azure.data.tables import TableClient, TableServiceClient
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_CIRCUITS_TABLE_NAME = "circuits"


def table_safe(name: str) -> str:
    """Turn an arbitrary feature name into an Azure Table-safe property name.

    Azure Tables restrict property names to alphanumerics and underscores, and
    forbid a leading digit.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", name.strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"prop_{cleaned}"
    return cleaned.lower()


class AzureCredentialsError(RuntimeError):
    """Raised when required Azure environment variables are missing."""


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
    def from_env(cls) -> "AzureCredentials":
        """Load credentials from the environment, consulting a local .env file.

        Raises:
            AzureCredentialsError: if any required variable is unset, naming all
                of the missing ones at once.
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


class AzureConnection:
    """Blob container and Table clients for the configured storage account.

    Authentication prefers the account key when available, because it is the
    only method that reliably authorizes Table operations, and falls back to the
    SAS token otherwise.
    """

    def __init__(self, credentials: AzureCredentials | None = None):
        from config import get_azure_config

        self.azure_config = get_azure_config()
        self.credentials = credentials or AzureCredentials.from_env()

        self.container_client = self.create_container_client()
        self.table_service_client = self.create_table_service_client()
        self.circuits_table_client = self.create_circuits_table_client()

    def create_container_client(self) -> ContainerClient:
        """Create the blob container client for the configured container."""
        creds = self.credentials
        container_name = self.azure_config.get("container_name", "circuits")

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
        except Exception as e:
            logger.warning("SAS credential authentication failed: %s", e)
            return TableServiceClient(endpoint=creds.table_endpoint_with_sas)

    def create_circuits_table_client(self) -> TableClient:
        """Create the circuits Table client, creating the table if absent."""
        creds = self.credentials
        table_name = self.azure_config.get("table_name", DEFAULT_CIRCUITS_TABLE_NAME)

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
            except Exception as e:
                logger.warning("SAS credential authentication failed: %s", e)
                table_client = TableClient(
                    endpoint=creds.table_endpoint_with_sas, table_name=table_name
                )

        try:
            table_client.create_table()
            logger.info("Created table: %s", table_name)
        except Exception as e:
            if "TableAlreadyExists" in str(e) or "already exists" in str(e).lower():
                logger.debug("Table %s already exists", table_name)
            else:
                logger.warning("Error creating table %s: %s", table_name, e)

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
