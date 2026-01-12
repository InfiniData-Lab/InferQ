import time
import logging
import numpy as np
from qiskit import transpile

# Configure logging
logger = logging.getLogger(__name__)

class IQSGateWrapper:
    """Wrapper for InfiniQuantumSim gates"""
    def __init__(self, tensor, qubits):
        self.tensor = tensor
        self.qubits = qubits

try:
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit, Gate as IQSGate
    import InfiniQuantumSim.mps as iqs_mps
    INFINI_QUANTUM_AVAILABLE = True
except ImportError as e:
    # logger.debug(f"InfiniQuantumSim import failed: {e}")
    INFINI_QUANTUM_AVAILABLE = False


def _execute_infiniquantum_simulation(qc, **kwargs):
    """
    Standalone function to run InfiniQuantumSim simulation.
    Can be run in a separate process.
    """
    if not INFINI_QUANTUM_AVAILABLE:
            return {"success": False, "error": "InfiniQuantumSim not installed", "method": "infiniquantum"}
    
    start_time = time.time()
    try:
        
        # Transpile to ensure we only have 1 and 2 qubit gates
        # InfiniQuantumSim handles gates by matrix, so we just need to decompose
        transpiled_qc = transpile(qc, basis_gates=['u', 'cx', 'id', 'rz', 'sx', 'x'], optimization_level=2)
        
        num_qubits = transpiled_qc.num_qubits
        
        # Check if circuit is too large for InfiniQuantumSim
        # InfiniQuantumSim uses single characters for indices. 
        # The number of available characters is limited (around 500-600 based on utils.py).
        # Each gate adds 1 or 2 indices.
        # Rough estimate: num_qubits + 2 * num_gates < len(INDICES)
        # If we exceed this, we should skip or fail gracefully.
        from InfiniQuantumSim.utils import INDICES
        # Use a safer estimate or check exact usage if possible.
        # For now, let's be conservative.
        estimated_indices = num_qubits + 3 * len(transpiled_qc.data) # Increased multiplier to be safe
        if estimated_indices >= len(INDICES):
                logger.warning(f"Skipping InfiniQuantumSim: Circuit  too large (indices limit): {estimated_indices} > {len(INDICES)}")
                return {
                "success": False,
                "error": f"Circuit too large for InfiniQuantumSim (indices limit): {estimated_indices} > {len(INDICES)}",
                "method": "infiniquantum",
                "skipped": True
            }

        iqs_qc = IQSQuantumCircuit(num_qubits=num_qubits)
        
        # Add gates to IQS circuit
        for instruction in transpiled_qc.data:
            op = instruction.operation
            qubits = [transpiled_qc.find_bit(q).index for q in instruction.qubits]
            
            if op.name == 'barrier':
                continue
            if op.name == 'measure':
                continue
                
            matrix = op.to_matrix()
            
            # Reshape matrix for IQS Gate
            # IQS expects (2, 2, 2, 2) for 2-qubit gates, (2, 2) for 1-qubit
            if len(qubits) == 1:
                tensor = matrix
            elif len(qubits) == 2:
                tensor = matrix.reshape(2, 2, 2, 2)
            else:
                raise ValueError(f"Unsupported operation {op.name} on {len(qubits)} qubits")
            
            # Create unique name for parameterized gates to avoid tensor collision if needed
            # But for now, let's just use op.name + id(op) to be safe? 
            # Or just op.name if it's standard. 
            # IQS uses name as key in tensor_uniques. 
            # If we have two RZ gates with different angles, they must have different names.
            if len(op.params) > 0:
                gate_name = f"{op.name}_{id(op)}"
            else:
                gate_name = op.name
            
            gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
            iqs_qc.add_gate(gate)

        # Run benchmark
        n_runs = kwargs.get("n_runs", 1)
        # Default to skipping database methods unless explicitly requested
        # This prevents connection errors if DBs are not set up
        oom = kwargs.get("oom", ["psql", "sqlite", "ducksql", "eqc"])
        timeout = kwargs.get("timeout", None)
        
        logger.info(f"Running InfiniQuantumSim benchmark with {n_runs} runs...")
        benchmark_results = iqs_qc.benchmark_ciruit_performance(n_runs, oom=oom, timeout_seconds=timeout)
        
        # Process results
        processed_results = {}
        for method, data in benchmark_results.items():
            if not data: # Empty dict if skipped or failed
                continue
                
            # Calculate averages
            if "memory" in data and "time" in data:
                # Check if lists are None (can happen if initialization failed)
                if data["memory"] is None or data["time"] is None:
                    continue

                # Filter out None values which can occur if a run failed
                mem_values = [x for x in data["memory"] if x is not None]
                time_values = [x for x in data["time"] if x is not None]
                
                if mem_values:
                    mem_avg = np.mean(mem_values)
                    mem_avg_mb = mem_avg / (1024 * 1024)
                else:
                    mem_avg_mb = 0.0
                    
                if time_values:
                    tim_avg = np.mean(time_values)
                else:
                    tim_avg = 0.0

                processed_results[method] = {
                    "memory_avg_mb": mem_avg_mb,
                    "time_avg_s": tim_avg,
                    "raw": data
                }
            elif method == "eqc":
                    # Handle EQC special structure if present (based on user snippet)
                    # But user snippet logic was complex, let's just return raw for now
                    processed_results[method] = data

        execution_time = time.time() - start_time
        
        return {
            "success": True,
            "method": "infiniquantum",
            "benchmark_results": processed_results,
            "execution_time": execution_time,
            "backend_name": "InfiniQuantumSim",
        }

    except Exception as e:
        logger.error(f"InfiniQuantumSim failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "method": "infiniquantum",
            "execution_time": time.time() - start_time
        }


def _wrapper_run_iqs(qc, kwargs, q):
    """Wrapper to run IQS simulation in a process and put result in queue"""
    try:
        res = _execute_infiniquantum_simulation(qc, **kwargs)
        q.put(res)
    except Exception as e:
        q.put({"success": False, "error": str(e), "method": "infiniquantum"})
