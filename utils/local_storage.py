"""
Local storage utilities for quantum circuits.

This module handles saving and loading quantum circuits to/from local filesystem
with multiple serialization formats (QPY, pickle, QASM).
"""

from pathlib import Path
import json
import logging
import qiskit.qpy
from io import BytesIO
import pickle

from utils.circuit_hash import compute_circuit_hash
from typing import Dict, Any

# Configure logging
logger = logging.getLogger(__name__)

def save_circuit_locally(circuit, features: dict, out_root: Path, expected_hash: str = None):
    """
    Save a quantum circuit locally with multiple serialization fallbacks.
    
    This function attempts to save circuits using QPY format first, but falls back
    to pickle serialization for very large circuits that exceed QPY limitations.
    """
    logger.info(f"Starting local save for circuit: {circuit.num_qubits} qubits, depth {circuit.depth()}")
    
    # Try QPY serialization first
    qpy_success = False
    raw_bytes = None
    serialization_method = "qpy"
    
    # Use expected hash if provided, otherwise compute it
    if expected_hash:
        qpy_hash = expected_hash
        cid = qpy_hash
        # Still need to compute for file saving, but use expected hash as ID
        _, raw_bytes, serialization_method = compute_circuit_hash(circuit)
        qpy_success = (serialization_method == "qpy")
        
        # Log if there's a mismatch
        computed_hash, _, _ = compute_circuit_hash(circuit)
        if computed_hash != expected_hash:
            logger.warning(f"⚠️  Circuit modified during processing: expected {expected_hash[:8]}..., computed {computed_hash[:8]}...")
    else:
        # Use centralized circuit hashing
        qpy_hash, raw_bytes, serialization_method = compute_circuit_hash(circuit)
        cid = qpy_hash
        qpy_success = (serialization_method == "qpy")
    dir_ = out_root / cid
    logger.debug(f"Circuit hash: {cid}")

    # Create directory if it doesn't exist, or skip if it does (same circuit)
    try:
        dir_.mkdir(parents=True, exist_ok=False)
        logger.debug(f"✓ Created directory: {dir_}")
    except FileExistsError:
        logger.info(f"Circuit {cid} already exists, skipping save")
        return cid, {}, False

    # Save the circuit using the successful method
    logger.debug(f"Saving circuit files using {serialization_method} method...")
    if qpy_success:
        # Save as QPY
        qpy_path = dir_ / "circuit.qpy"
        try:
            with open(qpy_path, "wb") as f:
                qiskit.qpy.dump(circuit, f)
            logger.debug("✓ Circuit saved in QPY format")
        except Exception as e:
            logger.warning(f"Failed to save QPY file: {e}")
            # Save raw bytes instead
            with open(qpy_path, "wb") as f:
                f.write(raw_bytes)
            logger.debug("✓ Circuit saved as raw QPY bytes")
    elif serialization_method == "pickle":
        # Save as pickle
        pickle_path = dir_ / "circuit.pkl"
        with open(pickle_path, "wb") as f:
            pickle.dump(circuit, f)
        logger.debug("✓ Circuit saved in pickle format")
    else:
        # Save circuit as QASM string for metadata method
        qasm_path = dir_ / "circuit.qasm"
        try:
            with open(qasm_path, "w") as f:
                f.write(circuit.qasm())
            logger.debug("✓ Circuit saved as QASM")
        except Exception as e:
            logger.warning(f"Failed to save QASM: {e}")
            # Save basic circuit info
            info_path = dir_ / "circuit_info.txt"
            with open(info_path, "w") as f:
                f.write(f"Qubits: {circuit.num_qubits}\n")
                f.write(f"Depth: {circuit.depth()}\n")
                f.write(f"Size: {circuit.size()}\n")
                f.write(f"Serialization failed - only metadata available\n")
            logger.debug("✓ Circuit info saved as fallback")

    # Create comprehensive metadata
    logger.debug("Creating metadata file...")
    meta = {
        "qpy_sha256": qpy_hash,
        "serialization_method": serialization_method,
        "circuit_qubits": circuit.num_qubits,
        "circuit_depth": circuit.depth(),
        "circuit_size": circuit.size(),
        "qpy_serialization_success": qpy_success,
        **features,
    }
    
    with open(dir_ / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    logger.debug("✓ Metadata file created")

    logger.info(f"✓ Circuit saved locally: {cid} (method: {serialization_method})")
    return cid, meta, True

def load_circuit_locally(circuit_dir: Path):
    """
    Load a quantum circuit from local storage, handling different serialization formats.
    """
    logger.info(f"Loading circuit from: {circuit_dir}")
    
    if not circuit_dir.exists():
        logger.error(f"Circuit directory not found: {circuit_dir}")
        raise FileNotFoundError(f"Circuit directory {circuit_dir} not found")
    
    # Read metadata to determine serialization method
    meta_path = circuit_dir / "meta.json"
    if meta_path.exists():
        logger.debug("Reading metadata file...")
        with open(meta_path, "r") as f:
            meta = json.load(f)
        serialization_method = meta.get("serialization_method", "qpy")
        logger.debug(f"Detected serialization method: {serialization_method}")
    else:
        serialization_method = "qpy"  # Default assumption
        logger.warning("No metadata file found, assuming QPY format")
    
    # Load circuit based on serialization method
    logger.debug(f"Attempting to load circuit using {serialization_method} method...")
    
    if serialization_method == "qpy":
        qpy_path = circuit_dir / "circuit.qpy"
        if qpy_path.exists():
            try:
                with open(qpy_path, "rb") as f:
                    circuits = qiskit.qpy.load(f)
                circuit = circuits[0] if isinstance(circuits, list) else circuits
                logger.info(f"✓ Circuit loaded from QPY: {circuit.num_qubits} qubits, depth {circuit.depth()}")
                return circuit
            except Exception as e:
                logger.warning(f"Failed to load QPY file: {e}")
    
    elif serialization_method == "pickle":
        pickle_path = circuit_dir / "circuit.pkl"
        if pickle_path.exists():
            try:
                with open(pickle_path, "rb") as f:
                    circuit = pickle.load(f)
                logger.info(f"✓ Circuit loaded from pickle: {circuit.num_qubits} qubits, depth {circuit.depth()}")
                return circuit
            except Exception as e:
                logger.warning(f"Failed to load pickle file: {e}")
    
    elif serialization_method == "metadata":
        qasm_path = circuit_dir / "circuit.qasm"
        if qasm_path.exists():
            try:
                from qiskit import QuantumCircuit
                with open(qasm_path, "r") as f:
                    qasm_str = f.read()
                circuit = QuantumCircuit.from_qasm_str(qasm_str)
                logger.info(f"✓ Circuit loaded from QASM: {circuit.num_qubits} qubits, depth {circuit.depth()}")
                return circuit
            except Exception as e:
                logger.warning(f"Failed to load from QASM: {e}")
    
    logger.error(f"Could not load circuit from {circuit_dir}")
    raise ValueError(f"Could not load circuit from {circuit_dir}")

def get_circuit_info(circuit_dir: Path):
    """
    Get circuit information without loading the full circuit.
    """
    logger.debug(f"Getting circuit info from: {circuit_dir}")
    
    meta_path = circuit_dir / "meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                info = json.load(f)
            logger.debug(f"✓ Circuit info loaded: {info.get('circuit_qubits', 'unknown')} qubits")
            return info
        except Exception as e:
            logger.warning(f"Failed to read circuit info: {e}")
            return None
    else:
        logger.warning(f"No metadata file found in {circuit_dir}")
        return None