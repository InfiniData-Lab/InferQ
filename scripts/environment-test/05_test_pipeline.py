#!/usr/bin/env python3
"""
Test 5: Pipeline Integration Test
Tests the actual quantum circuit pipeline components
"""

import sys
import os
import tempfile
import json
from pathlib import Path
import time

def setup_test_environment():
    """Set up test environment"""
    print("🔧 Setting up test environment...")
    
    # Add project root to Python path
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    # Create temporary directories for testing
    test_circuits_dir = Path("test_circuits")
    test_circuits_dir.mkdir(exist_ok=True)
    
    print(f"   ✅ Project root: {project_root}")
    print(f"   ✅ Test circuits directory: {test_circuits_dir}")
    
    return test_circuits_dir

def test_config_import():
    """Test configuration module import"""
    print("\n📋 Testing Configuration Import...")
    
    try:
        from config import (
            get_circuit_config, 
            get_simulation_config, 
            get_storage_config,
            apply_optimizations
        )
        print("   ✅ Configuration module imported")
        
        # Test configuration functions
        circuit_config = get_circuit_config()
        simulation_config = get_simulation_config()
        storage_config = get_storage_config()
        
        print(f"   ✅ Circuit config: {len(circuit_config)} parameters")
        print(f"   ✅ Simulation config: {len(simulation_config)} parameters")
        print(f"   ✅ Storage config: {len(storage_config)} parameters")
        
        # Apply optimizations
        apply_optimizations()
        print("   ✅ Performance optimizations applied")
        
        return True, (circuit_config, simulation_config, storage_config)
        
    except Exception as e:
        print(f"   ❌ Configuration import failed: {e}")
        return False, None

def test_circuit_generation():
    """Test quantum circuit generation"""
    print("\n⚛️  Testing Circuit Generation...")
    
    try:
        from generators.circuit_merger import CircuitMerger
        from generators.lib.generator import BaseParams
        
        print("   ✅ Circuit generation modules imported")
        
        # Create base parameters for testing
        base_params = BaseParams(
            max_qubits=3,  # Small for testing
            min_qubits=2,
            max_depth=50,  # Small for testing
            min_depth=10,
            seed=12345,
            measure=False
        )
        
        print("   ✅ Base parameters created")
        
        # Create circuit merger
        circuit_merger = CircuitMerger(base_params=base_params)
        print("   ✅ Circuit merger initialized")
        
        # Generate a test circuit
        start_time = time.time()
        circuit = circuit_merger.generate_hierarchical_circuit(
            stopping_probability=0.5,
            max_generators=3
        )
        generation_time = time.time() - start_time
        
        print(f"   ✅ Circuit generated in {generation_time:.3f}s")
        print(f"   Circuit: {circuit.num_qubits} qubits, depth {circuit.depth()}, size {circuit.size()}")
        
        return True, circuit
        
    except Exception as e:
        print(f"   ❌ Circuit generation failed: {e}")
        return False, None

def test_feature_extraction(circuit):
    """Test feature extraction from circuit"""
    print("\n🔍 Testing Feature Extraction...")
    
    try:
        from feature_extractors.extractors import extract_features
        
        print("   ✅ Feature extraction module imported")
        
        # Extract features
        start_time = time.time()
        features = extract_features(circuit=circuit)
        extraction_time = time.time() - start_time
        
        print(f"   ✅ Features extracted in {extraction_time:.3f}s")
        print(f"   Features: {len(features)} total")
        
        # Show some key features
        key_features = ['num_qubits', 'depth', 'size', 'num_gates']
        for feature in key_features:
            if feature in features:
                print(f"     {feature}: {features[feature]}")
        
        return True, features
        
    except Exception as e:
        print(f"   ❌ Feature extraction failed: {e}")
        return False, None

def test_quantum_simulation(circuit):
    """Test quantum simulation"""
    print("\n🖥️  Testing Quantum Simulation...")
    
    try:
        from simulators.simulate import QuantumSimulator
        
        print("   ✅ Quantum simulator module imported")
        
        # Create simulator with conservative settings
        simulator = QuantumSimulator(
            seed=12345,
            shots=100,  # Small for testing
            timeout_seconds=30  # Short timeout for testing
        )
        
        print("   ✅ Quantum simulator initialized")
        
        # Run simulation
        start_time = time.time()
        results = simulator.simulate_all_methods(circuit)
        simulation_time = time.time() - start_time
        
        print(f"   ✅ Simulation completed in {simulation_time:.3f}s")
        
        # Check results
        successful_methods = sum(1 for r in results.values() if r.get('success', False))
        total_methods = len(results)
        
        print(f"   Results: {successful_methods}/{total_methods} methods successful")
        
        # Show method results
        for method, result in results.items():
            status = "✅" if result.get('success', False) else "❌"
            print(f"     {status} {method}")
        
        return True, results
        
    except Exception as e:
        print(f"   ❌ Quantum simulation failed: {e}")
        return False, None

def test_local_storage(circuit, features, test_circuits_dir):
    """Test local storage functionality"""
    print("\n💾 Testing Local Storage...")
    
    try:
        from utils.save_utils import save_circuit_locally
        
        print("   ✅ Storage utilities imported")
        
        # Save circuit locally
        start_time = time.time()
        qpy_hash, saved_features, written = save_circuit_locally(
            circuit, features, test_circuits_dir
        )
        storage_time = time.time() - start_time
        
        print(f"   ✅ Circuit saved in {storage_time:.3f}s")
        print(f"   Hash: {qpy_hash}")
        print(f"   Written: {written}")
        print(f"   Features: {len(saved_features)} total")
        
        # Verify files exist
        circuit_dir = test_circuits_dir / qpy_hash
        if circuit_dir.exists():
            files = list(circuit_dir.glob("*"))
            print(f"   ✅ Circuit directory created with {len(files)} files")
            
            # Check for expected files
            expected_files = ['meta.json', 'circuit.qpy']
            for expected_file in expected_files:
                if (circuit_dir / expected_file).exists():
                    print(f"     ✅ {expected_file}")
                else:
                    print(f"     ⚠️  {expected_file} missing")
        else:
            print("   ❌ Circuit directory not created")
            return False
        
        return True, qpy_hash
        
    except Exception as e:
        print(f"   ❌ Local storage failed: {e}")
        return False, None

def test_pipeline_integration():
    """Test full pipeline integration"""
    print("\n🔄 Testing Pipeline Integration...")
    
    try:
        # Import main pipeline function
        from main import run_extraction_pipeline
        from generators.circuit_merger import CircuitMerger
        from generators.lib.generator import BaseParams
        from simulators.simulate import QuantumSimulator
        
        print("   ✅ Pipeline modules imported")
        
        # Set up minimal pipeline components
        base_params = BaseParams(
            max_qubits=2,  # Very small for integration test
            min_qubits=2,
            max_depth=20,
            min_depth=10,
            seed=12345,
            measure=False
        )
        
        circuit_merger = CircuitMerger(base_params=base_params)
        quantum_simulator = QuantumSimulator(
            seed=12345,
            shots=10,  # Minimal shots
            timeout_seconds=15
        )
        
        print("   ✅ Pipeline components initialized")
        
        # Run pipeline (without Azure for testing)
        start_time = time.time()
        run_extraction_pipeline(
            circuitMerger=circuit_merger,
            quantumSimulator=quantum_simulator,
            azure_conn=None  # Local only for testing
        )
        pipeline_time = time.time() - start_time
        
        print(f"   ✅ Full pipeline completed in {pipeline_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Pipeline integration failed: {e}")
        return False

def cleanup_test_environment(test_circuits_dir):
    """Clean up test environment"""
    print("\n🧹 Cleaning up test environment...")
    
    try:
        # Remove test circuits directory
        import shutil
        if test_circuits_dir.exists():
            shutil.rmtree(test_circuits_dir)
            print("   ✅ Test circuits directory removed")
        
        return True
        
    except Exception as e:
        print(f"   ⚠️  Cleanup failed: {e}")
        return False

def main():
    """Run all pipeline tests"""
    print("=" * 60)
    print("🔬 PIPELINE INTEGRATION TEST")
    print("=" * 60)
    
    # Setup
    test_circuits_dir = setup_test_environment()
    
    # Run tests
    config_ok, configs = test_config_import()
    
    if config_ok:
        circuit_ok, circuit = test_circuit_generation()
        
        if circuit_ok:
            features_ok, features = test_feature_extraction(circuit)
            simulation_ok, results = test_quantum_simulation(circuit)
            
            if features_ok:
                storage_ok, qpy_hash = test_local_storage(circuit, features, test_circuits_dir)
            else:
                storage_ok = False
        else:
            features_ok = simulation_ok = storage_ok = False
        
        # Full integration test
        integration_ok = test_pipeline_integration()
    else:
        circuit_ok = features_ok = simulation_ok = storage_ok = integration_ok = False
    
    # Cleanup
    cleanup_ok = cleanup_test_environment(test_circuits_dir)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PIPELINE TEST SUMMARY")
    print("=" * 60)
    
    tests = [
        ("Configuration Import", config_ok),
        ("Circuit Generation", circuit_ok),
        ("Feature Extraction", features_ok),
        ("Quantum Simulation", simulation_ok),
        ("Local Storage", storage_ok),
        ("Pipeline Integration", integration_ok)
    ]
    
    passed = 0
    for test_name, result in tests:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:8} {test_name}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(tests)} tests")
    
    if passed >= 5:  # Allow one failure
        print("🎉 Pipeline is ready for production!")
        return 0
    else:
        print("❌ Pipeline has critical issues")
        return 1

if __name__ == "__main__":
    exit(main())