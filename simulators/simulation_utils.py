"""
Utility functions for quantum circuit simulation analysis and comparison.

This module provides helper functions for analyzing simulation results,
comparing different methods, and extracting useful metrics.
"""

import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from qiskit.quantum_info import state_fidelity, Statevector, DensityMatrix
from qiskit.result import Result
import matplotlib.pyplot as plt
from dataclasses import dataclass
import json


@dataclass
class SimulationMetrics:
    """Data class for storing simulation metrics."""

    method: str
    success: bool
    execution_time: Optional[float] = None
    memory_usage: Optional[float] = None
    circuit_depth: Optional[int] = None
    circuit_size: Optional[int] = None
    num_qubits: Optional[int] = None
    fidelity: Optional[float] = None
    entropy: Optional[float] = None
    purity: Optional[float] = None
    error_message: Optional[str] = None
    actual_method: Optional[str] = None


class SimulationAnalyzer:
    """Analyzer for comparing and evaluating simulation results."""

    def __init__(self):
        self.results_history = []

    def add_results(
        self, results: Dict[str, Dict[str, Any]], circuit_name: str = "unknown"
    ) -> None:
        """
        Add simulation results to the analyzer.

        Args:
            results: Dictionary of simulation results from QuantumSimulator
            circuit_name: Name identifier for the circuit
        """
        entry = {
            "circuit_name": circuit_name,
            "timestamp": np.datetime64("now"),
            "results": results,
        }
        self.results_history.append(entry)

    def extract_metrics(
        self, results: Dict[str, Dict[str, Any]]
    ) -> List[SimulationMetrics]:
        """
        Extract standardized metrics from simulation results.

        Args:
            results: Dictionary of simulation results

        Returns:
            List of SimulationMetrics objects
        """
        metrics = []

        for method, result in results.items():
            if result["success"]:
                metric = SimulationMetrics(
                    method=method,
                    success=True,
                    # Use the new simplified structure
                    circuit_depth=result.get("transpiled_circuit_depth"),
                    circuit_size=result.get("transpiled_circuit_size"),
                    num_qubits=result.get("transpiled_num_qubits"),
                    execution_time=result.get("execution_time"),
                    memory_usage=result.get("memory_usage"),
                )

                # Calculate additional metrics only for statevector (simplified)
                data = result.get("data", {})

                if "actual_method" in data:
                    metric.actual_method = data["actual_method"]

                if "probabilities" in data:
                    probs = data["probabilities"]
                    # Calculate entropy
                    metric.entropy = self._calculate_entropy(probs)

            else:
                metric = SimulationMetrics(
                    method=method,
                    success=False,
                    error_message=result.get("error", "Unknown error"),
                )

            metrics.append(metric)

        return metrics

    def compare_statevectors(
        self, results: Dict[str, Dict[str, Any]], reference_method: str = "statevector"
    ) -> Dict[str, float]:
        """
        Compare statevectors from different simulation methods.

        Args:
            results: Dictionary of simulation results
            reference_method: Method to use as reference for comparison

        Returns:
            Dictionary mapping method names to fidelities with reference
        """
        if reference_method not in results or not results[reference_method]["success"]:
            raise ValueError(
                f"Reference method {reference_method} not available or failed"
            )

        ref_data = results[reference_method]["data"]
        if "statevector" not in ref_data:
            raise ValueError(
                f"Reference method {reference_method} does not provide statevector"
            )

        ref_statevector = Statevector(ref_data["statevector"])
        fidelities = {}

        for method, result in results.items():
            if not result["success"] or method == reference_method:
                continue

            data = result["data"]
            if "statevector" in data:
                try:
                    test_statevector = Statevector(data["statevector"])
                    fidelity = state_fidelity(ref_statevector, test_statevector)
                    fidelities[method] = float(fidelity)
                except Exception as e:
                    print(f"Error calculating fidelity for {method}: {e}")

        return fidelities

    def compare_measurement_distributions(
        self, results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, float]]:
        """
        Compare measurement count distributions between methods.

        Args:
            results: Dictionary of simulation results

        Returns:
            Dictionary of statistical distances between distributions
        """
        methods_with_counts = {}

        # Extract count distributions
        for method, result in results.items():
            if result["success"] and "counts" in result["data"]:
                counts = result["data"]["counts"]
                total_shots = sum(counts.values())
                # Normalize to probabilities
                probs = {state: count / total_shots for state, count in counts.items()}
                methods_with_counts[method] = probs

        if len(methods_with_counts) < 2:
            return {}

        # Calculate pairwise distances
        distances = {}
        methods = list(methods_with_counts.keys())

        for i, method1 in enumerate(methods):
            distances[method1] = {}
            for method2 in methods[i + 1 :]:
                # Calculate total variation distance
                tv_distance = self._total_variation_distance(
                    methods_with_counts[method1], methods_with_counts[method2]
                )
                distances[method1][method2] = tv_distance

        return distances

    def generate_performance_report(
        self, results: Dict[str, Dict[str, Any]], circuit_name: str = "Circuit"
    ) -> str:
        """
        Generate a comprehensive performance report.

        Args:
            results: Dictionary of simulation results
            circuit_name: Name of the circuit being analyzed

        Returns:
            Formatted report string
        """
        metrics = self.extract_metrics(results)

        report = []
        report.append(f"Simulation Performance Report: {circuit_name}")
        report.append("=" * 60)

        # Success rate
        successful = [m for m in metrics if m.success]
        report.append(f"Success Rate: {len(successful)}/{len(metrics)} methods")

        if not successful:
            report.append("No successful simulations to analyze.")
            return "\n".join(report)

        # Circuit properties (transpiled)
        if successful[0].circuit_depth is not None:
            report.append(f"Transpiled Circuit Depth: {successful[0].circuit_depth}")
            report.append(f"Transpiled Circuit Size: {successful[0].circuit_size}")
            report.append(f"Transpiled Number of Qubits: {successful[0].num_qubits}")

        report.append("\nMethod-specific Results:")
        report.append("-" * 40)

        for metric in metrics:
            if metric.success:
                report.append(f"{metric.method}:")
                if metric.execution_time is not None:
                    report.append(f"  Execution Time: {metric.execution_time:.4f}s")
                if metric.memory_usage is not None:
                    report.append(f"  Memory Usage: {metric.memory_usage}")
                if metric.entropy is not None:
                    report.append(f"  Entropy: {metric.entropy:.4f}")
            else:
                report.append(f"{metric.method}: FAILED - {metric.error_message}")

        # Fidelity comparison if possible
        try:
            fidelities = self.compare_statevectors(results)
            if fidelities:
                report.append("\nStatevector Fidelities (vs statevector method):")
                report.append("-" * 40)
                for method, fidelity in fidelities.items():
                    report.append(f"{method}: {fidelity:.6f}")
        except Exception as e:
            report.append(f"\nFidelity comparison failed: {e}")

        return "\n".join(report)

    def plot_comparison(
        self, results: Dict[str, Dict[str, Any]], save_path: Optional[str] = None
    ) -> None:
        """
        Create visualization comparing simulation results.

        Args:
            results: Dictionary of simulation results
            save_path: Optional path to save the plot
        """
        metrics = self.extract_metrics(results)
        successful_metrics = [m for m in metrics if m.success]

        if len(successful_metrics) < 2:
            print("Need at least 2 successful simulations for comparison plot")
            return

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle("Simulation Method Comparison", fontsize=16)

        methods = [m.method for m in successful_metrics]

        # Circuit properties
        depths = [
            m.circuit_depth for m in successful_metrics if m.circuit_depth is not None
        ]
        sizes = [
            m.circuit_size for m in successful_metrics if m.circuit_size is not None
        ]

        if depths:
            axes[0, 0].bar(methods[: len(depths)], depths)
            axes[0, 0].set_title("Circuit Depth")
            axes[0, 0].set_ylabel("Depth")
            axes[0, 0].tick_params(axis="x", rotation=45)

        if sizes:
            axes[0, 1].bar(methods[: len(sizes)], sizes)
            axes[0, 1].set_title("Circuit Size")
            axes[0, 1].set_ylabel("Size")
            axes[0, 1].tick_params(axis="x", rotation=45)

        # Entropy comparison
        entropies = [m.entropy for m in successful_metrics if m.entropy is not None]
        if entropies:
            axes[1, 0].bar(methods[: len(entropies)], entropies)
            axes[1, 0].set_title("State Entropy")
            axes[1, 0].set_ylabel("Entropy")
            axes[1, 0].tick_params(axis="x", rotation=45)

        # Purity comparison
        purities = [m.purity for m in successful_metrics if m.purity is not None]
        if purities:
            axes[1, 1].bar(methods[: len(purities)], purities)
            axes[1, 1].set_title("State Purity")
            axes[1, 1].set_ylabel("Purity")
            axes[1, 1].tick_params(axis="x", rotation=45)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")

        plt.show()

    def export_results(self, results: Dict[str, Dict[str, Any]], filename: str) -> None:
        """
        Export simulation results to JSON file.

        Args:
            results: Dictionary of simulation results
            filename: Output filename
        """
        # Convert numpy arrays to lists for JSON serialization
        exportable_results = {}

        for method, result in results.items():
            exportable_result = {
                "success": result["success"],
                "method": result["method"],
            }

            if result["success"]:
                exportable_result.update(
                    {
                        "execution_time": result.get("execution_time"),
                        "memory_usage": result.get("memory_usage"),
                        "transpiled_circuit_depth": result.get(
                            "transpiled_circuit_depth"
                        ),
                        "transpiled_circuit_size": result.get(
                            "transpiled_circuit_size"
                        ),
                        "transpiled_num_qubits": result.get("transpiled_num_qubits"),
                        "transpiled_num_clbits": result.get("transpiled_num_clbits"),
                    }
                )

                # Handle data with numpy arrays
                data = result.get("data", {})
                exportable_data = {}

                for key, value in data.items():
                    if isinstance(value, np.ndarray):
                        if np.iscomplexobj(value):
                            # Convert complex arrays to real/imag parts
                            exportable_data[f"{key}_real"] = value.real.tolist()
                            exportable_data[f"{key}_imag"] = value.imag.tolist()
                        else:
                            exportable_data[key] = value.tolist()
                    elif isinstance(value, (np.integer, np.floating)):
                        exportable_data[key] = float(value)
                    elif isinstance(value, (np.complexfloating)):
                        exportable_data[f"{key}_real"] = float(value.real)
                        exportable_data[f"{key}_imag"] = float(value.imag)
                    else:
                        exportable_data[key] = value

                exportable_result["data"] = exportable_data
            else:
                exportable_result["error"] = result.get("error")

            exportable_results[method] = exportable_result

        with open(filename, "w") as f:
            json.dump(exportable_results, f, indent=2)

        print(f"Results exported to {filename}")

    def _calculate_entropy(self, probabilities: np.ndarray) -> float:
        """Calculate von Neumann entropy of a probability distribution."""
        # Add small epsilon to avoid log(0)
        probs = probabilities + 1e-16
        entropy = -np.sum(probs * np.log2(probs))
        return float(entropy)

    def _calculate_sparsity(
        self, probabilities: np.ndarray, atol: float = 1e-10
    ) -> float:
        """Calculate sparsity of a probability distribution."""
        return float(np.count_nonzero(probabilities > atol) / len(probabilities))

    def _total_variation_distance(
        self, dist1: Dict[str, float], dist2: Dict[str, float]
    ) -> float:
        """Calculate total variation distance between two probability distributions."""
        all_states = set(dist1.keys()) | set(dist2.keys())

        distance = 0.0
        for state in all_states:
            p1 = dist1.get(state, 0.0)
            p2 = dist2.get(state, 0.0)
            distance += abs(p1 - p2)

        return distance / 2.0


def process_simulation_data_for_features(
    simulation_results: Dict[str, Dict[str, Any]], extracted_features: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process simulation results and integrate them with extracted features for storage.

    Args:
        simulation_results: Raw simulation results from QuantumSimulator
        extracted_features: Circuit features from feature extractors

    Returns:
        Combined features dictionary with simulation data as individual columns
    """
    import logging

    logger = logging.getLogger(__name__)

    # Start with extracted features
    combined_features = extracted_features.copy()

    # Extract essential simulation data first
    simulation_data = extract_essential_simulation_data(simulation_results)

    # Define all simulation methods to track
    simulation_methods = [
        "statevector",
        "matrix_product_state",
        "unitary",
        "density_matrix",
        "stabilizer",
        "extended_stabilizer",
        "statevector_saved",
    ]

    for method in simulation_methods:
        if method in simulation_data and simulation_data[method]["success"]:
            # Add execution time and memory for successful simulations
            combined_features[f"{method}_execution_time"] = simulation_data[method].get(
                "execution_time"
            )
            combined_features[f"{method}_memory_usage"] = simulation_data[method].get(
                "memory_usage"
            )

            # Add transpiled circuit stats
            combined_features[f"{method}_transpiled_depth"] = simulation_data[
                method
            ].get("transpiled_circuit_depth")
            combined_features[f"{method}_transpiled_size"] = simulation_data[
                method
            ].get("transpiled_circuit_size")

            # Add transpiled gate counts
            gate_counts = simulation_data[method].get("transpiled_gate_counts", {})
            combined_features[f"{method}_gate_counts"] = gate_counts

            # Special handling for statevector entropy
            if method == "statevector_saved":
                statevector_data = simulation_data[method].get("simulation_data", {})
                if (
                    "entropy" in statevector_data
                    and statevector_data["entropy"] is not None
                ):
                    combined_features["statevector_saved_entropy"] = statevector_data[
                        "entropy"
                    ]
                    logger.info(
                        f"✓ Statevector entropy calculated: {statevector_data['entropy']:.4f}"
                    )
                if (
                    "sparsity" in statevector_data
                    and statevector_data["sparsity"] is not None
                ):
                    combined_features["statevector_saved_sparsity"] = statevector_data[
                        "sparsity"
                    ]
                    logger.info(
                        f"✓ Statevector sparsity calculated: {statevector_data['sparsity']:.4f}"
                    )
                # if "probablities":
                #     combined_features["probabilities"]=list(statevector_data["probabilities"])
        else:
            # For failed simulations, set to None
            combined_features[f"{method}_execution_time"] = None
            combined_features[f"{method}_memory_usage"] = None
            combined_features[f"{method}_transpiled_depth"] = None
            combined_features[f"{method}_transpiled_size"] = None
            combined_features[f"{method}_gate_counts"] = None

            if method == "statevector":
                combined_features["statevector_entropy"] = None

    logger.info(f"✓ Simulation data processed and added to features")
    logger.info(
        f"✓ Added individual columns for {len(simulation_methods)} simulation methods"
    )

    return combined_features


def extract_essential_simulation_data(
    results: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Extract only essential data from simulation results for storage/analysis.

    Args:
        results: Full simulation results from QuantumSimulator

    Returns:
        Dictionary with only essential data (execution time, memory, transpiled stats, statevector data)
    """
    essential_data = {}

    for method, result in results.items():
        if result["success"]:
            essential_result = {
                "success": True,
                "method": method,
                "execution_time": result.get("execution_time"),
                "memory_usage": result.get("memory_usage"),
                "transpiled_circuit_depth": result.get("transpiled_circuit_depth"),
                "transpiled_circuit_size": result.get("transpiled_circuit_size"),
                "transpiled_num_qubits": result.get("transpiled_num_qubits"),
                "transpiled_num_clbits": result.get("transpiled_num_clbits"),
                "transpiled_gate_counts": result.get("transpiled_gate_counts", {}),
            }

            # Only include simulation data for statevector
            data = result.get("data", {})
            if method == "statevector_saved":
                essential_result["simulation_data"] = {
                    "statevector": data.get("statevector"),
                    "probabilities": data.get("probabilities"),
                    "entropy": data.get("entropy"),  # Include entropy from simulation
                    "sparsity": data.get("sparsity"),
                }
            elif "counts" in data:
                essential_result["simulation_data"] = {"counts": data.get("counts")}

            essential_data[method] = essential_result
        else:
            essential_data[method] = {
                "success": False,
                "method": method,
                "error": result.get("error", "Unknown error"),
            }

    return essential_data


def benchmark_simulation_methods(
    circuit, shots: int = 1024, seed: int = 42
) -> Dict[str, Any]:
    """
    Benchmark all simulation methods on a given circuit.

    Args:
        circuit: Quantum circuit to benchmark
        shots: Number of shots for sampling-based simulations
        seed: Random seed for reproducible results

    Returns:
        Dictionary containing benchmark results and analysis
    """
    from .simulate import QuantumSimulator

    simulator = QuantumSimulator(shots=shots, seed=seed)
    analyzer = SimulationAnalyzer()

    # Run all simulations
    results = simulator.simulate_all_methods(circuit)

    # Analyze results
    metrics = analyzer.extract_metrics(results)
    report = analyzer.generate_performance_report(results, "Benchmark Circuit")

    # Try to calculate fidelities
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
