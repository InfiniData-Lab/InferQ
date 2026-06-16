"""
Azure Blob Storage utilities for quantum circuits.

This module handles uploading and downloading quantum circuits to/from
Azure Blob Storage with multiple serialization formats.
"""

import pickle
import logging
from pathlib import PurePosixPath
from azure.storage.blob import ContentSettings
from io import BytesIO
import qiskit.qpy

# Configure logging
logger = logging.getLogger(__name__)

def upload_circuit_blob(container_client, qc, qpy_sha256: str, serialization_method: str = "qpy") -> str:
    """
    Serialize QuantumCircuit qc, upload it to Azure Blob Storage,
    and return the HTTPS URL (suitable for storing in SQL).
    
    Supports multiple serialization methods with fallbacks for large circuits.
    """
    logger.info(f"Uploading circuit to blob storage: {qc.num_qubits} qubits, depth {qc.depth()}, hash {qpy_sha256}")
    logger.debug(f"Requested serialization method: {serialization_method}")
    
    raw_bytes = None
    file_extension = "qpy"
    content_type = "application/octet-stream"
    
    # Try different serialization methods
    if serialization_method == "qpy":
        try:
            logger.debug("Attempting QPY serialization for blob upload...")
            buf = BytesIO()
            qiskit.qpy.dump(qc, buf)
            raw_bytes = buf.getvalue()
            file_extension = "qpy"
            logger.debug(f"✓ QPY serialization for upload successful ({len(raw_bytes)} bytes)")
        except Exception as e:
            logger.warning(f"QPY serialization for upload failed: {e}")
            logger.info("Falling back to pickle serialization for blob...")
            serialization_method = "pickle"  # Fallback
    
    if serialization_method == "pickle":
        try:
            logger.debug("Attempting pickle serialization for blob upload...")
            buf = BytesIO()
            pickle.dump(qc, buf)
            raw_bytes = buf.getvalue()
            file_extension = "pkl"
            logger.debug(f"✓ Pickle serialization for upload successful ({len(raw_bytes)} bytes)")
        except Exception as e:
            logger.warning(f"Pickle serialization for upload failed: {e}")
            logger.info("Falling back to QASM serialization for blob...")
            serialization_method = "qasm"  # Fallback
    
    if serialization_method == "qasm":
        try:
            logger.debug("Attempting QASM serialization for blob upload...")
            qasm_str = qc.qasm()
            raw_bytes = qasm_str.encode('utf-8')
            file_extension = "qasm"
            content_type = "text/plain"
            logger.debug(f"✓ QASM serialization for upload successful ({len(raw_bytes)} bytes)")
        except Exception as e:
            logger.error(f"All serialization methods failed for blob upload: {e}")
            raise ValueError("Unable to serialize circuit for upload")
    
    # Create blob path
    rel_path = PurePosixPath(qpy_sha256[:2]) / f"{qpy_sha256}.{file_extension}"
    logger.debug(f"Blob path: {rel_path}")
    
    # Upload to blob storage
    logger.debug("Uploading to Azure Blob Storage...")
    blob_client = container_client.get_blob_client(str(rel_path))
    
    metadata = {
        "sha256": qpy_sha256,
        "format": serialization_method,
        "nqubits": str(qc.num_qubits),
        "depth": str(qc.depth()),
        "size": str(qc.size()),
    }
    logger.debug(f"Blob metadata: {metadata}")
    
    blob_client.upload_blob(
        raw_bytes,
        overwrite=True,
        max_concurrency=4,  # parallel blocks (>4 MiB auto-split)
        content_settings=ContentSettings(
            content_type=content_type
        ),
        metadata=metadata
    )
    
    blob_url = blob_client.url
    logger.info(f"✓ Circuit uploaded to blob storage (format: {serialization_method}, size: {len(raw_bytes)} bytes)")
    logger.debug(f"Blob URL: {blob_url}")
    return blob_url

def download_circuit_blob(container_client, blob_path: str, serialization_method: str = "qpy"):
    """
    Download and deserialize a quantum circuit from Azure Blob Storage.
    
    Args:
        container_client: Azure container client
        blob_path: Path to the blob in storage
        serialization_method: Method used to serialize the circuit
        
    Returns:
        QuantumCircuit object
    """
    logger.info(f"Downloading circuit from blob storage: {blob_path}")
    logger.debug(f"Expected serialization method: {serialization_method}")
    
    try:
        logger.debug("Getting blob client and downloading data...")
        blob_client = container_client.get_blob_client(blob_path)
        blob_data = blob_client.download_blob().readall()
        logger.debug(f"✓ Downloaded {len(blob_data)} bytes from blob")
        
        logger.debug(f"Deserializing circuit using {serialization_method} method...")
        
        if serialization_method == "qpy":
            buf = BytesIO(blob_data)
            circuits = qiskit.qpy.load(buf)
            circuit = circuits[0] if isinstance(circuits, list) else circuits
            logger.info(f"✓ Circuit loaded from QPY blob: {circuit.num_qubits} qubits, depth {circuit.depth()}")
            return circuit
        
        elif serialization_method == "pickle":
            buf = BytesIO(blob_data)
            circuit = pickle.load(buf)
            logger.info(f"✓ Circuit loaded from pickle blob: {circuit.num_qubits} qubits, depth {circuit.depth()}")
            return circuit
        
        elif serialization_method == "qasm":
            qasm_str = blob_data.decode('utf-8')
            from qiskit import QuantumCircuit
            circuit = QuantumCircuit.from_qasm_str(qasm_str)
            logger.info(f"✓ Circuit loaded from QASM blob: {circuit.num_qubits} qubits, depth {circuit.depth()}")
            return circuit
        
        else:
            logger.error(f"Unsupported serialization method: {serialization_method}")
            raise ValueError(f"Unsupported serialization method: {serialization_method}")
            
    except Exception as e:
        logger.error(f"Failed to download circuit from blob {blob_path}: {e}")
        raise