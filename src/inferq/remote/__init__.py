"""Azure Blob and Table Storage clients.

:class:`AzureConnection` is the single place credentials are resolved; the blob and
table helpers take an already-constructed client so they stay testable without any
account. Importing this package does not contact Azure.
"""

from .blob import download_circuit_blob, upload_circuit_blob
from .connection import AzureConnection, AzureCredentials, AzureCredentialsError
from .table import (
    delete_circuit_metadata_from_table,
    get_circuit_metadata_from_table,
    list_circuits_from_table,
    save_circuit_metadata_to_table,
    update_circuit_metadata_in_table,
)

__all__ = [
    "AzureConnection",
    "AzureCredentials",
    "AzureCredentialsError",
    "delete_circuit_metadata_from_table",
    "download_circuit_blob",
    "get_circuit_metadata_from_table",
    "list_circuits_from_table",
    "save_circuit_metadata_to_table",
    "update_circuit_metadata_in_table",
    "upload_circuit_blob",
]
