from qiskit import QuantumCircuit, QuantumRegister
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import num_qbits
import numpy as np


class WState(Generator):
    """
    Class to generate a W-state quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(self, num_qubits: int) -> QuantumCircuit:
        """
        Create an n-qubit W state:
        |W⟩ = (|100...0⟩ + |010...0⟩ + ... + |000...1⟩)/√n

        Args:
            num_qubits (int): Number of qubits for the W state

        Returns:
            QuantumCircuit: The generated W state circuit
        """
        q = QuantumRegister(num_qubits, "q")
        qc = QuantumCircuit(q, name=f"WState({num_qubits})")

        # Helper function for the f_gate used in W state construction
        def f_gate(
            qc: QuantumCircuit, q: QuantumRegister, i: int, j: int, n: int, k: int
        ) -> None:
            theta = np.arccos(np.sqrt(1 / (n - k + 1)))
            qc.ry(-theta, q[j])
            qc.cz(q[i], q[j])
            qc.ry(theta, q[j])

        # W state construction using MQT bench approach
        qc.x(q[-1])

        for m in range(1, num_qubits):
            f_gate(qc, q, num_qubits - m, num_qubits - m - 1, num_qubits, m)

        for k in reversed(range(1, num_qubits)):
            qc.cx(k - 1, k)

        if self.measure:
            qc.measure_all()

        return qc

    def generate_parameters(self) -> int:
        """
        Generate parameters for the W state circuit.

        Returns:
            int: Number of qubits for the W state
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )
        self.measure = self.base_params.measure
        return self.num_qubits


# Backward compatible function
def generate(n):
    """
    Backward-compatible function to generate a W state circuit.

    Args:
        n (int): Number of qubits for the W state

    Returns:
        QuantumCircuit: The generated W state circuit
    """
    params = BaseParams(
        max_qubits=n, min_qubits=n, max_depth=1, min_depth=1, measure=False
    )
    wstate_generator = WState(params)
    return wstate_generator.generate(n)


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=3, max_depth=10, min_depth=1, measure=False, seed=42
    )

    wstate_generator = WState(params)
    num_qubits = wstate_generator.generate_parameters()
    wstate_circuit = wstate_generator.generate(num_qubits)

    print("Generated parameters:")
    print(f"  - Number of qubits: {num_qubits}")

    print("\nGenerated circuit:")
    print(wstate_circuit)
