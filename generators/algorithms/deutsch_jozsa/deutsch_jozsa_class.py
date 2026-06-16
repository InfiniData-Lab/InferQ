"""
Class-based wrapper for Deutsch-Jozsa algorithm
"""

from qiskit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    oracle_type_choice,
    random_bitstring,
    constant_output_choice,
)
from generators.algorithms.deutsch_jozsa.deutsch_jozsa import generate
from typing import Optional


class DeutschJozsa(Generator):
    """
    Class to generate a Deutsch-Jozsa quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = base_params.measure  # Deutsch-Jozsa always requires measurement

    def generate(
        self,
        n: int,
        oracle_type: str = "balanced",
        bitstring: Optional[str] = None,
        constant_output: int = 0,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a Deutsch-Jozsa circuit using the class-based approach.

        Args:
            n (int): Number of input qubits.
            oracle_type (str): Either "balanced" or "constant".
            bitstring (Optional[str]): For balanced oracle, the hidden bitstring.
            constant_output (int): For constant oracle, the output value (0 or 1).
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated Deutsch-Jozsa circuit.
        """
        # Use the original generate function for the actual circuit construction
        qc = generate(
            n=n,
            oracle_type=oracle_type,
            bitstring=bitstring,
            constant_output=constant_output,
            name=name or f"DeutschJozsa({n}q,{oracle_type})",
            measure=self.measure,  # Always measure for Deutsch-Jozsa
        )

        return qc

    def generate_parameters(self) -> tuple[int, str, Optional[str], int]:
        """
        Generate parameters for the Deutsch-Jozsa circuit.

        Returns:
            tuple: (n_qubits, oracle_type, bitstring, constant_output)
        """
        self.n_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.oracle_type = oracle_type_choice(seed=self.base_params.seed)

        if self.oracle_type == "balanced":
            self.bitstring = random_bitstring(self.n_qubits, seed=self.base_params.seed)
            self.constant_output = 0  # Not used for balanced
        else:
            self.bitstring = None  # Not used for constant
            self.constant_output = constant_output_choice(seed=self.base_params.seed)

        return self.n_qubits, self.oracle_type, self.bitstring, self.constant_output


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=2, max_depth=1, min_depth=1, measure=True, seed=42
    )

    dj_generator = DeutschJozsa(params)
    n_qubits, oracle_type, bitstring, constant_output = (
        dj_generator.generate_parameters()
    )

    print("Generated parameters:")
    print(f"  - Number of qubits: {n_qubits}")
    print(f"  - Oracle type: {oracle_type}")
    if oracle_type == "balanced":
        print(f"  - Bitstring: {bitstring}")
    else:
        print(f"  - Constant output: {constant_output}")

    dj_circuit = dj_generator.generate(
        n_qubits, oracle_type, bitstring, constant_output
    )
    print(f"\nGenerated circuit: {dj_circuit.name}")
    print(f"Total qubits: {dj_circuit.num_qubits}")
    print(f"Classical registers: {len(dj_circuit.cregs)}")
    print(f"Metadata: {dj_circuit.metadata}")

    print(dj_circuit)
