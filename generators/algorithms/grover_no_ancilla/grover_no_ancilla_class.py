"""
Class-based wrapper for Grover no-ancilla algorithm
"""

from qiskit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    grover_target_bitstring,
    depth
)
from generators.algorithms.grover_no_ancilla.grover_no_ancilla import generate
from typing import Optional


class GroverNoAncilla(Generator):
    """
    Class to generate a Grover search circuit without ancilla qubits.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        # Grover can optionally measure, depending on use case
        self.measure = self.base_params.measure

    def generate(
        self,
        n: int,
        target: str,
        iterations: int,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a Grover search circuit using the class-based approach.

        Args:
            n (int): Number of qubits (search space size).
            target (str): Target bitstring to search for.
            iterations (int): Number of Grover iterations.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated Grover search circuit.
        """
        # Use the original generate function for the actual circuit construction
        qc = generate(
            n=n,
            target=target,
            iterations=iterations,
            name=name or f"GroverNoAncilla({n}q,{iterations}iter,{target})",
            measure=self.measure,
        )

        return qc

    def generate_parameters(self) -> tuple[int, str, int]:
        """
        Generate parameters for the Grover no-ancilla circuit.

        Returns:
            tuple: (n_qubits, target_bitstring, iterations)
        """
        # Limit to 8 qubits for no-ancilla version
        max_qubits = min(self.base_params.max_qubits, 8)
        min_qubits = max(self.base_params.min_qubits, 1)

        self.n_qubits = num_qbits(
            min_qubits,
            max_qubits,
            self.base_params.seed,
        )

        self.target_bitstring = grover_target_bitstring(
            self.n_qubits, seed=self.base_params.seed
        )

        self.iterations = depth(self.base_params.min_depth,self.base_params.max_depth,self.base_params.seed)

        return self.n_qubits, self.target_bitstring, self.iterations


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=6, min_qubits=3, max_depth=5, min_depth=1, measure=True, seed=42
    )

    grover_generator = GroverNoAncilla(params)
    n_qubits, target, iterations = grover_generator.generate_parameters()

    print("Generated parameters:")
    print(f"  - Number of qubits: {n_qubits}")
    print(f"  - Target bitstring: {target}")
    print(f"  - Grover iterations: {iterations}")

    grover_circuit = grover_generator.generate(n_qubits, target, iterations)
    print(f"\nGenerated circuit: {grover_circuit.name}")
    print(f"Total qubits: {grover_circuit.num_qubits}")
    print(f"Classical registers: {len(grover_circuit.cregs)}")
    print(f"Algorithm metadata: {grover_circuit.metadata['algorithm']}")
