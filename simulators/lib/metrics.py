from dataclasses import dataclass
from typing import Optional, Dict, Any

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
    fidelity: Optional[float] = None
    entropy: Optional[float] = None
    purity: Optional[float] = None
    error_message: Optional[str] = None
    actual_method: Optional[str] = None
