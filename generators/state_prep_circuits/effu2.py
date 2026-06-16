from qiskit.circuit.library import efficient_su2
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import num_qbits, reps, entanglement_pattern


class EfficientU2(Generator):
    """
    Class to generate an efficient SU(2) circuit.
    """

    def __init__(self, base_params):
        self.base_params = base_params

    def generate(self, num_qubits, entanglement, reps):
        """Generate an efficient SU(2) circuit."""
        qc = efficient_su2(num_qubits=num_qubits, entanglement=entanglement, reps=reps)
        qc.name = "efficientU2"
        return qc

    def generate_parameters(self):
        """
        Generate parameters for the efficient SU(2) circuit.
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )
        self.entanglement = entanglement_pattern(
            self.num_qubits,
            self.base_params.seed,
        )
        self.reps = reps(
            self.base_params.min_reps,
            self.base_params.max_reps,
            self.base_params.seed,
        )
        return self.num_qubits, self.entanglement, self.reps


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=2, max_depth=10, min_depth=1, measure=False
    )
    efficient_u2_generator = EfficientU2(params)
    num_qubits, entanglement, reps = efficient_u2_generator.generate_parameters()
    efficient_u2_circuit = efficient_u2_generator.generate(
        num_qubits, entanglement, reps
    )
    print(efficient_u2_circuit)
