"""
Class-based wrapper for Grover V-chain algorithm
"""

from qiskit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    grover_target_bitstring,
    grover_iterations,
    depth
)
from generators.algorithms.grover_v_chain.grover_v_chain import generate
from typing import Optional


class GroverVChain(Generator):
    """
    Class to generate a Grover V-chain quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = base_params.measure  # Grover always requires measurement

    def generate(
        self,
        n: int,
        target: Optional[str] = None,
        iterations: Optional[int] = None,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a Grover V-chain circuit using the class-based approach.

        Args:
            n (int): Number of search qubits (must be ≥ 3).
            target (Optional[str]): Target bitstring to search for.
            iterations (Optional[int]): Number of Grover iterations.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated Grover V-chain circuit.
        """
        # Use the original generate function for the actual circuit construction
        qc = generate(
            n=n,
            target=target,
            iterations=iterations,
            name=name or f"GroverVChain({n}q,{iterations}iter)",
            measure=self.measure,  # Always measure for Grover
        )

        return qc

    def generate_parameters(self) -> tuple[int, str, int]:
        """
        Generate parameters for the Grover V-chain circuit.

        Returns:
            tuple: (n_qubits, target_bitstring, iterations)
        """
        self.n_qubits = num_qbits(
            max(3, self.base_params.min_qubits),  # V-chain requires ≥ 3 qubits
            self.base_params.max_qubits,
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
        max_qubits=6,
        min_qubits=3,  # V-chain requires at least 3 qubits
        max_depth=1,
        min_depth=1,
        measure=True,
        seed=42,
    )

    grover_generator = GroverVChain(params)
    n_qubits, target, iterations = grover_generator.generate_parameters()

    print("Generated parameters:")
    print(f"  - Number of qubits: {n_qubits}")
    print(f"  - Target bitstring: {target}")
    print(f"  - Grover iterations: {iterations}")
    print(f"  - Ancilla qubits needed: {n_qubits - 2}")

    grover_circuit = grover_generator.generate(n_qubits, target, iterations)
    print(f"\nGenerated circuit: {grover_circuit.name}")
    print(f"Total qubits: {grover_circuit.num_qubits}")
    print(f"Search qubits: {n_qubits}")
    print(f"Ancilla qubits: {n_qubits - 2}")
    print(f"Classical registers: {len(grover_circuit.cregs)}")
    print(f"Metadata: {grover_circuit.metadata}")
