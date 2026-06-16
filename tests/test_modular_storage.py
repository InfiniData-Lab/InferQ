#!/usr/bin/env python3
"""
Test script for the modular storage system.
"""

from utils.local_storage import save_circuit_locally, get_circuit_info
from utils.table_storage import save_circuit_metadata_to_table, list_circuits_from_table
from utils.azure_connection import AzureConnection
from qiskit import QuantumCircuit
from pathlib import Path

def test_modular_storage():
    """Test the modular storage system."""
    
    print("Testing Modular Storage System")
    print("=" * 40)
    
    # Create a simple test circuit
    qc = QuantumCircuit(3, 3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.measure_all()
    
    print(f"Test circuit: {qc.num_qubits} qubits, depth {qc.depth()}")
    
    # Test local storage
    print("\n1. Testing local storage...")
    features = {
        "test_feature": "modular_test",
        "num_qubits": qc.num_qubits,
        "circuit_depth": qc.depth()
    }
    
    try:
        qpy_hash, saved_features, written = save_circuit_locally(qc, features, Path("./test_circuits/"))
        if written:
            print(f"✓ Local storage successful: {qpy_hash}")
            
            # Test reading info
            circuit_info = get_circuit_info(Path("./test_circuits/") / qpy_hash)
            print(f"✓ Circuit info retrieved: {circuit_info.get('serialization_method', 'unknown')}")
        else:
            print("⚠️  Circuit already exists locally")
    except Exception as e:
        print(f"✗ Local storage failed: {e}")
        return
    
    # Test Azure Table Storage
    print("\n2. Testing Azure Table Storage...")
    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.get_circuits_table_client()
        
        # Save to table
        table_success = save_circuit_metadata_to_table(table_client, saved_features)
        if table_success:
            print("✓ Table storage successful")
            
            # List circuits
            circuits = list_circuits_from_table(table_client, limit=5)
            print(f"✓ Found {len(circuits)} circuits in table")
        else:
            print("✗ Table storage failed")
            
    except Exception as e:
        print(f"✗ Azure Table Storage test failed: {e}")
    
    print("\n✅ Modular storage test completed!")

if __name__ == "__main__":
    test_modular_storage()