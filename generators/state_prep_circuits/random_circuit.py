from qiskit.circuit.random import random_circuit
from qiskit import QuantumCircuit

from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import num_qbits, depth


class RandomCircuit(Generator):
    """
    Class to generate a random quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(self, width: int, depth: int) -> QuantumCircuit:
        """Generate a random quantum circuit."""
        qc = random_circuit(width, depth * 2, measure=self.measure, seed=10)
        qc.name = f"RandomCircuit{width}x{depth}"
        return qc

    def generate_parameters(self) -> tuple[int, int]:
        """Generate the number of qubits for the random circuit."""
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )
        self.depth = depth(
            self.base_params.min_depth,
            self.base_params.max_depth,
            self.base_params.seed,
        )
        return self.num_qubits, self.depth


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=2, max_depth=10, min_depth=1, measure=False
    )
    random_circuit_generator = RandomCircuit(params)
    num_qubits, depth = random_circuit_generator.generate_parameters()
    random_circuit_circuit = random_circuit_generator.generate(num_qubits, depth)
    print(random_circuit_circuit)
