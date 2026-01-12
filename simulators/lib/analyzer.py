import numpy as np
from typing import Dict, Any, List, Optional
from qiskit.quantum_info import state_fidelity, Statevector
import matplotlib.pyplot as plt
import json
from .metrics import SimulationMetrics

class SimulationAnalyzer:
    """Analyzer for comparing and evaluating simulation results."""

    def __init__(self):
        self.results_history = []

    def add_results(
        self, results: Dict[str, Dict[str, Any]], circuit_name: str = "unknown"
    ) -> None:
        """Add simulation results to the analyzer."""
        entry = {
            "circuit_name": circuit_name,
            "timestamp": np.datetime64("now"),
            "results": results,
        }
        self.results_history.append(entry)

    def extract_metrics(
        self, results: Dict[str, Dict[str, Any]]
    ) -> List[SimulationMetrics]:
        """Extract standardized metrics from simulation results."""
        metrics = []

        for method, result in results.items():
            if result["success"]:
                metric = SimulationMetrics(
                    method=method,
                    success=True,
                    circuit_depth=result.get("transpiled_circuit_depth"),
                    circuit_size=result.get("transpiled_circuit_size"),
                    num_qubits=result.get("transpiled_num_qubits"),
                    execution_time=result.get("execution_time"),
                    memory_usage=result.get("memory_usage"),
                )

                data = result.get("data", {})
                if "actual_method" in data:
                    metric.actual_method = data["actual_method"]

                if "probabilities" in data:
                    metric.entropy = self._calculate_entropy(data["probabilities"])
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
        """Compare statevectors from different simulation methods."""
        if reference_method not in results or not results[reference_method]["success"]:
            raise ValueError(f"Reference method {reference_method} not available or failed")

        ref_data = results[reference_method]["data"]
        if "statevector" not in ref_data:
            # Fallback to statevector_saved if standard statevector method fails 
            if "statevector_saved" in results and results["statevector_saved"]["success"] and \
               "statevector" in results["statevector_saved"]["data"].get("simulation_data", {}):
               ref_data = results["statevector_saved"]["data"]["simulation_data"]
            else:
               raise ValueError(f"Reference method {reference_method} does not provide statevector")

        ref_statevector = Statevector(ref_data["statevector"])
        fidelities = {}

        for method, result in results.items():
            if not result["success"] or method == reference_method:
                continue

            data = result["data"]
            sv_data = data.get("statevector")
            
            # Check for saved statevector structure
            if not sv_data and "simulation_data" in data:
                 sv_data = data["simulation_data"].get("statevector")

            if sv_data:
                try:
                    test_statevector = Statevector(sv_data)
                    fidelity = state_fidelity(ref_statevector, test_statevector)
                    fidelities[method] = float(fidelity)
                except Exception as e:
                    print(f"Error calculating fidelity for {method}: {e}")

        return fidelities

    def generate_performance_report(
        self, results: Dict[str, Dict[str, Any]], circuit_name: str = "Circuit"
    ) -> str:
        """Generate a comprehensive performance report."""
        metrics = self.extract_metrics(results)
        report = []
        report.append(f"Simulation Performance Report: {circuit_name}")
        report.append("=" * 60)

        successful = [m for m in metrics if m.success]
        report.append(f"Success Rate: {len(successful)}/{len(metrics)} methods")

        if not successful:
            report.append("No successful simulations to analyze.")
            return "\n".join(report)

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

        try:
            fidelities = self.compare_statevectors(results)
            if fidelities:
                report.append("\nStatevector Fidelities (vs statevector method):")
                report.append("-" * 40)
                for method, fidelity in fidelities.items():
                    report.append(f"{method}: {fidelity:.6f}")
        except Exception as e:
            report.append(f"\nFidelity comparison failed/skipped: {e}")

        return "\n".join(report)

    def _calculate_entropy(self, probabilities: np.ndarray) -> float:
        """Calculate von Neumann entropy."""
        probs = probabilities + 1e-16
        entropy = -np.sum(probs * np.log2(probs))
        return float(entropy)
    
    def _calculate_sparsity(self, probabilities: np.ndarray, atol: float = 1e-10) -> float:
        return float(np.count_nonzero(probabilities > atol) / len(probabilities))

