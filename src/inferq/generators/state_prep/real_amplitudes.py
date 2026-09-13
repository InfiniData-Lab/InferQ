import random

import numpy as np
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import RealAmplitudes as QiskitRealAmplitudes

from inferq.generators.base import BaseParams, Generator
from inferq.generators.params import depth, num_qbits, random_parameter_values


class RealAmplitudes(Generator):
    """
    Class to generate a RealAmplitudes ansatz circuit with random parameters.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self, num_qubits: int, circuit_depth: int, parameter_values: list[float]
    ) -> QuantumCircuit:
        """
        Creates and completes a RealAmplitudes Qiskit circuit with the provided parameters.

        This function first builds the parameterized RealAmplitudes circuit structure
        and then assigns the given numerical parameter values to it, resulting
        in a fully defined quantum circuit.

        Args:
            num_qubits (int): The number of qubits in the circuit.
            circuit_depth (int): The number of layers (repetitions) of the ansatz.
            parameter_values (list[float]): A list of numerical values to bind to the
                                            circuit's parameters. The length of this list
                                            must match the number of parameters expected
                                            by the RealAmplitudes circuit.

        Returns:
            QuantumCircuit: A Qiskit QuantumCircuit with all its parameters bound to
                            the provided numerical values. Returns None if parameter
                            count does not match.
        """
        # Create the base parameterized RealAmplitudes circuit using Qiskit API
        ansatz_circuit = QiskitRealAmplitudes(num_qubits=num_qubits, reps=circuit_depth)

        # Check if the provided parameter_values match the number of expected parameters
        expected_params = len(ansatz_circuit.parameters)
        if len(parameter_values) != expected_params:
            print(
                f"Error: Mismatch in parameter count. Expected {expected_params} parameters, "
                f"but got {len(parameter_values)} values."
            )
            return None
        # Assign the numerical values to the parameters
        ansatz_circuit.assign_parameters(parameter_values,inplace=True)
        ansatz_circuit.name = f"RealAmplitudes({num_qubits}q,{circuit_depth}d)"

        if self.measure:
            ansatz_circuit.measure_all()

        return ansatz_circuit.decompose()

    def generate_parameters(self) -> tuple[int, int, list[float]]:
        """
        Generate parameters for the RealAmplitudes circuit.

        Returns:
            tuple: (num_qubits, circuit_depth, parameter_values)
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.circuit_depth = depth(
            self.base_params.min_depth,
            self.base_params.max_depth,
            self.base_params.seed,
        )

        # Calculate the number of parameters needed for RealAmplitudes
        # RealAmplitudes with n qubits and d repetitions needs n * (d + 1) parameters
        num_params = self.num_qubits * (self.circuit_depth + 1)

        self.parameter_values = random_parameter_values(
            num_params, seed=self.base_params.seed
        )
        self.measure = self.base_params.measure

        return self.num_qubits, self.circuit_depth, self.parameter_values


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=2, max_depth=3, min_depth=1, measure=False,seed=2
    )
    random.seed(params.seed)
    np.random.seed(params.seed)
    real_amplitudes_generator = RealAmplitudes(params)
    num_qubits, circuit_depth, parameter_values = (
        real_amplitudes_generator.generate_parameters()
    )

    print("Generated parameters:")
    print(f"  - Number of qubits: {num_qubits}")
    print(f"  - Circuit depth: {circuit_depth}")
    print(f"  - Number of parameters: {len(parameter_values)}")
    print(
        f"  - Parameter values: {parameter_values[:5]}..."
        if len(parameter_values) > 5
        else f"  - Parameter values: {parameter_values}"
    )

    real_amplitudes_circuit = real_amplitudes_generator.generate(
        num_qubits, circuit_depth, parameter_values
    )
    print("\nGenerated circuit:")
    print(real_amplitudes_circuit)
