from typing import Dict, Any
from .analyzer import SimulationAnalyzer

def benchmark_simulation_methods(
    circuit, shots: int = 1024, seed: int = 42
) -> Dict[str, Any]:
    """
    Benchmark all simulation methods on a given circuit.
    Wrapper around QuantumSimulator and SimulationAnalyzer.
    """
    # Import locally to avoid circular dependency
    from ..simulate import QuantumSimulator
    
    simulator = QuantumSimulator(shots=shots, seed=seed)
    analyzer = SimulationAnalyzer()

    # Run all simulations
    results = simulator.simulate_all_methods(circuit)

    # Analyze results
    metrics = analyzer.extract_metrics(results)
    report = analyzer.generate_performance_report(results, "Benchmark Circuit")
    
    fidelities = {}
    try:
        fidelities = analyzer.compare_statevectors(results)
    except Exception as e:
        print(f"Fidelity calculation failed: {e}")

    return {
        "results": results,
        "metrics": metrics,
        "report": report,
        "fidelities": fidelities,
        "analyzer": analyzer,
    }
