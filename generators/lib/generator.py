from abc import ABC
from dataclasses import dataclass
from qiskit import QuantumCircuit
from config import get_circuit_config

@dataclass
class BaseParams:
    max_qubits: int = None
    min_qubits: int = None
    max_depth: int = None
    min_depth: int = None
    min_reps: int = None
    max_reps: int = None
    min_eval_qubits: int = None
    max_eval_qubits: int = None
    measure: bool = None
    seed: int = None

    def __post_init__(self):
        """
        Load defaults from central config if not provided.
        """
        config = get_circuit_config()
        
        if self.max_qubits is None: self.max_qubits = config["max_qubits"]
        if self.min_qubits is None: self.min_qubits = config["min_qubits"]
        if self.max_depth is None: self.max_depth = config["max_depth"]
        if self.min_depth is None: self.min_depth = config["min_depth"]
        if self.min_reps is None: self.min_reps = config["min_reps"]
        if self.max_reps is None: self.max_reps = config["max_reps"]
        if self.min_eval_qubits is None: self.min_eval_qubits = config["min_eval_qubits"]
        if self.max_eval_qubits is None: self.max_eval_qubits = config["max_eval_qubits"]
        if self.measure is None: self.measure = config["measure"]
        if self.seed is None: self.seed = config["seed"]


class Generator(ABC):
    """
    Abstract base class for generators.
    """

    def __init__(self, base_params: BaseParams):
        """
        Initialize the generator with a configuration.

        :param config: Configuration dictionary for the generator.
        """
        self.base_params = base_params

    def generate(self, *args, **kwargs) -> QuantumCircuit | None:
        """
        Generate content based on the provided arguments.

        :param args: Positional arguments for generation.
        :param kwargs: Keyword arguments for generation.
        :return: Generated content.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def generate_parameters(self) -> tuple:
        """
        Generate parameters for the generator.

        :return: Parameters for the generator.
        """
        raise NotImplementedError("Subclasses must implement this method.")
