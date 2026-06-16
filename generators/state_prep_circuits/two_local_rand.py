# Import necessary Qiskit components
from qiskit.circuit.library import TwoLocal as QiskitTwoLocal
from qiskit.circuit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import num_qbits, reps, random_parameter_values
import random


class TwoLocal(Generator):
    """
    Class to generate a TwoLocal variational form circuit with random parameters.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        num_qubits: int,
        circuit_reps: int,
        parameter_values: list[float],
        rotation_blocks: list[str] = None,
        entanglement_blocks: list[str] = None,
        entanglement: str = "full",
        skip_final_rotation_layer: bool = False,
    ) -> QuantumCircuit:
        """
        Creates and completes a TwoLocal Qiskit circuit with the provided parameters.

        This function first builds the parameterized TwoLocal circuit structure
        and then assigns the given numerical parameter values to it, resulting
        in a fully defined quantum circuit.

        Args:
            num_qubits (int): The number of qubits in the circuit.
            circuit_reps (int): The number of repetitions (layers) of the ansatz.
            parameter_values (list[float]): A list of numerical values to bind to the
                                            circuit's parameters. The length of this list
                                            must match the number of parameters expected
                                            by the TwoLocal circuit.
            rotation_blocks (list[str], optional): A list of gate names (e.g., ['ry', 'rz'])
                                                   to use for the rotation layers.
                                                   Defaults to ['ry', 'rz'] if None.
            entanglement_blocks (list[str], optional): A list of gate names (e.g., ['cx'])
                                                      to use for the entanglement layers.
                                                      Defaults to ['cx'] if None.
            entanglement (str): Specifies the entanglement pattern. Common options include
                                'full', 'linear', 'circular', or a list of qubit pairs.
                                Defaults to 'full'.
            skip_final_rotation_layer (bool): If True, the last rotation layer is omitted.
                                              Defaults to False.

        Returns:
            QuantumCircuit: A Qiskit QuantumCircuit with all its parameters bound to
                            the provided numerical values. Returns None if parameter
                            count does not match.
        """
        if rotation_blocks is None:
            rotation_blocks = ["ry", "rz"]
        if entanglement_blocks is None:
            entanglement_blocks = ["cx"]

        # Create the TwoLocal ansatz circuit
        ansatz = QiskitTwoLocal(
            num_qubits=num_qubits,
            reps=circuit_reps,
            rotation_blocks=rotation_blocks,
            entanglement_blocks=entanglement_blocks,
            entanglement=entanglement,
            skip_final_rotation_layer=skip_final_rotation_layer,
        )

        # Check if the provided parameter_values match the number of expected parameters
        expected_params = len(ansatz.parameters)
        if len(parameter_values) != expected_params:
            print(
                f"Error: Mismatch in parameter count. Expected {expected_params} parameters, "
                f"but got {len(parameter_values)} values."
            )
            return None

        # Assign the numerical values to the parameters
        completed_circuit = ansatz.assign_parameters(parameter_values)
        completed_circuit.name = f"TwoLocal({num_qubits}q,{circuit_reps}r)"

        if self.measure:
            completed_circuit.measure_all()

        return completed_circuit.decompose()

    def generate_parameters(
        self,
    ) -> tuple[int, int, list[float], list[str], list[str], str, bool]:
        """
        Generate parameters for the TwoLocal circuit.

        Returns:
            tuple: (num_qubits, circuit_reps, parameter_values, rotation_blocks,
                   entanglement_blocks, entanglement, skip_final_rotation_layer)
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.circuit_reps = reps(
            self.base_params.min_reps,
            self.base_params.max_reps,
            self.base_params.seed,
        )

        # Generate random rotation and entanglement blocks
        rotation_options = [
            ["ry"],
            ["rz"],
            ["rx"],
            ["ry", "rz"],
            ["rx", "ry"],
            ["rx", "rz"],
        ]
        entanglement_options = [["cx"], ["cz"], ["cy"]]
        entanglement_patterns = ["full", "linear", "circular"]

        # Use current random state set by CircuitMerger instead of resetting seed
        # This ensures reproducibility while maintaining proper random sequence
        self.rotation_blocks = random.choice(rotation_options)
        self.entanglement_blocks = random.choice(entanglement_options)
        self.entanglement = random.choice(entanglement_patterns)
        self.skip_final_rotation_layer = random.choice([True, False])

        # Create a temporary circuit to count parameters
        temp_ansatz = QiskitTwoLocal(
            num_qubits=self.num_qubits,
            reps=self.circuit_reps,
            rotation_blocks=self.rotation_blocks,
            entanglement_blocks=self.entanglement_blocks,
            entanglement=self.entanglement,
            skip_final_rotation_layer=self.skip_final_rotation_layer,
        )

        num_params = len(temp_ansatz.parameters)
        self.parameter_values = random_parameter_values(
            num_params, seed=self.base_params.seed
        )

        self.measure = self.base_params.measure

        return (
            self.num_qubits,
            self.circuit_reps,
            self.parameter_values,
            self.rotation_blocks,
            self.entanglement_blocks,
            self.entanglement,
            self.skip_final_rotation_layer,
        )


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=4,
        min_qubits=2,
        max_depth=3,
        min_depth=1,
        min_reps=1,
        max_reps=3,
        measure=False,
        seed=42,
    )

    two_local_generator = TwoLocal(params)
    (
        num_qubits,
        circuit_reps,
        parameter_values,
        rotation_blocks,
        entanglement_blocks,
        entanglement,
        skip_final,
    ) = two_local_generator.generate_parameters()

    print("Generated parameters:")
    print(f"  - Number of qubits: {num_qubits}")
    print(f"  - Circuit repetitions: {circuit_reps}")
    print(f"  - Rotation blocks: {rotation_blocks}")
    print(f"  - Entanglement blocks: {entanglement_blocks}")
    print(f"  - Entanglement pattern: {entanglement}")
    print(f"  - Skip final rotation: {skip_final}")
    print(f"  - Number of parameters: {len(parameter_values)}")
    print(
        f"  - Parameter values: {parameter_values[:5]}..."
        if len(parameter_values) > 5
        else f"  - Parameter values: {parameter_values}"
    )

    two_local_circuit = two_local_generator.generate(
        num_qubits,
        circuit_reps,
        parameter_values,
        rotation_blocks,
        entanglement_blocks,
        entanglement,
        skip_final,
    )
    print("\nGenerated circuit:")
    print(two_local_circuit)
