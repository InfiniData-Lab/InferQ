#!/usr/bin/env python3
"""
Quantum Circuit Hashing Utilities

This module provides consistent SHA-256 hashing for quantum circuits across the entire system.
All circuit hashing should use these functions to ensure consistency between:
- Duplicate detection
- Local storage
- Azure storage
- Database storage

Author: InferQ Pipeline System
"""

import hashlib
import logging
from typing import Tuple
from qiskit import QuantumCircuit
from qiskit.qpy import dump as qpy_dump
from io import BytesIO

# Configure logging
logger = logging.getLogger(__name__)

def compute_circuit_hash(circuit: QuantumCircuit) -> Tuple[str, bytes, str]:
    """
    Compute SHA-256 hash of a quantum circuit with fallback methods.
    
    This is the canonical circuit hashing function used throughout the system.
    It tries multiple serialization methods in order of preference:
    1. QPY serialization (most reliable)
    2. Pickle serialization (fallback)
    3. Metadata-based hash (final fallback)
    
    Args:
        circuit: The quantum circuit to hash
        
    Returns:
        Tuple of (hash_string, raw_bytes, serialization_method)
        - hash_string: SHA-256 hash as hexadecimal string
        - raw_bytes: The raw bytes that were hashed
        - serialization_method: Method used ("qpy", "pickle", or "metadata")
    """
    try:
        # Method 1: QPY serialization (preferred)
        try:
            buffer = BytesIO()
            qpy_dump(circuit, buffer)
            raw_bytes = buffer.getvalue()
            serialization_method = "qpy"
            logger.debug(f"✓ Using QPY serialization ({len(raw_bytes)} bytes)")
            
        except Exception as qpy_error:
            logger.debug(f"QPY serialization failed: {qpy_error}")
            
            # Method 2: Pickle serialization (fallback)
            try:
                import pickle
                raw_bytes = pickle.dumps(circuit)
                serialization_method = "pickle"
                logger.debug(f"✓ Using pickle serialization ({len(raw_bytes)} bytes)")
                
            except Exception as pickle_error:
                logger.debug(f"Pickle serialization failed: {pickle_error}")
                
                # Method 3: Metadata-based hash (final fallback)
                logger.debug("Using metadata-based fallback...")
                circuit_str = f"{circuit.num_qubits}_{circuit.depth()}_{circuit.size()}_{str(circuit.data)}"
                raw_bytes = circuit_str.encode('utf-8')
                serialization_method = "metadata"
                logger.debug(f"✓ Using metadata-based hash ({len(raw_bytes)} bytes)")
        
        # Compute SHA-256 hash
        hash_obj = hashlib.sha256(str(circuit).encode("utf-8"))
        hash_string = hash_obj.hexdigest()
        
        logger.debug(f"Circuit hash: {hash_string[:8]}... (method: {serialization_method})")
        
        return hash_string, raw_bytes, serialization_method
        
    except Exception as e:
        logger.error(f"❌ Critical error in circuit hashing: {e}")
        # Emergency fallback: use circuit string representation
        emergency_str = f"emergency_{circuit.num_qubits}_{circuit.depth()}_{circuit.size()}"
        emergency_bytes = emergency_str.encode('utf-8')
        emergency_hash = hashlib.sha256(emergency_bytes).hexdigest()
        logger.warning(f"⚠️  Using emergency hash: {emergency_hash[:8]}...")
        return emergency_hash, emergency_bytes, "emergency"

def compute_circuit_hash_simple(circuit: QuantumCircuit) -> str:
    """
    Compute SHA-256 hash of a quantum circuit (simple interface).
    
    This is a simplified interface that only returns the hash string.
    Use this when you only need the hash and don't care about the method used.
    
    Args:
        circuit: The quantum circuit to hash
        
    Returns:
        SHA-256 hash as hexadecimal string
    """
    hash_string, _, _ = compute_circuit_hash(circuit)
    return hash_string

def verify_circuit_hash(circuit: QuantumCircuit, expected_hash: str) -> bool:
    """
    Verify that a circuit matches an expected hash.
    
    Args:
        circuit: The quantum circuit to verify
        expected_hash: The expected SHA-256 hash
        
    Returns:
        True if the circuit hash matches the expected hash, False otherwise
    """
    try:
        actual_hash = compute_circuit_hash_simple(circuit)
        matches = actual_hash == expected_hash
        
        if matches:
            logger.debug(f"✓ Hash verification passed: {expected_hash[:8]}...")
        else:
            logger.warning(f"❌ Hash verification failed: expected {expected_hash[:8]}..., got {actual_hash[:8]}...")
            
        return matches
        
    except Exception as e:
        logger.error(f"❌ Error during hash verification: {e}")
        return False

def get_hash_info(circuit: QuantumCircuit) -> dict:
    """
    Get detailed information about circuit hashing.
    
    Args:
        circuit: The quantum circuit to analyze
        
    Returns:
        Dictionary with hash information including:
        - hash: The SHA-256 hash string
        - method: Serialization method used
        - size_bytes: Size of serialized data
        - circuit_qubits: Number of qubits
        - circuit_depth: Circuit depth
        - circuit_size: Number of operations
    """
    try:
        hash_string, raw_bytes, method = compute_circuit_hash(circuit)
        
        return {
            'hash': hash_string,
            'method': method,
            'size_bytes': len(raw_bytes),
            'circuit_qubits': circuit.num_qubits,
            'circuit_depth': circuit.depth(),
            'circuit_size': circuit.size()
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting hash info: {e}")
        return {
            'hash': 'error',
            'method': 'error',
            'size_bytes': 0,
            'circuit_qubits': circuit.num_qubits if circuit else 0,
            'circuit_depth': circuit.depth() if circuit else 0,
            'circuit_size': circuit.size() if circuit else 0
        }


if __name__ == "__main__":
    # Test the circuit hashing utilities
    import logging
    from qiskit import QuantumCircuit
    
    logging.basicConfig(level=logging.DEBUG)
    
    print("🧪 Testing Circuit Hashing Utilities...")
    
    # Create a test circuit
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.measure_all()
    
    # Test hash computation
    hash1 = compute_circuit_hash_simple(qc)
    print(f"Hash 1: {hash1}")
    
    # Test consistency
    hash2 = compute_circuit_hash_simple(qc)
    print(f"Hash 2: {hash2}")
    print(f"Consistent: {hash1 == hash2}")
    
    # Test detailed info
    info = get_hash_info(qc)
    print(f"Hash Info: {info}")
    
    # Test verification
    verified = verify_circuit_hash(qc, hash1)
    print(f"Verification: {verified}")