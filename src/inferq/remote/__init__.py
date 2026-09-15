"""Provider-neutral cloud storage for circuits and their metadata.

Two interfaces carry everything: an :class:`~inferq.remote.base.ObjectStore`
for serialized circuits and a :class:`~inferq.remote.base.MetadataStore` for
their feature records. A :class:`~inferq.remote.base.CloudConnection` hands
out one of each, and :func:`~inferq.remote.factory.get_connection` builds the
connection the environment asks for -- Azure Blob + Table, or S3 + DynamoDB.

Everything above that boundary (:mod:`inferq.remote.circuits` and
:mod:`inferq.remote.metadata`) is written once and runs on either cloud.

Importing this package pulls in no cloud SDK: provider backends live under
``inferq.remote.providers`` and are imported only when one is selected. The
``Azure*`` names re-exported here are resolved the same way, on first access.
"""

from __future__ import annotations

from typing import Any

from .base import (
    CIRCUITS_PARTITION,
    CloudConnection,
    CloudCredentialsError,
    MetadataStore,
    ObjectInfo,
    ObjectStore,
    Record,
    RecordPage,
    decode_cursor,
    encode_cursor,
    field_safe,
    table_safe,
)
from .circuits import blob_path_for, download_circuit_blob, upload_circuit_blob
from .factory import (
    available_providers,
    connection_class,
    get_connection,
    register_provider,
    resolve_provider,
)
from .metadata import (
    delete_circuit_metadata,
    get_circuit_metadata,
    list_circuits,
    save_circuit_metadata,
    update_circuit_metadata,
)

#: Provider-specific names kept importable from the package root, resolved on
#: first access so that the SDK behind them is never a cost of importing
#: ``inferq.remote``.
_LAZY_EXPORTS = {
    "AzureConnection": "inferq.remote.providers.azure",
    "AzureCredentials": "inferq.remote.providers.azure",
    "AzureCredentialsError": "inferq.remote.providers.azure",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])


__all__ = [
    "CIRCUITS_PARTITION",
    "AzureConnection",
    "AzureCredentials",
    "AzureCredentialsError",
    "CloudConnection",
    "CloudCredentialsError",
    "MetadataStore",
    "ObjectInfo",
    "ObjectStore",
    "Record",
    "RecordPage",
    "available_providers",
    "blob_path_for",
    "connection_class",
    "decode_cursor",
    "delete_circuit_metadata",
    "download_circuit_blob",
    "encode_cursor",
    "field_safe",
    "get_circuit_metadata",
    "get_connection",
    "list_circuits",
    "register_provider",
    "resolve_provider",
    "save_circuit_metadata",
    "table_safe",
    "update_circuit_metadata",
    "upload_circuit_blob",
]
