"""Circuit metadata mapped onto a provider-neutral metadata store.

Feature extraction produces a wide, ragged dictionary: numpy scalars, numpy
arrays, nested dicts, plain strings. Storage backends accept a much narrower
set of types. This module owns that translation -- name normalisation, numpy
coercion, JSON encoding of anything structured -- so it happens once, in the
same way, no matter which cloud is behind it.

The coercion helpers are shared with the provider backends rather than
reimplemented there: a record handed straight to ``MetadataStore.put_record``
must be normalised the same way as one that came through
:func:`save_circuit_metadata`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

from inferq.remote.base import CIRCUITS_PARTITION, MetadataStore, field_safe

logger = logging.getLogger(__name__)

#: Attributes a catalogue listing needs. Everything else is left unread, which
#: keeps the projection -- and the bytes on the wire -- small.
CATALOG_FIELDS = (
    "num_qubits",
    "circuit_depth",
    "circuit_size",
    "serialization_method",
)


def json_default(obj: Any) -> Any:
    """``json.dumps`` fallback for numpy types nested inside structures."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def coerce_native(value: Any) -> Any:
    """Convert numpy types to Python natives that any backend can store."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def encode_value(value: Any) -> Any:
    """Reduce one feature value to a scalar the storage layer accepts.

    Scalars pass through; lists and dicts become JSON strings; anything else
    becomes its ``str()``. JSON encoding is how a wide, schemaless feature set
    survives a key-value store without exploding into columns.
    """
    converted = coerce_native(value)
    if isinstance(converted, (int, float, str, bool)):
        return converted
    if isinstance(converted, (list, dict)):
        return json.dumps(converted, default=json_default)
    return str(converted)


def encode_fields(features: dict[str, Any], *, skip: tuple[str, ...] = ()) -> dict[str, Any]:
    """Normalise a feature dict into storable attributes keyed by safe names."""
    return {
        field_safe(key): encode_value(value) for key, value in features.items() if key not in skip
    }


def decode_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Undo :func:`encode_fields`, parsing JSON strings back into structures."""
    decoded: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str):
            try:
                decoded[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                decoded[key] = value
        else:
            decoded[key] = value
    return decoded


def save_circuit_metadata(store: MetadataStore, features: dict[str, Any]) -> bool:
    """Write a circuit's full metadata record, replacing any earlier one.

    Args:
        store: Metadata store to write into.
        features: Circuit metadata; must contain ``qpy_sha256``, which becomes
            the record key rather than an attribute.

    Returns:
        Whether the write succeeded.
    """
    if "qpy_sha256" not in features:
        logger.error("Missing required 'qpy_sha256' in features dictionary")
        raise ValueError("'features' dict must contain 'qpy_sha256'")

    circuit_hash = features["qpy_sha256"]
    logger.info(f"Saving circuit metadata: {circuit_hash}")

    try:
        fields = encode_fields(features, skip=("qpy_sha256",))
        store.put_record(CIRCUITS_PARTITION, circuit_hash, fields)
        logger.info(f"✓ Circuit metadata saved ({len(fields)} fields): {circuit_hash}")
        return True
    except Exception as e:
        logger.error(f"Failed to save metadata for {circuit_hash}: {e}")
        return False


def update_circuit_metadata(store: MetadataStore, qpy_sha256: str, updates: dict[str, Any]) -> bool:
    """Set some attributes of a circuit record, leaving the rest untouched."""
    logger.info(f"Updating circuit metadata: {qpy_sha256}")
    try:
        store.merge_record(CIRCUITS_PARTITION, qpy_sha256, encode_fields(updates))
        logger.info(f"✓ Circuit metadata updated (merge): {qpy_sha256}")
        return True
    except Exception as e:
        logger.error(f"Failed to update metadata for {qpy_sha256}: {e}")
        return False


def get_circuit_metadata(store: MetadataStore, qpy_sha256: str) -> dict[str, Any] | None:
    """Read a circuit's metadata, or ``None`` when it is not recorded."""
    logger.info(f"Retrieving circuit metadata: {qpy_sha256}")
    try:
        record = store.get_record(CIRCUITS_PARTITION, qpy_sha256)
    except Exception as e:
        logger.error(f"Failed to retrieve metadata for {qpy_sha256}: {e}")
        return None

    if record is None:
        logger.warning(f"Circuit metadata not found: {qpy_sha256}")
        return None

    metadata = decode_fields(record.fields)
    metadata["qpy_sha256"] = record.key
    logger.info(f"✓ Circuit metadata retrieved: {len(record.fields)} fields")
    return metadata


def list_circuits(store: MetadataStore, limit: int = 100) -> list[dict[str, Any]]:
    """Return a catalogue listing: one summary row per recorded circuit."""
    try:
        return [
            {
                "qpy_sha256": record.key,
                "num_qubits": record.fields.get("num_qubits"),
                "circuit_depth": record.fields.get("circuit_depth"),
                "circuit_size": record.fields.get("circuit_size"),
                "serialization_method": record.fields.get("serialization_method"),
                "timestamp": record.timestamp,
            }
            for record in store.list_records(CIRCUITS_PARTITION, select=CATALOG_FIELDS, limit=limit)
        ]
    except Exception as e:
        logger.error(f"Failed to list circuits: {e}")
        return []


def delete_circuit_metadata(store: MetadataStore, qpy_sha256: str) -> bool:
    """Delete a circuit's metadata record."""
    try:
        store.delete_record(CIRCUITS_PARTITION, qpy_sha256)
        logger.info(f"✓ Circuit metadata deleted: {qpy_sha256}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete metadata for {qpy_sha256}: {e}")
        return False


__all__ = [
    "CATALOG_FIELDS",
    "coerce_native",
    "decode_fields",
    "delete_circuit_metadata",
    "encode_fields",
    "encode_value",
    "get_circuit_metadata",
    "json_default",
    "list_circuits",
    "save_circuit_metadata",
    "update_circuit_metadata",
]
