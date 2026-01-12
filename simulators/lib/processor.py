from typing import Dict, Any
import logging
import numpy as np

logger = logging.getLogger(__name__)

def process_simulation_data_for_features(
    simulation_results: Dict[str, Dict[str, Any]], extracted_features: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process simulation results and integrate them with extracted features for storage.
    """
    combined_features = extracted_features.copy()
    simulation_data = extract_essential_simulation_data(simulation_results)
    
    simulation_methods = [
        "statevector", "matrix_product_state", "unitary", 
        "density_matrix", "stabilizer", "extended_stabilizer", 
        "statevector_saved", "infiniquantum"
    ]

    for method in simulation_methods:
        if method in simulation_data and simulation_data[method]["success"]:
            # Add basic stats
            combined_features[f"{method}_execution_time"] = simulation_data[method].get("execution_time")
            combined_features[f"{method}_memory_usage"] = simulation_data[method].get("memory_usage")

            # Add transpiled stats if available
            combined_features[f"{method}_transpiled_depth"] = simulation_data[method].get("transpiled_circuit_depth")
            combined_features[f"{method}_transpiled_size"] = simulation_data[method].get("transpiled_circuit_size")

            # Add gate counts
            gate_counts = simulation_data[method].get("transpiled_gate_counts", {})
            combined_features[f"{method}_gate_counts"] = gate_counts

            # Check for generic benchmark results (e.g. from InfiniQuantumSim)
            if "benchmark_results" in simulation_data[method]:
                 # Flatten benchmark results into features if needed, or store as JSON blob
                 combined_features[f"{method}_benchmark"] = simulation_data[method]["benchmark_results"]

            # Special handling for statevector features
            if method == "statevector_saved":
                sd = simulation_data[method].get("simulation_data", {})
                if "entropy" in sd and sd["entropy"] is not None:
                    combined_features["statevector_saved_entropy"] = sd["entropy"]
                if "sparsity" in sd and sd["sparsity"] is not None:
                    combined_features["statevector_saved_sparsity"] = sd["sparsity"]
        else:
            # Set failed/missing to None
            msg = f"{method}_"
            combined_features[f"{msg}execution_time"] = None
            combined_features[f"{msg}memory_usage"] = None
            combined_features[f"{msg}transpiled_depth"] = None
            combined_features[f"{msg}transpiled_size"] = None
            combined_features[f"{msg}gate_counts"] = None
            
            if method == "statevector":
                 combined_features["statevector_entropy"] = None

    return combined_features

def extract_essential_simulation_data(
    results: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Extract only essential data from simulation results for storage/analysis.
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
            
            # Pass through raw benchmark results (e.g. from IQS)
            if "benchmark_results" in result:
                essential_result["benchmark_results"] = result["benchmark_results"]

            # Handle simulation data (counts, statevector properties)
            data = result.get("data", {})
            
            if method == "statevector_saved":
                essential_result["simulation_data"] = {
                    # Don't store full statevector/probs in essential data to save space if not needed
                    # "statevector": data.get("statevector"), 
                    # "probabilities": data.get("probabilities"),
                    "entropy": data.get("entropy"),
                    "sparsity": data.get("sparsity"),
                }
                # Keep statevector for fidelity check if available in data
                if "statevector" in data:
                     essential_result["simulation_data"]["statevector"] = data["statevector"]

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
