from __future__ import annotations
from typing import Optional

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    qwalk_steps,
    qwalk_coin_preparation_type,
)

"""Quantum Walk circuit generator
===============================
This module provides both a class-based quantum walk generator and a functional interface
for generating quantum walk circuits. Based on MQT Bench's implementation, it supports
discrete-time quantum walks on graphs with configurable coin operators and steps.

Quick example
~~~~~~~~~~~~~
```python
# Class-based approach
from qwalk import QuantumWalkGenerator
from generators.lib.generator import BaseParams

params = BaseParams(max_qubits=5, min_qubits=2, measure=True)
qwalk_gen = QuantumWalkGenerator(params)
n, steps, coin_type = qwalk_gen.generate_parameters()
qc = qwalk_gen.generate(n, steps, coin_type)

# Function-based approach
from qwalk import generate
qc = generate(n=4, depth=3)
```

Parameters
~~~~~~~~~~
* ``n`` – total number of qubits (``n ≥ 2``). One qubit for coin, n-1 for graph nodes.
* ``depth`` – number of quantum walk steps.
* ``coin_preparation_type`` – type of coin state preparation.
* ``coin_state_preparation`` – custom coin preparation circuit.
* ``measure`` – whether to add measurements. Default ``False``.
* ``name`` – optional circuit name.

Returns
~~~~~~~
:class:`qiskit.circuit.QuantumCircuit` containing the quantum walk circuit.
"""


class QuantumWalk(Generator):
    """
    Class to generate a Quantum Walk circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        num_qubits: int,
        steps: int,
        coin_preparation_type: str = "none",
        coin_state_preparation: Optional[QuantumCircuit] = None,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a Quantum Walk circuit.

        Args:
            num_qubits (int): Total number of qubits (≥ 2).
            steps (int): Number of quantum walk steps.
            coin_preparation_type (str): Type of coin preparation.
            coin_state_preparation (Optional[QuantumCircuit]): Custom coin circuit.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated quantum walk circuit.
        """
        if num_qubits < 3:
            raise ValueError("num_qubits must be ≥ 3 (1 for coin, ≥2 for graph)")

        # Calculate graph size (num_qubits - 1 for coin qubit)
        graph_size = num_qubits - 1

        # Create quantum registers
        coin = QuantumRegister(1, "coin")
        node = QuantumRegister(graph_size, "graphnode")

        # Create classical register if measurements are needed
        cr = None
        if self.measure:
            cr = ClassicalRegister(num_qubits, "c")
            qc = QuantumCircuit(node, coin, cr)
        else:
            qc = QuantumCircuit(node, coin)

        qc.name = name or f"QuantumWalk({num_qubits}q,{steps}steps)"

        # Coin state preparation
        if coin_state_preparation is not None:
            qc.append(coin_state_preparation, coin[:])
        else:
            self._apply_coin_preparation(qc, coin, coin_preparation_type)

        # Quantum walk steps
        for step in range(steps):
            self._quantum_walk_step(qc, coin, node, graph_size)
            if step < steps - 1:  # Add barrier between steps (except last)
                qc.barrier()

        # Add measurements if requested
        if self.measure:
            qc.barrier()
            # Measure graph nodes first, then coin
            qc.measure(node, cr[:graph_size])
            qc.measure(coin, cr[graph_size:])

        # Metadata
        qc.metadata = {
            "algorithm": "QuantumWalk",
            "total_qubits": num_qubits,
            "graph_size": graph_size,
            "steps": steps,
            "coin_preparation": coin_preparation_type,
            "measured": self.measure,
        }

        return qc

    def _apply_coin_preparation(
        self, qc: QuantumCircuit, coin: QuantumRegister, prep_type: str
    ):
        """Apply coin state preparation based on type."""
        if prep_type == "hadamard":
            qc.h(coin)
        elif prep_type == "x":
            qc.x(coin)
        elif prep_type == "y":
            qc.y(coin)
        elif prep_type == "none":
            pass  # No preparation, start in |0⟩
        else:
            raise ValueError(f"Unknown coin preparation type: {prep_type}")

    def _quantum_walk_step(
        self, qc: QuantumCircuit, coin: QuantumRegister, node: QuantumRegister, n: int
    ):
        """Perform one quantum walk step."""
        # Hadamard coin operator
        qc.h(coin)

        # Controlled increment
        for i in range(n - 1):
            qc.mcx(coin[:] + node[i + 1 :], node[i])
        qc.cx(coin, node[n - 1])

        # Controlled decrement
        qc.x(coin)
        qc.x(node[1:])
        for i in range(n - 1):
            qc.mcx(coin[:] + node[i + 1 :], node[i])
        qc.cx(coin, node[n - 1])
        qc.x(node[1:])
        qc.x(coin)

    def generate_parameters(self) -> dict:
        """
        Generate parameters for the Quantum Walk circuit.

        Returns:
            tuple: (num_qubits, steps, coin_preparation_type)
        """
        self.num_qubits = num_qbits(
            max(2, self.base_params.min_qubits),  # Ensure at least 2 qubits
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.steps = qwalk_steps(
            self.base_params.seed,
            min_steps=1,
            max_steps=min(10, self.base_params.max_depth),  # Limit by max_depth
        )

        self.coin_preparation_type = qwalk_coin_preparation_type(self.base_params.seed)

        return {
            "num_qubits": self.num_qubits,
            "steps": self.steps,
            "coin_preparation_type": self.coin_preparation_type,
        }


# -----------------------------------------------------------------------------
# CLI for quick visualization
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a Quantum Walk circuit and save to SVG."
    )
    parser.add_argument("n", type=int, help="Total number of qubits (≥2)")
    parser.add_argument("depth", type=int, help="Number of quantum walk steps")
    parser.add_argument(
        "--coin-prep",
        choices=["none", "hadamard", "x", "y"],
        default="none",
        help="Coin state preparation type",
    )
    parser.add_argument("--measure", action="store_true", help="Add measurements")
    parser.add_argument("--outfile", default="qwalk.svg", help="Output SVG filename")
    args = parser.parse_args()

    # Example usage of class-based approach
    print("\nExample using QuantumWalkGenerator class:")
    from generators.lib.generator import BaseParams

    params = BaseParams(
        max_qubits=args.n,
        min_qubits=args.n,
        max_depth=args.depth,
        min_depth=1,
        measure=args.measure,
        seed=42,
    )

    qwalk_gen = QuantumWalk(params)
    params = qwalk_gen.generate_parameters()
    qc_class = qwalk_gen.generate(**params)
    print(
        f"Generated circuit: {qc_class.name}, qubits={qc_class.num_qubits}, depth={qc_class.depth()}"
    )
    print(
        f"Parameters: n={params['num_qubits']}, steps={params['steps']}, coin_prep={params['coin_preparation_type']}"
    )
    print(f"Graph size: {params['num_qubits'] - 1} nodes")
