from typing import Dict, Any
from qiskit import QuantumCircuit
from qiskit.result import Result
from .types import SimulationMethod
from .analyzer import (
    calculate_shannon_entropy,
    calculate_sparsity,
    calculate_von_neumann_entropy,
)
import logging

logger = logging.getLogger(__name__)

class DynamicFeatureExtractor:
    def _extract_simulation_data(
        self, result: Result, method: SimulationMethod, qc: QuantumCircuit
    ) -> Dict[str, Any]:
        """
        Extract minimal simulation data - only counts/simulation data for statevector.
        Returns execution time, memory, and basic stats for all methods.

        Args:
            result: Qiskit Result object
            method: Simulation method used
            qc: Quantum circuit that was simulated

        Returns:
            Dictionary containing minimal extracted data
        """
        data = {}

        try:
            # Try to identify the actual method used
            if (
                hasattr(result, "results")
                and result.results
                and len(result.results) > 0
            ):
                res_metadata = result.results[0].metadata
                if res_metadata and "method" in res_metadata:
                    data["actual_method"] = res_metadata["method"]

            # Only extract detailed simulation data for statevector
            if method == SimulationMethod.STATEVECTOR:
                if "statevector" in result.data(0):
                    sv = result.get_statevector()
                    probabilities = sv.probabilities()
                    # Calculate entropy
                    shannon_entropy = calculate_shannon_entropy(probabilities)
                    # Calculate per-qubit von Neumann entropy
                    von_neumann_entropy = calculate_von_neumann_entropy(sv.data)
                    # Sparsity
                    sparsity = calculate_sparsity(probabilities)

                    data["shannon_entropy"] = shannon_entropy
                    data["von_neumann_entropy"] = von_neumann_entropy
                    data["sparsity"] = sparsity
                    data["probabilities"] = probabilities

            # For all other methods, just check if they have counts (if applicable)
            elif hasattr(result, "get_counts") and qc.num_clbits > 0:
                try:
                    data["counts"] = result.get_counts(0)
                except:
                    # If counts extraction fails, don't store anything
                    pass
            metadata = getattr(result, "metadata", None)
            # Basic execution stats for all methods
            data["execution_time"] = getattr(result, "time_taken", None)
            data["memory_usage"] = (
                metadata.get("max_memory_mb", None) if metadata else None
            )

        except Exception as e:
            logger.warning(f"Error extracting data for {method.value}: {e}")
            data["extraction_error"] = str(e)

        return data
