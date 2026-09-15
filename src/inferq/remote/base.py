"""Provider-neutral interfaces for InferQ's cloud storage layer.

InferQ stores two kinds of things in the cloud: serialized circuits, which are
opaque blobs addressed by a path, and circuit metadata, which is a wide,
sparsely populated record addressed by a ``(partition, key)`` pair. Azure
serves those with Blob Storage and Table Storage; AWS serves them with S3 and
DynamoDB. This module defines the two interfaces -- :class:`ObjectStore` and
:class:`MetadataStore` -- plus the :class:`CloudConnection` that hands them
out, so that everything above the provider boundary is written once.

Nothing here imports a cloud SDK. Provider packages under
``inferq.remote.providers`` do, and they import it lazily, so that merely
importing :mod:`inferq.remote` stays free of boto3 and the Azure SDK.
"""

from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Partition that every circuit metadata record lives in. Circuit metadata is
#: read either by hash or in full scans, so a single partition is the right
#: shape; it is named here because both providers need the same value.
CIRCUITS_PARTITION = "circuits"

#: Defaults used when the configuration names neither a bucket nor a table.
DEFAULT_BUCKET_NAME = "circuits"
DEFAULT_TABLE_NAME = "circuits"


class CloudCredentialsError(RuntimeError):
    """Raised when the environment is missing credentials a provider needs.

    Providers raise this naming *all* missing variables at once, so that an
    operator fixes their environment in one pass rather than one variable per
    run.
    """


def field_safe(name: str) -> str:
    """Normalise a feature name into an attribute name every provider accepts.

    Azure Tables restrict property names to alphanumerics and underscores and
    forbid a leading digit. DynamoDB is far more permissive, but the rule is
    applied identically on both sides on purpose: metadata written by the Azure
    backend and metadata written by the AWS backend must be comparable
    attribute for attribute, so that migrating between them is a copy rather
    than a transformation.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", name.strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"prop_{cleaned}"
    return cleaned.lower()


#: Historical name for :func:`field_safe`, kept because it appears in call
#: sites and tests that predate the provider split.
table_safe = field_safe


@dataclass(frozen=True)
class ObjectInfo:
    """One object in an :class:`ObjectStore` listing."""

    key: str
    size: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    last_modified: datetime | None = None


@dataclass(frozen=True)
class Record:
    """One metadata record, provider-neutral.

    ``fields`` excludes the partition key, the row key and any provider system
    attributes; ``timestamp`` carries the record's write time where the
    provider records one.
    """

    partition: str
    key: str
    fields: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RecordPage:
    """A page of records plus the cursor that resumes after it.

    ``cursor`` is ``None`` on the last page. It is otherwise an opaque string:
    callers persist it -- checkpoint files do exactly that -- and hand it back,
    but never parse it. Each provider encodes its own resumption state into it.
    """

    records: list[Record]
    cursor: str | None = None


def encode_cursor(state: Mapping[str, Any]) -> str:
    """Pack provider resumption state into an opaque, persistable string.

    Base64 of compact JSON: durable across processes, safe to drop into a JSON
    checkpoint file, and identical in shape for every provider.
    """
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Unpack a cursor produced by :func:`encode_cursor`.

    Raises:
        ValueError: if the cursor is not one this layer produced.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        state = json.loads(raw)
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("Malformed pagination cursor") from exc
    if not isinstance(state, dict):
        raise ValueError("Malformed pagination cursor: expected a JSON object")
    return state


class ObjectStore(ABC):
    """A flat, key-addressed store of byte blobs."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Container or bucket name, for logging and operator messages."""

    @abstractmethod
    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        """Write ``data`` at ``key``, overwriting, and return its URL."""

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Read the whole object at ``key``."""

    @abstractmethod
    def object_url(self, key: str) -> str:
        """Return the URL an object at ``key`` would have, without a round trip."""

    @abstractmethod
    def list_objects(
        self, prefix: str | None = None, *, include_metadata: bool = False
    ) -> Iterator[ObjectInfo]:
        """Iterate objects, optionally under ``prefix``.

        ``include_metadata`` is opt-in because it is not free on every
        provider: S3 listings do not carry user metadata, so the AWS backend
        pays one ``HeadObject`` per key to fill it in.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether an object exists at ``key``."""

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Delete ``key``. Deleting a missing key is not an error."""

    @abstractmethod
    def ping(self) -> None:
        """Raise if the store is unreachable or the credentials are rejected."""


class MetadataStore(ABC):
    """A ``(partition, key)``-addressed store of flat attribute records."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Table name, for logging and operator messages."""

    @abstractmethod
    def ensure_table(self) -> None:
        """Create the backing table if it does not exist. Idempotent."""

    @abstractmethod
    def put_record(self, partition: str, key: str, fields: Mapping[str, Any]) -> None:
        """Write a record, replacing any record already at that address."""

    @abstractmethod
    def merge_record(self, partition: str, key: str, updates: Mapping[str, Any]) -> None:
        """Set the named attributes, leaving every other attribute untouched."""

    @abstractmethod
    def get_record(self, partition: str, key: str) -> Record | None:
        """Read one record, or ``None`` when it does not exist."""

    @abstractmethod
    def list_records(
        self,
        partition: str | None = None,
        *,
        select: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        """Iterate records, optionally projecting only ``select`` attributes."""

    @abstractmethod
    def scan_records(
        self,
        partition: str | None = None,
        *,
        page_size: int = 1000,
        cursor: str | None = None,
    ) -> Iterator[RecordPage]:
        """Iterate whole pages, so a caller can checkpoint between them.

        This is the interface behind the resumable Parquet export: each page
        carries the cursor that resumes *after* it, which the caller writes to
        its checkpoint before it moves on.
        """

    @abstractmethod
    def delete_record(self, partition: str, key: str) -> None:
        """Delete one record. Deleting a missing record is not an error."""

    @abstractmethod
    def ping(self) -> None:
        """Raise if the table is unreachable or the credentials are rejected."""


class CloudConnection(ABC):
    """A provider's object store and metadata store, constructed together.

    Implementations build their clients eagerly in ``__init__`` so that bad
    credentials surface where the connection is made rather than deep inside a
    pipeline run.
    """

    #: Short provider identifier, e.g. ``"azure"`` or ``"aws"``.
    provider: str = ""

    @property
    @abstractmethod
    def objects(self) -> ObjectStore:
        """The blob/object side of this provider."""

    @property
    @abstractmethod
    def metadata(self) -> MetadataStore:
        """The record/table side of this provider."""

    @classmethod
    @abstractmethod
    def from_env(cls, config: Mapping[str, Any] | None = None) -> CloudConnection:
        """Build a connection from the environment and an optional config view."""

    def ping(self) -> None:
        """Check both stores, raising the first failure."""
        self.objects.ping()
        self.metadata.ping()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<{type(self).__name__} provider={self.provider!r} "
            f"bucket={self.objects.name!r} table={self.metadata.name!r}>"
        )


__all__ = [
    "CIRCUITS_PARTITION",
    "DEFAULT_BUCKET_NAME",
    "DEFAULT_TABLE_NAME",
    "CloudConnection",
    "CloudCredentialsError",
    "MetadataStore",
    "ObjectInfo",
    "ObjectStore",
    "Record",
    "RecordPage",
    "decode_cursor",
    "encode_cursor",
    "field_safe",
    "table_safe",
]
