from dataclasses import dataclass


@dataclass
class SimulationMetrics:
    """Data class for storing simulation metrics."""
    method: str
    success: bool
    execution_time: float | None = None
    memory_usage: float | None = None
    circuit_depth: int | None = None
    circuit_size: int | None = None
    num_qubits: int | None = None
    shannon_entropy: float | None = None
    von_neumann_entropy: list[float] | None = None
    sparsity: float | None = None
    error_message: str | None = None
    actual_method: str | None = None
