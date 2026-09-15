"""Circuit (de)serialization against a provider-neutral object store.

Circuits are addressed by the SHA-256 of their QPY encoding, sharded one level
deep on the first two hex characters so that no single prefix accumulates the
whole catalogue. That layout is the storage contract: it is derived in exactly
one place, :func:`blob_path_for`, and every reader and writer goes through it.

Serialization degrades rather than fails: QPY first, pickle when QPY chokes on
a circuit, OpenQASM last. The format that actually won is recorded in the
object's metadata and in the extension, so a download knows how to read it
back.
"""

from __future__ import annotations

import logging
import pickle
from io import BytesIO
from pathlib import PurePosixPath

import qiskit.qpy

from inferq.remote.base import ObjectStore
from inferq.storage.qpy import load_circuit

logger = logging.getLogger(__name__)

#: Serialization methods in the order they are attempted, with the file
#: extension and content type each produces.
_FORMATS = {
    "qpy": ("qpy", "application/octet-stream"),
    "pickle": ("pkl", "application/octet-stream"),
    "qasm": ("qasm", "text/plain"),
}


def blob_path_for(circuit_hash: str, extension: str = "qpy") -> str:
    """Return the storage key for a circuit, given its hash and extension.

    The single source of truth for the ``<hash[:2]>/<hash>.<ext>`` layout.
    """
    return str(PurePosixPath(circuit_hash[:2]) / f"{circuit_hash}.{extension}")


def _dump_qasm(qc) -> bytes:
    """Serialize a circuit to OpenQASM, preferring QASM 2 and falling back to 3.

    ``QuantumCircuit.qasm()`` was removed in Qiskit 2.x; the exporters live in
    ``qiskit.qasm2`` and ``qiskit.qasm3``. QASM 2 cannot express every circuit
    Qiskit can build, so a circuit it rejects is retried as QASM 3.
    """
    import qiskit.qasm2

    try:
        return qiskit.qasm2.dumps(qc).encode("utf-8")
    except Exception as exc:  # noqa: BLE001 - any QASM 2 limitation means try QASM 3
        logger.debug("QASM 2 export failed (%s); trying QASM 3", exc)
        import qiskit.qasm3

        return qiskit.qasm3.dumps(qc).encode("utf-8")


def serialize_circuit(qc, serialization_method: str = "qpy") -> tuple[bytes, str]:
    """Serialize ``qc``, falling back through the format chain.

    Returns:
        The encoded bytes and the method that produced them, which may differ
        from the method requested.

    Raises:
        ValueError: when no format in the chain could encode the circuit.
    """
    if serialization_method == "qpy":
        try:
            buf = BytesIO()
            qiskit.qpy.dump(qc, buf)
            return buf.getvalue(), "qpy"
        except Exception as e:  # noqa: BLE001 - fall through to the next format
            logger.warning(f"QPY serialization failed: {e}; falling back to pickle")
            serialization_method = "pickle"

    if serialization_method == "pickle":
        try:
            buf = BytesIO()
            pickle.dump(qc, buf)
            return buf.getvalue(), "pickle"
        except Exception as e:  # noqa: BLE001 - fall through to the next format
            logger.warning(f"Pickle serialization failed: {e}; falling back to QASM")
            serialization_method = "qasm"

    if serialization_method == "qasm":
        try:
            return _dump_qasm(qc), "qasm"
        except Exception as e:
            logger.error(f"All serialization methods failed: {e}")
            raise ValueError("Unable to serialize circuit for upload") from e

    raise ValueError(f"Unsupported serialization method: {serialization_method}")


def deserialize_circuit(data: bytes, serialization_method: str = "qpy"):
    """Rebuild a ``QuantumCircuit`` from bytes written by :func:`serialize_circuit`."""
    if serialization_method == "qpy":
        return load_circuit(data)
    if serialization_method == "pickle":
        return pickle.load(BytesIO(data))
    if serialization_method == "qasm":
        from qiskit import QuantumCircuit

        return QuantumCircuit.from_qasm_str(data.decode("utf-8"))
    raise ValueError(f"Unsupported serialization method: {serialization_method}")


def upload_circuit_blob(
    store: ObjectStore, qc, qpy_sha256: str, serialization_method: str = "qpy"
) -> str:
    """Serialize ``qc``, upload it, and return its storage key.

    The key, not the URL, is what gets recorded as a circuit's ``blob_path``:
    it is the same string on every provider, whereas a URL embeds the account,
    the region and the endpoint. Call ``store.object_url(key)`` when a URL is
    what you actually need.

    Args:
        store: The object store to write into.
        qc: The circuit to upload.
        qpy_sha256: The circuit's content hash; it names the object.
        serialization_method: Preferred format; the chain may fall back.
    """
    logger.info(
        f"Uploading circuit to object storage: {qc.num_qubits} qubits, "
        f"depth {qc.depth()}, hash {qpy_sha256}"
    )

    raw_bytes, method = serialize_circuit(qc, serialization_method)
    file_extension, content_type = _FORMATS[method]
    key = blob_path_for(qpy_sha256, file_extension)

    metadata = {
        "sha256": qpy_sha256,
        "format": method,
        "nqubits": str(qc.num_qubits),
        "depth": str(qc.depth()),
        "size": str(qc.size()),
    }

    url = store.put_object(key, raw_bytes, content_type=content_type, metadata=metadata)
    logger.info(f"✓ Circuit uploaded (format: {method}, size: {len(raw_bytes)} bytes)")
    logger.debug(f"Object URL: {url}")
    return key


def download_circuit_blob(store: ObjectStore, blob_path: str, serialization_method: str = "qpy"):
    """Download and deserialize a circuit.

    Args:
        store: The object store to read from.
        blob_path: The object key, as produced by :func:`blob_path_for`.
        serialization_method: Format the object was written in.

    Returns:
        The reconstructed ``QuantumCircuit``.
    """
    logger.info(f"Downloading circuit from object storage: {blob_path}")
    try:
        data = store.get_object(blob_path)
        circuit = deserialize_circuit(data, serialization_method)
        logger.info(
            f"✓ Circuit loaded from {serialization_method}: "
            f"{circuit.num_qubits} qubits, depth {circuit.depth()}"
        )
        return circuit
    except Exception as e:
        logger.error(f"Failed to download circuit from {blob_path}: {e}")
        raise


__all__ = [
    "blob_path_for",
    "deserialize_circuit",
    "download_circuit_blob",
    "serialize_circuit",
    "upload_circuit_blob",
]
