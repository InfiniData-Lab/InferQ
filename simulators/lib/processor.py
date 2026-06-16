from typing import Dict, Any, List
import logging
from feature_extractors.sql_analyzer import SQLFeatureExtractor

logger = logging.getLogger(__name__)

# List of metric keys to automatically extract from simulation data if present
METRIC_KEYS = [
    "shannon_entropy", 
    "von_neumann_entropy", 
    "sparsity", 
]

def process_simulation_data_for_features(
    simulation_results: Dict[str, Dict[str, Any]], extracted_features: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process simulation results and integrate them with extracted features for storage.
    Dynamically handles and extracts features from any simulation method present in results.
    """
    combined_features = extracted_features.copy()
    
    # Iterate over all methods present in the results
    for method, result in simulation_results.items():
        if not result.get("success", False):
            # Set standard fields to None for consistency
            _set_missing_features(combined_features, method)
            continue

        # 1. Basic Performance & Transpilation Metrics
        combined_features[f"{method}_execution_time"] = result.get("execution_time")
        combined_features[f"{method}_memory_usage"] = result.get("memory_usage")
        combined_features[f"{method}_transpiled_depth"] = result.get("transpiled_circuit_depth")
        combined_features[f"{method}_transpiled_size"] = result.get("transpiled_circuit_size")
        
        # Note: gate_counts is a dictionary, stored as is. 
        # Downstream processors might need to flatten this if they need scalar columns.
        combined_features[f"{method}_gate_counts"] = result.get("transpiled_gate_counts", {})

        # 2. Benchmark Results (e.g. from InfiniQuantumSim or others)
        if "benchmark_results" in result:
             # Special handling for InfiniQuantum renaming and flattening
             prefix = "infinidata_quantum" if method == "infiniquantum" else method
             _flatten_benchmark_results(prefix, result["benchmark_results"], combined_features)
             if method == "infiniquantum":
                 _flatten_infiniquantum_rdbms_results(result["benchmark_results"], combined_features)

        # 2.5 Extract SQL Features if present
        if "sql_query" in result:
             try:
                sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(result["sql_query"])
                prefix = "infinidata_quantum" if method == "infiniquantum" else method
                
                # Add SQL features
                for feat_name, count in sql_features.items():
                    combined_features[f"{prefix}_sql_{feat_name}"] = count
                    
                # Add join complexity
                combined_features[f"{prefix}_sql_num_joins"] = len(join_edges)
             except Exception as e:
                logger.error(f"Failed to extract SQL features for method {method}: {e}")

        # 3. Extract Specific Scalar Metrics from Data
        # We look in 'data' and backward-compatible 'simulation_data' locations
        data = result.get("data", {})
        
        # Check standard location (ResultExtractor puts metrics directly in 'data')
        _extract_metrics_to_features(combined_features, method, data)
        
        # Check backward-compatible location (some old runs might have 'simulation_data')
        if "simulation_data" in data and isinstance(data["simulation_data"], dict):
            _extract_metrics_to_features(combined_features, method, data["simulation_data"])


    return combined_features

def _extract_metrics_to_features(features: Dict[str, Any], method: str, source_dict: Dict[str, Any]):
    """Helper to extract known metrics from a source dictionary into features."""
    for key in METRIC_KEYS:
        if key in source_dict and source_dict[key] is not None:
            # Use the key as part of the feature name
            features[f"{method}_{key}"] = source_dict[key]

def _flatten_benchmark_results(base_name: str, benchmark_data: Dict[str, Any], features: Dict[str, Any]):
    """Recursively flatten benchmark results into feature dictionary."""
    for key, value in benchmark_data.items():
        # Clean key for variable naming (replace - with _)
        clean_key = key.replace("-", "_")
        
        # Skip raw data
        if clean_key == "raw":
            continue

        if isinstance(value, dict):
             # Recurse
             _flatten_benchmark_results(f"{base_name}_{clean_key}", value, features)
        elif isinstance(value, (int, float)):
             features[f"{base_name}_{clean_key}"] = value
        elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], (int, float)):
             # Compute average for lists of numbers (e.g. EQC memory/time)
             features[f"{base_name}_{clean_key}_avg"] = sum(value) / len(value)

def _flatten_infiniquantum_rdbms_results(benchmark_data: Dict[str, Any], features: Dict[str, Any]):
    """Expose InfiniQuantum SQL backend results under the historical rdbms_* keys."""
    for method in ("sqlite", "psql", "ducksql"):
        data = benchmark_data.get(method)
        if not isinstance(data, dict):
            continue
        time_s = data.get("time_avg_s")
        memory_mb = data.get("memory_avg_mb")
        if time_s is not None:
            features[f"rdbms_{method}_time_s"] = time_s
        if memory_mb is not None:
            features[f"rdbms_{method}_memory_mb"] = memory_mb

def _set_missing_features(features: Dict[str, Any], method: str):
    """Helper to maintain schema consistency for failed methods."""
    for suffix in ["execution_time", "memory_usage", "transpiled_depth", "transpiled_size", "gate_counts"]:
        features[f"{method}_{suffix}"] = None

def extract_essential_simulation_data(
    results: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Extract only essential data from simulation results for storage/analysis.
    Filters out large data blobs (like full statevectors) unless specifically required.
    """
    essential_data = {}

    for method, result in results.items():
        if not result.get("success", False):
            essential_data[method] = {
                "success": False,
                "method": method,
                "error": result.get("error", "Unknown error"),
            }
            continue

        # Build essential result object
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
        
        if "benchmark_results" in result:
            essential_result["benchmark_results"] = result["benchmark_results"]

        # Handle data content
        raw_data = result.get("data", {})
        essential_data_content = {}
        
        # 1. Keep counts
        if "counts" in raw_data:
            essential_data_content["counts"] = raw_data["counts"]
            
        # 2. Keep metrics
        for key in METRIC_KEYS:
            if key in raw_data:
                essential_data_content[key] = raw_data[key]
                
        # 3. Handle statevectors/probabilities (keep only if needed/requested)
        # Check for 'statevector_saved' method convention or explicit flags
        should_keep_state = (method == "statevector_saved") or result.get("keep_statevector", False)
        
        if should_keep_state:
            for key in ["statevector", "probabilities"]:
                if key in raw_data:
                    essential_data_content[key] = raw_data[key]
            
            # Legacy/Nested structure support
            if "simulation_data" in raw_data:
                essential_data_content.update(raw_data["simulation_data"])

        # Store cleaned data
        essential_result["simulation_data"] = essential_data_content
        
        essential_data[method] = essential_result

    return essential_data
