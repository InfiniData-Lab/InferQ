from dataclasses import dataclass
from typing import Optional, List

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
    shannon_entropy: Optional[float] = None
    von_neumann_entropy: Optional[List[float]] = None
    sparsity: Optional[float] = None
    error_message: Optional[str] = None
    actual_method: Optional[str] = None
