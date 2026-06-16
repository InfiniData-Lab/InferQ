#!/usr/bin/env python3
"""
Test script for the quantum simulation module.

This script performs basic tests to ensure all simulation methods
are working correctly.
"""

import sys
from pathlib import Path

# Add the parent directory to the path so we can import the simulators module
sys.path.append(str(Path(__file__).parent.parent))

from qiskit import QuantumCircuit
from simulators import QuantumSimulator, SimulationMethod, benchmark_simulation_methods

def test_basic_functionality():
    """Test basic functionality of the QuantumSimulator."""
    print("Testing basic QuantumSimulator functionality...")
    
    # Create a simple Bell state circuit
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    
    # Initialize simulator
    simulator = QuantumSimulator(shots=1024, seed=42)
    
    # Test individual methods
    methods_to_test = [
        ('statevector', simulator.simulate_statevector),
        ('mps', simulator.simulate_mps),
        ('unitary', simulator.simulate_unitary),
        ('density_matrix', simulator.simulate_density_matrix),
        ('stabilizer', simulator.simulate_stabilizer),
        ('extended_stabilizer', simulator.simulate_extended_stabilizer),
    ]
    
    results = {}
    for method_name, method_func in methods_to_test:
        try:
            result = method_func(qc)
            results[method_name] = result
            status = "✓" if result['success'] else "✗"
            print(f"  {method_name:<20} {status}")
        except Exception as e:
            print(f"  {method_name:<20} ✗ (Exception: {e})")
            results[method_name] = {'success': False, 'error': str(e)}
    
    return results

def test_all_methods():
    """Test the simulate_all_methods function."""
    print("\nTesting simulate_all_methods...")
    
    # Create a simple circuit
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    
    simulator = QuantumSimulator(shots=1024, seed=42)
    results = simulator.simulate_all_methods(qc)
    
    successful = sum(1 for r in results.values() if r['success'])
    total = len(results)
    
    print(f"  Results: {successful}/{total} methods successful")
    
    for method, result in results.items():
        status = "✓" if result['success'] else "✗"
        print(f"    {method:<20} {status}")
    
    return results

def test_benchmark_function():
    """Test the benchmark function."""
    print("\nTesting benchmark_simulation_methods...")
    
    # Create a simple circuit
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    
    try:
        benchmark_results = benchmark_simulation_methods(qc, shots=1024, seed=42)
        
        print("  ✓ Benchmark completed successfully")
        print(f"  Generated report with {len(benchmark_results['metrics'])} metrics")
        
        # Print a summary of the report
        report_lines = benchmark_results['report'].split('\n')
        for line in report_lines[:10]:  # Print first 10 lines
            print(f"    {line}")
        
        if len(report_lines) > 10:
            print("    ...")
        
        return benchmark_results
        
    except Exception as e:
        print(f"  ✗ Benchmark failed: {e}")
        return None

def test_simulator_info():
    """Test getting simulator information."""
    print("\nTesting simulator information...")
    
    simulator = QuantumSimulator()
    
    print(f"  Available methods: {simulator.get_available_methods()}")
    
    # Test getting info for a specific method
    try:
        info = simulator.get_simulator_info(SimulationMethod.STATEVECTOR)
        print(f"  Statevector simulator info: {info['name']}")
        print("  ✓ Simulator info retrieval successful")
    except Exception as e:
        print(f"  ✗ Simulator info retrieval failed: {e}")

def main():
    """Run all tests."""
    print("Quantum Simulator Test Suite")
    print("=" * 50)
    
    try:
        # Test basic functionality
        basic_results = test_basic_functionality()
        
        # Test all methods function
        all_methods_results = test_all_methods()
        
        # Test benchmark function
        benchmark_results = test_benchmark_function()
        
        # Test simulator info
        test_simulator_info()
        
        print("\n" + "=" * 50)
        print("Test Summary:")
        
        # Count successful tests
        if basic_results:
            basic_success = sum(1 for r in basic_results.values() if r.get('success', False))
            print(f"  Basic functionality: {basic_success}/{len(basic_results)} methods")
        
        if all_methods_results:
            all_success = sum(1 for r in all_methods_results.values() if r.get('success', False))
            print(f"  All methods test: {all_success}/{len(all_methods_results)} methods")
        
        benchmark_status = "✓" if benchmark_results else "✗"
        print(f"  Benchmark test: {benchmark_status}")
        
        print("\nAll tests completed!")
        
    except Exception as e:
        print(f"Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()