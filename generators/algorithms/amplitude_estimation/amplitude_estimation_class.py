"""
Class-based wrapper for Amplitude Estimation algorithm
"""

from qiskit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import evaluation_qubits, demo_theta_value
from generators.algorithms.amplitude_estimation.amplitude_estimation import generate
from typing import Optional


class AmplitudeEstimation(Generator):
    """
    Class to generate an Amplitude Estimation quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = base_params  # Amplitude estimation always requires measurement

    def generate(
        self,
        m: int,
        theta: float,
        state_preparation: Optional[QuantumCircuit] = None,
        grover_operator: Optional[QuantumCircuit] = None,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate an Amplitude Estimation circuit using the class-based approach.

        Args:
            m (int): Number of evaluation qubits.
            theta (float): Demo theta value for single-qubit demo mode.
            state_preparation (Optional[QuantumCircuit]): Custom state preparation circuit.
            grover_operator (Optional[QuantumCircuit]): Custom Grover operator circuit.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated amplitude estimation circuit.
        """
        # Use the original generate function for the actual circuit construction
        qc = generate(
            m=m,
            state_preparation=state_preparation,
            grover_operator=grover_operator,
            theta=theta,
            name=name or f"AmplitudeEstimation({m}eval,θ={theta:.3f})",
        )

        return qc

    def generate_parameters(self) -> tuple[int, float]:
        """
        Generate parameters for the Amplitude Estimation circuit.

        Returns:
            tuple: (m_evaluation_qubits, theta_value)
        """
        self.m_eval_qubits = evaluation_qubits(
            self.base_params.min_eval_qubits,
            self.base_params.max_eval_qubits,
            self.base_params.seed,
        )

        self.theta_value = demo_theta_value(seed=self.base_params.seed)

        return self.m_eval_qubits, self.theta_value


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=3,
        min_qubits=2,
        max_depth=5,
        min_depth=1,
        min_eval_qubits=2,
        max_eval_qubits=4,
        measure=True,
    )

    ae_generator = AmplitudeEstimation(params)
    m_eval, theta = ae_generator.generate_parameters()

    print("Generated parameters:")
    print(f"  - Evaluation qubits: {m_eval}")
    print(f"  - Theta value: {theta:.4f}")

    ae_circuit = ae_generator.generate(m_eval, theta)
    print(ae_circuit)
    print(f"\nGenerated circuit: {ae_circuit.name}")
    print(f"Total qubits: {ae_circuit.num_qubits}")
    print(f"Classical registers: {len(ae_circuit.cregs)}")
