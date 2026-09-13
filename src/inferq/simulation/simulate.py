import logging
import time
import tracemalloc
from typing import Any

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from .dynamic_feature_extractor import DynamicFeatureExtractor
from .infiniquantum import INFINI_QUANTUM_AVAILABLE, _execute_infiniquantum_simulation
from .types import SimulationMethod

logger = logging.getLogger(__name__)

class QuantumSimulator(DynamicFeatureExtractor):
    """
    A comprehensive quantum circuit simulator supporting multiple simulation methods.

    This class provides a unified interface for simulating quantum circuits using
    different backends available in Qiskit, including statevector, MPS, unitary,
    density matrix, stabilizer, and extended stabilizer simulations.
    """

    def __init__(
        self,
        shots: int | None = None,
        seed: int | None = None,
        timeout_seconds: int | None = None,
        device: str = "CPU",
        infiniquantum_config: dict[str, Any] | None = None,
    ):
        """
        Initialize the quantum simulator.
        
        Args:
            shots: Number of shots for sampling-based simulations
            seed: Random seed for reproducible results
            timeout_seconds: Maximum time allowed for simulation (in seconds)
            device: Device to run simulations on ("CPU" or "GPU")
            infiniquantum_config: Configuration for InfiniQuantumSim
        """
        self.shots = shots
        self.seed = seed
        self.timeout_seconds = timeout_seconds
        self.device = device
        self.infiniquantum_config = infiniquantum_config or {}
        self.simulators = {}
        self._initialize_simulators()

    def _initialize_simulators(self):
        """Initialize all available simulators"""
        # Methods that explicitly support GPU
        gpu_methods = {
            SimulationMethod.STATEVECTOR,
            SimulationMethod.DENSITY_MATRIX,
            SimulationMethod.UNITARY,
            SimulationMethod.AUTOMATIC,
        }

        try:
            for method in SimulationMethod:
                if method == SimulationMethod.INFINI_QUANTUM:
                    continue

                # Determine device for this specific method
                method_device = "CPU"
                if self.device == "GPU" and method in gpu_methods:
                    method_device = "GPU"

                self.simulators[method] = AerSimulator(
                    method=method.value,
                    shots=self.shots,
                    seed_simulator=self.seed,
                    device=method_device,
                )
                logger.debug(
                    f"Initialized simulator for method {method.value} on device {method_device}"
                )
            
            if INFINI_QUANTUM_AVAILABLE:
                self.simulators[SimulationMethod.INFINI_QUANTUM] = "InfiniQuantumSim"
                logger.info("Initialized InfiniQuantumSim simulator")

        except Exception as e:
            logger.error(f"Error initializing simulators: {e}")
            raise

    def simulate_statevector(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.STATEVECTOR, **kwargs)
    
    def simulate_mps(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.MPS, **kwargs)

    def simulate_unitary(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.UNITARY, **kwargs)

    def simulate_density_matrix(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.DENSITY_MATRIX, **kwargs)

    def simulate_stabilizer(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.STABILIZER, **kwargs)

    def simulate_extended_stabilizer(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.EXTENDED_STABILIZER, **kwargs)

    def simulate_auto(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        return self._run_simulation(qc, SimulationMethod.AUTOMATIC, **kwargs)

    def simulate_all_methods(
        self, qc: QuantumCircuit, **kwargs
    ) -> dict[str, dict[str, Any]]:
        """
        Simulate the circuit using all available methods with size limits.
        """
        logger.info(
            f"Starting simulation for circuit: {qc.num_qubits} qubits, depth {qc.depth()}, size {qc.size()}"
        )
        results = {}
        successful_methods = 0
        failed_methods = 0

        # Get simulation limits from config
        from inferq.config import get_simulation_config

        # Indexed, not .get()-with-default: get_simulation_config() always supplies
        # these keys, and the old inline defaults had drifted out of step with it.
        sim_config = get_simulation_config()
        max_qubits_statevector = sim_config["max_qubits_statevector"]
        max_qubits_unitary = sim_config["max_qubits_unitary"]
        max_qubits_mps = sim_config["max_qubits_mps"]
        max_circuit_size = sim_config["max_circuit_size"]

        # Check overall circuit complexity
        if qc.size() > max_circuit_size:
            logger.warning(
                f"Circuit too complex for simulation: {qc.size()} gates > {max_circuit_size} limit"
            )
            failed_result = {
                "success": False,
                "error": f"Circuit too complex: {qc.size()} gates exceeds simulation limit of {max_circuit_size}",
                "skipped": True,
            }
            return {
                method.value: {**failed_result, "method": method.value}
                for method in SimulationMethod
            }

        for method in SimulationMethod:
            try:
                # Check qubit limits before attempting simulation
                skip_reason = None
                if (
                    method == SimulationMethod.STATEVECTOR
                    and qc.num_qubits > max_qubits_statevector
                ):
                    skip_reason = f"Circuit has {qc.num_qubits} qubits, exceeds statevector limit of {max_qubits_statevector}"
                elif (
                    method
                    in [SimulationMethod.UNITARY, SimulationMethod.DENSITY_MATRIX]
                    and qc.num_qubits > max_qubits_unitary
                ):
                    skip_reason = f"Circuit has {qc.num_qubits} qubits, exceeds {method.value} limit of {max_qubits_unitary}"
                elif method == SimulationMethod.MPS and qc.num_qubits > max_qubits_mps:
                    skip_reason = f"Circuit has {qc.num_qubits} qubits, exceeds MPS limit of {max_qubits_mps}"

                if skip_reason:
                    failed_methods += 1
                    results[method.value] = {
                        "success": False,
                        "error": skip_reason,
                        "method": method.value,
                        "skipped": True,
                    }
                    continue

                logger.debug(f"Attempting {method.value} simulation...")
                result = self._run_simulation(qc, method, **kwargs)
                results[method.value] = result

                if result.get("success", False):
                    successful_methods += 1
                    logger.debug(f"✓ {method.value} simulation completed successfully")
                else:
                    failed_methods += 1
                    logger.warning(
                        f"✗ {method.value} simulation failed: {result.get('error', 'Unknown error')}"
                    )

            except Exception as e:
                failed_methods += 1
                logger.warning(
                    f"✗ {method.value} simulation failed with exception: {e}"
                )
                results[method.value] = {
                    "success": False,
                    "error": str(e),
                    "method": method.value,
                }

        # Add additional statevector simulation with save_statevector for entropy/sparsity calculations
        if (
            SimulationMethod.STATEVECTOR in self.simulators
            and qc.num_qubits <= max_qubits_statevector
        ):
            try:
                logger.debug("Attempting statevector_saved simulation...")
                qc_copy = qc.copy()  # Don't modify original circuit
                qc_copy.save_statevector()
                result = self._run_simulation(
                    qc_copy, SimulationMethod.STATEVECTOR, **kwargs
                )
                results["statevector_saved"] = result

                if result.get("success", False):
                    successful_methods += 1
                    logger.debug("✓ statevector_saved simulation completed successfully")
                else:
                    failed_methods += 1
                    logger.warning(
                        f"✗ statevector_saved simulation failed: {result.get('error', 'Unknown error')}"
                    )

            except Exception as e:
                failed_methods += 1
                logger.warning(
                    f"✗ statevector_saved simulation failed with exception: {e}"
                )
                results["statevector_saved"] = {
                    "success": False,
                    "error": str(e),
                    "method": "statevector_saved",
                }
        elif qc.num_qubits > max_qubits_statevector:
            failed_methods += 1
            results["statevector_saved"] = {
                "success": False,
                "error": f"Circuit has {qc.num_qubits} qubits, exceeds statevector limit of {max_qubits_statevector}",
                "method": "statevector_saved",
                "skipped": True,
            }

        logger.info(
            f"Simulation summary: {successful_methods} successful, {failed_methods} failed out of {len(SimulationMethod) + 1} methods"
        )
        return results

    def _run_simulation(
        self, qc: QuantumCircuit, method: SimulationMethod, **kwargs
    ) -> dict[str, Any]:
        """
        Internal method to run simulation with specified method.
        """
        if method == SimulationMethod.INFINI_QUANTUM:
            return self._run_infiniquantum_simulation(qc, **kwargs)

        try:
            simulator = self.simulators[method]

            circuit_to_simulate = qc

            transpiled_qc = transpile(circuit_to_simulate, simulator)

            tracemalloc.start()
            tracemalloc.clear_traces()
            mem_tic, _ = tracemalloc.get_traced_memory()

            start_time = time.time()
            mem_toc = 0

            try:
                job = simulator.run(transpiled_qc, **kwargs)
                result = job.result(timeout=self.timeout_seconds)
                end_time = time.time()
                measured_execution_time = end_time - start_time
            except Exception as timeout_error:
                end_time = time.time()
                measured_execution_time = end_time - start_time
                if (
                    "timeout" in str(timeout_error).lower()
                    or measured_execution_time >= self.timeout_seconds
                ):
                    timeout_msg = f"Simulation timed out after {measured_execution_time:.1f}s (limit: {self.timeout_seconds}s)"
                    logger.warning(f"✗ {method.value} {timeout_msg}")
                    return {
                        "success": False,
                        "method": method.value,
                        "error": timeout_msg,
                        "execution_time": measured_execution_time,
                        "skipped": True,
                    }
                else:
                    raise timeout_error
            finally:
                _, mem_toc = tracemalloc.get_traced_memory()
                tracemalloc.stop()

            measured_memory_mb = (mem_toc - mem_tic) / (1024 * 1024)

            simulation_data = self._extract_simulation_data(
                result, method, transpiled_qc
            )

            has_extraction_error = "extraction_error" in simulation_data
            success = not has_extraction_error

            execution_time = getattr(
                result,
                "time_taken",
                simulation_data.get("execution_time", measured_execution_time),
            )
            memory_usage = (
                measured_memory_mb
                if measured_memory_mb > 0
                else getattr(
                    result, "memory_usage", simulation_data.get("memory_usage")
                )
            )

            gate_counts = {}
            for instruction in transpiled_qc.data:
                gate_name = instruction.operation.name
                gate_counts[gate_name] = gate_counts.get(gate_name, 0) + 1

            return {
                "success": success,
                "method": method.value,
                "data": simulation_data,
                "execution_time": execution_time,
                "memory_usage": memory_usage,
                "transpiled_circuit_depth": transpiled_qc.depth(),
                "transpiled_circuit_size": transpiled_qc.size(),
                "transpiled_num_qubits": transpiled_qc.num_qubits,
                "transpiled_num_clbits": transpiled_qc.num_clbits,
                "transpiled_gate_counts": gate_counts,
                "extraction_error": (
                    simulation_data.get("extraction_error")
                    if has_extraction_error
                    else None
                ),
            }

        except Exception as e:
            logger.error(f"Simulation failed for method {method.value}: {e}")
            return {"success": False, "method": method.value, "error": str(e)}

    def _run_infiniquantum_simulation(self, qc: QuantumCircuit, **kwargs) -> dict[str, Any]:
        """
        Run simulation using InfiniQuantumSim benchmark.
        """
        # Inject configuration
        if self.infiniquantum_config:
            if "oom" not in kwargs and "omit_methods" in self.infiniquantum_config:
                kwargs["oom"] = self.infiniquantum_config["omit_methods"]
            if "n_runs" not in kwargs:
                kwargs["n_runs"] = self.infiniquantum_config.get("n_runs", 1)
            if "run_benchmark" not in kwargs:
                kwargs["run_benchmark"] = self.infiniquantum_config.get("run_benchmark", True)
            if "query_mode" not in kwargs:
                kwargs["query_mode"] = self.infiniquantum_config.get("query_mode", "monolithic")

        if self.timeout_seconds:
            kwargs["timeout"] = self.timeout_seconds

        return _execute_infiniquantum_simulation(qc, **kwargs)
    
    def get_available_methods(self) -> list:
        return [method.value for method in SimulationMethod]

    def get_simulator_info(self, method: SimulationMethod) -> dict[str, Any]:
        if method not in self.simulators:
            return {"error": f"Method {method.value} not available"}

        if method == SimulationMethod.INFINI_QUANTUM:
            return {
                "method": method.value,
                "name": "InfiniQuantumSim",
                "version": "0.1.0",
                "configuration": {"device": "CPU"}
            }

        simulator = self.simulators[method]
        return {
            "method": method.value,
            "name": simulator.name,
            "version": getattr(simulator, "version", "unknown"),
            "configuration": simulator.configuration().to_dict(),
            "properties": getattr(simulator, "properties", lambda: None)(),
        }
