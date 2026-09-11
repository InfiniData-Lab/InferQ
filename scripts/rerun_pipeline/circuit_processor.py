"""
Circuit Processor

Handles processing of individual quantum circuits with different modes.
"""

import os
import logging
import time
import qiskit.qpy
from qiskit import transpile

logger = logging.getLogger(__name__)

# Check if InfiniQuantumSim is available
try:
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit, Gate as IQSGate
    from InfiniQuantumSim.utils import INDICES
    INFINI_QUANTUM_AVAILABLE = True
except ImportError:
    INFINI_QUANTUM_AVAILABLE = False


class CircuitProcessor:
    """Base class for processing quantum circuits"""
    
    @staticmethod
    def load_circuit_from_file(file_path: str):
        """
        Load a quantum circuit from a QPY file.
        
        Args:
            file_path: Path to the QPY file
            
        Returns:
            Tuple of (circuit, circuit_hash, filename)
        """
        with open(file_path, "rb") as f:
            circuits = qiskit.qpy.load(f)
            qc = circuits[0] if isinstance(circuits, list) else circuits
        
        filename = os.path.basename(file_path)
        circuit_hash = os.path.splitext(filename)[0]
        
        return qc, circuit_hash, filename


class SimulationProcessor(CircuitProcessor):
    """Processes circuits using quantum simulation"""
    
    def __init__(self, simulator, min_qubits=None, max_qubits=None, min_depth=None, max_depth=None):
        """
        Initialize with a QuantumSimulator instance.
        
        Args:
            simulator: Initialized QuantumSimulator
            min_qubits: Minimum qubit count to process (None = no limit)
            max_qubits: Maximum qubit count to process (None = no limit)
            min_depth: Minimum circuit depth to process (None = no limit)
            max_depth: Maximum circuit depth to process (None = no limit)
        """
        self.simulator = simulator
        self.min_qubits = min_qubits
        self.max_qubits = max_qubits
        self.min_depth = min_depth
        self.max_depth = max_depth
    
    def process_circuit_file(self, file_path: str, mode: str) -> dict:
        """
        Process a circuit file with simulation.
        
        Args:
            file_path: Path to circuit file
            mode: Simulation mode ('auto', 'all', 'rdbms')
            
        Returns:
            Dictionary with processing results
        """
        try:
            qc, circuit_hash, _ = self.load_circuit_from_file(file_path)
            
            # Check circuit size limits
            if self.min_qubits is not None and qc.num_qubits < self.min_qubits:
                logger.debug(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits below limit of {self.min_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, below limit of {self.min_qubits}",
                    "file_path": file_path,
                }

            if self.max_qubits is not None and qc.num_qubits > self.max_qubits:
                logger.debug(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits exceeds limit of {self.max_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, exceeds limit of {self.max_qubits}",
                    "file_path": file_path,
                }
            
            circuit_depth = qc.depth()
            if self.min_depth is not None and circuit_depth < self.min_depth:
                logger.debug(f"Skipping circuit {circuit_hash}: depth {circuit_depth} below limit of {self.min_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {circuit_depth} below limit of {self.min_depth}",
                    "file_path": file_path,
                }

            if self.max_depth is not None and circuit_depth > self.max_depth:
                logger.debug(f"Skipping circuit {circuit_hash}: depth {circuit_depth} exceeds limit of {self.max_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {circuit_depth} exceeds limit of {self.max_depth}",
                    "file_path": file_path,
                }
            
            updates = {}
            success_flag = False
            skipped_flag = False
            error_msg = None
            
            logger.info(f"Simulating circuit {circuit_hash} in mode {mode}")
            
            if mode == "auto":
                result = self.simulator.simulate_auto(qc)
                success_flag, skipped_flag, error_msg, updates = self._process_auto_result(result)
                
            elif mode == "all":
                results = self.simulator.simulate_all_methods(qc)
                success_flag, skipped_flag, error_msg, updates = self._process_all_results(results)
                
            elif mode == "rdbms":
                from simulators.simulate import SimulationMethod
                result = self.simulator._run_simulation(qc, SimulationMethod.INFINI_QUANTUM)
                success_flag, skipped_flag, error_msg, updates = self._process_rdbms_result(result)
            
            return {
                "hash": circuit_hash,
                "success": success_flag,
                "skipped": skipped_flag,
                "updates": updates,
                "error": error_msg,
                "file_path": file_path,
            }
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {
                "hash": None,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e),
                "file_path": file_path,
            }
    
    def _process_auto_result(self, result: dict) -> tuple:
        """Process results from auto mode"""
        updates = {}
        success_flag = False
        skipped_flag = False
        error_msg = None
        
        if result["success"]:
            success_flag = True
            data = result.get("data", {})
            actual_method = data.get("actual_method", result["method"])
            updates = {
                "automatic_method": actual_method,
                "automatic_execution_time": result["execution_time"],
                "automatic_memory_usage": result.get("memory_usage"),
                "automatic_transpiled_depth": result.get("transpiled_circuit_depth"),
                "automatic_transpiled_size": result.get("transpiled_circuit_size"),
                "automatic_transpiled_qubits": result.get("transpiled_num_qubits"),
            }
        elif result.get("skipped"):
            skipped_flag = True
            error_msg = result.get("error")
        else:
            error_msg = result.get("error")
        
        return success_flag, skipped_flag, error_msg, updates
    
    def _process_all_results(self, results: dict) -> tuple:
        """Process results from all methods mode"""
        from feature_extractors.sql_analyzer import SQLFeatureExtractor
        
        updates = {}
        success_flag = False
        skipped_flag = False
        error_msg = None
        
        if any(r.get("success", False) for r in results.values()):
            success_flag = True
            for method_name, result in results.items():
                if result.get("success", False):
                    prefix = method_name
                    updates[f"{prefix}_execution_time"] = result.get("execution_time")
                    updates[f"{prefix}_memory_usage"] = result.get("memory_usage")
                    updates[f"{prefix}_transpiled_depth"] = result.get("transpiled_circuit_depth")
                    updates[f"{prefix}_transpiled_size"] = result.get("transpiled_circuit_size")
                    updates[f"{prefix}_gate_counts"] = result.get("transpiled_gate_counts")
                    
                    data = result.get("data", {})
                    if "entropy" in data:
                        updates[f"{prefix}_entropy"] = data["entropy"]
                    if result.get("method") == "automatic":
                        updates["automatic_method"] = data["actual_method"]
                    
                    # Handle InfiniQuantumSim results
                    if method_name == "infiniquantum":
                        if "benchmark_results" in result:
                            for bench_method, bench_data in result["benchmark_results"].items():
                                if isinstance(bench_data, dict):
                                    if "memory_avg_mb" in bench_data:
                                        updates[f"rdbms_{bench_method}_memory_mb"] = bench_data["memory_avg_mb"]
                                    if "time_avg_s" in bench_data:
                                        updates[f"rdbms_{bench_method}_time_s"] = bench_data["time_avg_s"]
                        
                        # Extract SQL Features
                        if "sql_query" in result:
                            try:
                                sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(result["sql_query"])
                                for feat_name, count in sql_features.items():
                                    updates[f"infinidata_quantum_sql_{feat_name}"] = count
                                updates[f"infinidata_quantum_sql_num_joins"] = len(join_edges)
                            except Exception as e:
                                logger.error(f"Failed to extract SQL features: {e}")
        
        elif any(r.get("skipped", False) for r in results.values()):
            skipped_flag = True
            error_msg = "Simulations skipped"
        else:
            error_msg = "All simulations failed"
        
        return success_flag, skipped_flag, error_msg, updates
    
    def _process_rdbms_result(self, result: dict) -> tuple:
        """Process results from RDBMS mode"""
        from feature_extractors.sql_analyzer import SQLFeatureExtractor
        
        updates = {}
        success_flag = False
        skipped_flag = False
        error_msg = None
        
        if result.get("success", False):
            success_flag = True
            updates["rdbms_execution_time"] = result.get("execution_time")
            
            if "benchmark_results" in result:
                for bench_method, bench_data in result["benchmark_results"].items():
                    if isinstance(bench_data, dict):
                        if "memory_avg_mb" in bench_data:
                            updates[f"rdbms_{bench_method}_memory_mb"] = bench_data["memory_avg_mb"]
                        if "time_avg_s" in bench_data:
                            updates[f"rdbms_{bench_method}_time_s"] = bench_data["time_avg_s"]
            
            # Extract SQL Features
            if "sql_query" in result:
                try:
                    sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(result["sql_query"])
                    for feat_name, count in sql_features.items():
                        updates[f"infinidata_quantum_sql_{feat_name}"] = count
                    updates[f"infinidata_quantum_sql_num_joins"] = len(join_edges)
                except Exception as e:
                    logger.error(f"Failed to extract SQL features: {e}")
        
        elif result.get("skipped"):
            skipped_flag = True
            error_msg = result.get("error")
        else:
            error_msg = result.get("error")
        
        return success_flag, skipped_flag, error_msg, updates


class SQLFeatureProcessor(CircuitProcessor):
    """Processes circuits to extract SQL features only"""
    
    def __init__(self, min_qubits=None, max_qubits=None, min_depth=None, max_depth=None):
        """
        Initialize SQL feature processor.
        
        Args:
            min_qubits: Minimum qubit count to process (None = no limit)
            max_qubits: Maximum qubit count to process (None = no limit)
            min_depth: Minimum circuit depth to process (None = no limit)
            max_depth: Maximum circuit depth to process (None = no limit)
        """
        self.min_qubits = min_qubits
        self.max_qubits = max_qubits
        self.min_depth = min_depth
        self.max_depth = max_depth

    def process_circuit_file(self, file_path: str) -> dict:
        """
        Process a circuit file to extract SQL features.
        
        Args:
            file_path: Path to circuit file
            
        Returns:
            Dictionary with processing results
        """
        try:
            qc, circuit_hash, _ = self.load_circuit_from_file(file_path)
            
            # Check circuit size limits
            if self.min_qubits is not None and qc.num_qubits < self.min_qubits:
                logger.debug(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits below limit of {self.min_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, below limit of {self.min_qubits}",
                    "file_path": file_path,
                }

            if self.max_qubits is not None and qc.num_qubits > self.max_qubits:
                logger.debug(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits exceeds limit of {self.max_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, exceeds limit of {self.max_qubits}",
                    "file_path": file_path,
                }
            
            circuit_depth = qc.depth()
            if self.min_depth is not None and circuit_depth < self.min_depth:
                logger.debug(f"Skipping circuit {circuit_hash}: depth {circuit_depth} below limit of {self.min_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {circuit_depth} below limit of {self.min_depth}",
                    "file_path": file_path,
                }

            if self.max_depth is not None and circuit_depth > self.max_depth:
                logger.debug(f"Skipping circuit {circuit_hash}: depth {circuit_depth} exceeds limit of {self.max_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {circuit_depth} exceeds limit of {self.max_depth}",
                    "file_path": file_path,
                }

            logger.info(f"Extracting SQL features for circuit {circuit_hash}")
            
            result = self._extract_sql_features(qc, circuit_hash)
            result["file_path"] = file_path
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {
                "hash": None,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e),
                "file_path": file_path,
            }
    
    def _extract_sql_features(self, qc, circuit_hash: str) -> dict:
        """Extract SQL features from a quantum circuit"""
        from feature_extractors.sql_analyzer import SQLFeatureExtractor
        
        try:
            if not INFINI_QUANTUM_AVAILABLE:
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": False,
                    "updates": {},
                    "error": "InfiniQuantumSim not installed"
                }
            
            # Transpile to ensure we only have 1 and 2 qubit gates
            transpiled_qc = transpile(qc, basis_gates=['u', 'cx', 'id', 'rz', 'sx', 'x'], optimization_level=2)
            num_qubits = transpiled_qc.num_qubits
            
            # Check if circuit is too large
            estimated_indices = num_qubits + 3 * len(transpiled_qc.data)
            if estimated_indices >= len(INDICES):
                logger.warning(f"Skipping {circuit_hash}: Circuit too large (indices limit)")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": "Circuit too large for InfiniQuantumSim"
                }
            
            # Create IQS circuit
            iqs_qc = IQSQuantumCircuit(num_qubits=num_qubits)
            
            # Add gates to IQS circuit
            for instruction in transpiled_qc.data:
                op = instruction.operation
                qubits = [transpiled_qc.find_bit(q).index for q in instruction.qubits]
                
                if op.name in ['barrier', 'measure']:
                    continue
                
                matrix = op.to_matrix()
                
                if len(qubits) == 1:
                    tensor = matrix
                elif len(qubits) == 2:
                    tensor = matrix.reshape(2, 2, 2, 2)
                else:
                    raise ValueError(f"Unsupported operation {op.name} on {len(qubits)} qubits")
                
                gate_name = f"{op.name}_{id(op)}" if len(op.params) > 0 else op.name
                gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
                iqs_qc.add_gate(gate)
            
            # Generate SQL query and extract features
            sql_query = iqs_qc.to_query()
            sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(sql_query)
            
            # Prepare updates
            updates = {}
            for feat_name, count in sql_features.items():
                updates[f"infinidata_quantum_sql_{feat_name}"] = count
            updates["infinidata_quantum_sql_num_joins"] = len(join_edges)
            
            return {
                "hash": circuit_hash,
                "success": True,
                "skipped": False,
                "updates": updates,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Failed to extract SQL features for {circuit_hash}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {
                "hash": circuit_hash,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e)
            }


class DynamicFeatureProcessor(CircuitProcessor):
    """Processes circuits to extract dynamic features using statevector simulation"""
    
    def __init__(self, simulator, max_qubits=None, max_depth=None):
        """
        Initialize with a QuantumSimulator instance.
        
        Args:
            simulator: Initialized QuantumSimulator
            max_qubits: Maximum qubit count to process (None = no limit)
            max_depth: Maximum circuit depth to process (None = no limit)
        """
        self.simulator = simulator
        self.max_qubits = max_qubits
        self.max_depth = max_depth
    
    def process_circuit_file(self, file_path: str) -> dict:
        """
        Process a circuit file to extract dynamic features.
        
        Args:
            file_path: Path to circuit file
            
        Returns:
            Dictionary with processing results
        """
        try:
            qc, circuit_hash, _ = self.load_circuit_from_file(file_path)
            
            updates = {}
            success_flag = False
            skipped_flag = False
            error_msg = None
            
            logger.info(f"Processing dynamic features for circuit {circuit_hash}")
            
            # Check circuit size limits
            if self.max_qubits is not None and qc.num_qubits > self.max_qubits:
                logger.info(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits exceeds limit of {self.max_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, exceeds limit of {self.max_qubits}",
                    "file_path": file_path,
                }
            
            if self.max_depth is not None and qc.depth() > self.max_depth:
                logger.info(f"Skipping circuit {circuit_hash}: depth {qc.depth()} exceeds limit of {self.max_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {qc.depth()} exceeds limit of {self.max_depth}",
                    "file_path": file_path,
                }
            
            # Run statevector simulation with save_statevector to extract dynamic features
            from simulators.lib.types import SimulationMethod
            
            qc_copy = qc.copy()
            qc_copy.save_statevector()
            result = self.simulator._run_simulation(qc_copy, SimulationMethod.STATEVECTOR)
            
            if result.get("success"):
                success_flag = True
                data = result.get("data", {})
                
                # Extract dynamic features
                updates = {}
                if "shannon_entropy" in data:
                    updates["statevector_saved_shannon_entropy"] = data["shannon_entropy"]
                if "von_neumann_entropy" in data:
                    updates["statevector_saved_von_neumann_entropy"] = data["von_neumann_entropy"]
                if "sparsity" in data:
                    updates["statevector_saved_sparsity"] = data["sparsity"]
                
                logger.info(f"Dynamic features extracted - "
                           f"Entropy: {data.get('shannon_entropy', 0):.4f}, "
                           f"Sparsity: {data.get('sparsity', 0):.4f}")
                           
            elif result.get("skipped"):
                skipped_flag = True
                error_msg = result.get("error")
                logger.info(f"Dynamic feature extraction skipped: {error_msg}")
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"Dynamic feature extraction failed: {error_msg}")
            
            return {
                "hash": circuit_hash,
                "success": success_flag,
                "skipped": skipped_flag,
                "updates": updates,
                "error": error_msg,
                "file_path": file_path,
            }
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {
                "hash": None,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e),
                "file_path": file_path,
            }
