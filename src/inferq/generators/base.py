from abc import ABC, abstractmethod
from dataclasses import dataclass

from qiskit import QuantumCircuit

from inferq.config import get_circuit_config


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
        Load defaults from central config for any field left unset.
        """
        config = get_circuit_config()
        for field_name in self.__dataclass_fields__:
            if getattr(self, field_name) is None:
                setattr(self, field_name, config[field_name])


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

    @abstractmethod
    def generate(self, *args, **kwargs) -> QuantumCircuit | None:
        """
        Generate content based on the provided arguments.

        :param args: Positional arguments for generation.
        :param kwargs: Keyword arguments for generation.
        :return: Generated content.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    def generate_parameters(self) -> tuple:
        """
        Generate parameters for the generator.

        :return: Parameters for the generator.
        """
        raise NotImplementedError("Subclasses must implement this method.")
