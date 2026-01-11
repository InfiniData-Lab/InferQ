from typing import Dict, Any
import numpy as np
from qiskit import QuantumCircuit
from qiskit.result import Result
from .types import SimulationMethod
from simulators.simulation_utils import SimulationAnalyzer
import logging

logger = logging.getLogger(__name__)

class ResultExtractor:
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
                    probabilities = result.get_statevector().probabilities()
                    # Calculate entropy
                    entropy = self._calculate_entropy(probabilities)
                    # Sparsity
                    sparsity = self._calculate_sparsity(probabilities)

                    data["entropy"] = entropy
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

    def _calculate_entropy(self, probabilities: np.ndarray) -> float:
        """
        Calculate von Neumann entropy using the existing simulation_utils function.

        Args:
            probabilities: Array of probabilities

        Returns:
            Entropy value
        """
        analyzer = SimulationAnalyzer()
        return analyzer._calculate_entropy(probabilities)

    def _calculate_sparsity(self, probabilities: np.ndarray) -> float:
        """
        Calculates sparsity of a probability distribution.

        Args:
            probabilities: Array of probabilities

        Returns:
            Sparsity value
        """
        analyzer = SimulationAnalyzer()
        return analyzer._calculate_sparsity(probabilities)
