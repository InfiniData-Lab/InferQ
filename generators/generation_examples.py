#!/usr/bin/env python3
"""
Comprehensive example demonstrating the InferQ hierarchical circuit generation system.

This example shows:
1. Basic usage
2. Probability customization 
3. Synergy demonstration
4. Error handling
5. Circuit analysis
"""

import numpy as np
from generators.circuit_merger import CircuitMerger
from generators.lib.generator import BaseParams


def example_1_basic_usage():
    """
    Example 1: Basic hierarchical circuit generation
    """
    print("🔹 Example 1: Basic Usage")
    print("-" * 40)
    
    # Simple parameters
    base_params = BaseParams(
        max_qubits=4, min_qubits=4, 
        max_depth=10, min_depth=5, 
        seed=42
    )
    
    merger = CircuitMerger(base_params)
    
    # Generate with default equal probabilities
    circuit = merger.generate_hierarchical_circuit(
        stopping_probability=0.4,
        max_generators=2
    )
    
    if circuit and circuit.data:
        print(f"✅ Generated: {circuit.name}")
        print(f"   📏 Size: {circuit.num_qubits} qubits, depth {circuit.depth()}")
        print(f"   🔧 Operations: {len(circuit.data)}")
    else:
        print("❌ No circuit generated")
    
    return circuit


def example_2_custom_probabilities():
    """
    Example 2: Custom probability distributions
    """
    print("\n🔹 Example 2: Custom Probabilities")
    print("-" * 40)
    
    base_params = BaseParams(
        max_qubits=5, min_qubits=5,
        max_depth=12, min_depth=8,
        seed=123
    )
    
    merger = CircuitMerger(base_params)
    
    # Create custom probability distribution
    # Favor quantum algorithms over state preparation
    probabilities = np.ones(len(merger.generators))
    
    algorithm_names = {'QFTGenerator', 'QPE', 'GroverNoAncilla', 'QAOA', 'VQEGenerator'}
    state_prep_names = {'GHZ', 'WState', 'GraphState'}
    
    for i, gen in enumerate(merger.generators):
        name = gen.__class__.__name__
        if name in algorithm_names:
            probabilities[i] = 3.0  # High probability for algorithms
        elif name in state_prep_names:
            probabilities[i] = 2.0  # Medium probability for state prep
        else:
            probabilities[i] = 1.0  # Default probability
    
    print("Using custom probabilities favoring algorithms...")
    
    circuit = merger.generate_hierarchical_circuit(
        generators_probabilities=probabilities,
        stopping_probability=0.2,  # Lower stopping probability for more generators
        max_generators=4
    )
    
    if circuit and circuit.data:
        print(f"✅ Generated: {circuit.name}")
        return circuit
    return None


def example_3_synergy_demonstration():
    """
    Example 3: Demonstrate quantum algorithm synergies
    """
    print("\n🔹 Example 3: Synergy Demonstration")
    print("-" * 40)
    
    base_params = BaseParams(
        max_qubits=6, min_qubits=6,
        max_depth=15, min_depth=10,
        seed=456
    )
    
    merger = CircuitMerger(base_params)
    
    # Create probability distribution that starts with QFT
    # This should trigger the QFT→QPE synergy
    probabilities = np.ones(len(merger.generators)) * 0.1  # Low base probability
    
    for i, gen in enumerate(merger.generators):
        if gen.__class__.__name__ == 'QFTGenerator':
            probabilities[i] = 8.0  # Very high probability for QFT
        elif gen.__class__.__name__ == 'QPE':
            probabilities[i] = 1.0  # Normal probability for QPE (will be boosted by synergy)
    
    print("Starting with high QFT probability to demonstrate QFT→QPE synergy...")
    
    circuit = merger.generate_hierarchical_circuit(
        generators_probabilities=probabilities,
        stopping_probability=0.1,  # Very low to encourage multiple generations
        max_generators=3
    )
    
    return circuit


def analyze_circuit(circuit, title="Circuit Analysis"):
    """
    Analyze and display circuit properties
    """
    if not circuit or not circuit.data:
        print(f"❌ {title}: No circuit to analyze")
        return
    
    print(f"\n📊 {title}")
    print("-" * len(title))
    
    # Basic stats
    print(f"Name: {circuit.name}")
    print(f"Qubits: {circuit.num_qubits}")
    print(f"Classical bits: {circuit.num_clbits}")
    print(f"Depth: {circuit.depth()}")
    print(f"Total operations: {len(circuit.data)}")
    
    # Gate analysis
    gate_counts = {}
    for instruction in circuit.data:
        gate_name = instruction.operation.name
        gate_counts[gate_name] = gate_counts.get(gate_name, 0) + 1
    
    print(f"Gate types ({len(gate_counts)}): {list(gate_counts.keys())}")
    
    # Show top gates
    if gate_counts:
        sorted_gates = sorted(gate_counts.items(), key=lambda x: x[1], reverse=True)
        print("Most common gates:")
        for gate, count in sorted_gates[:5]:
            print(f"  {gate}: {count}")
    
    # Circuit visualization (truncated for large circuits)
    print("\nCircuit (first 100 chars):")
    circuit_str = str(circuit)
    if len(circuit_str) > 100:
        print(circuit_str[:100] + "...")
    else:
        print(circuit_str)


def main():
    """
    Run comprehensive examples of hierarchical circuit generation
    """
    print("🚀 InferQ Hierarchical Circuit Generation Examples")
    print("=" * 55)
    print("Using NumPy-optimized probability adaptation system")
    
    try:
        # Example 1: Basic usage
        circuit1 = example_1_basic_usage()
        analyze_circuit(circuit1, "Example 1 Analysis")
        
        # Example 2: Custom probabilities  
        circuit2 = example_2_custom_probabilities()
        analyze_circuit(circuit2, "Example 2 Analysis")
        
        # Example 3: Synergy demonstration
        circuit3 = example_3_synergy_demonstration()
        analyze_circuit(circuit3, "Example 3 Analysis")
        
        print("\n" + "=" * 55)
        print("🎉 All examples completed!")
        
        # Summary
        circuits = [c for c in [circuit1, circuit2, circuit3] if c and c.data]
        if circuits:
            avg_depth = sum(c.depth() for c in circuits) / len(circuits)
            avg_gates = sum(len(c.data) for c in circuits) / len(circuits)
            print(f"📈 Summary: Generated {len(circuits)} circuits")
            print(f"   Average depth: {avg_depth:.1f}")
            print(f"   Average gates: {avg_gates:.1f}")
        
    except Exception as e:
        print(f"\n💥 Error during examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
