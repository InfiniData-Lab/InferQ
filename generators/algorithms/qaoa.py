from __future__ import annotations

from typing import Sequence, Callable, Optional

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    qaoa_layers,
    qaoa_gamma_parameters,
    qaoa_beta_parameters,
    qaoa_adjacency_matrix,
)

"""Generic QAOA circuit generator (adjacency‑matrix + pluggable cost/mixer)
============================================================================
This module provides both a class-based QAOA generator and a functional interface
for building Quantum Approximate Optimization Algorithm (QAOA) circuits **not just for
Max‑Cut but for *any* cost Hamiltonian**.  You can either supply an *adjacency
matrix* (for Max‑Cut) **or** pass in *callables* that append your own cost and
mixer layers.

Highlights
~~~~~~~~~~
* **Max‑Cut via adjacency matrix** – pass an ``n×n`` (weighted) symmetric matrix
  ``adjacency``; weight 0 means no edge.  The generator constructs the standard
  ZX‑sandwich cost unitary ``exp(-i γ w_{uv}(I-Z_u Z_v)/2)`` for each edge.
* **Fully custom problems** – provide ``cost_layer`` and optionally
  ``mixer_layer`` *callables* that will be invoked once per QAOA layer with
  signature ``layer(qc, qubits, angle)``.
* **Random or user‑supplied angles** – ``gammas`` and ``betas`` lists control
  the variational parameters; random values are filled in if omitted.

Example – Class-based approach
------------------------------
```python
from qaoa import QAOAGenerator
from generators.lib.generator import BaseParams

params = BaseParams(max_qubits=5, min_qubits=2, measure=True)
qaoa_gen = QAOAGenerator(params)
n, p, adjacency = qaoa_gen.generate_parameters()
qc = qaoa_gen.generate(n, p, adjacency=adjacency)
```

Example – Max‑Cut on a weighted square graph
-------------------------------------------
```python
from qaoa import generate
import numpy as np

adj = np.array([[0, 1, 0, 1],
                [1, 0, 1.2, 0],
                [0, 1.2, 0, 0.7],
                [1, 0, 0.7, 0]], dtype=float)

qc = generate(n=4, p=2, adjacency=adj)
qc.draw("mpl")
```

API
~~~
```python
qaoa.generate(
    *,
    n: int,                    # number of qubits
    p: int,                    # QAOA depth (≥1)
    adjacency: np.ndarray | list[list[float]] | None = None,
    cost_layer: callable | None = None,
    mixer_layer: callable | None = None,
    gammas: Sequence[float] | None = None,
    betas: Sequence[float]  | None = None,
    name: str | None = None,
) -> QuantumCircuit
```
Exactly **one** of ``adjacency`` XOR ``cost_layer`` must be supplied.
"""


class QAOA(Generator):
    """
    Class to generate a QAOA (Quantum Approximate Optimization Algorithm) circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        num_qubits: int,
        p: int,
        adjacency: "np.ndarray | list[list[float]] | None" = None,
        cost_layer: "Callable[[QuantumCircuit, list, float], None] | None" = None,
        mixer_layer: "Callable[[QuantumCircuit, list, float], None] | None" = None,
        gammas: Sequence[float] | None = None,
        betas: Sequence[float] | None = None,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a QAOA circuit.

        Args:
            num_qubits (int): Number of qubits (≥ 2).
            p (int): Number of QAOA layers (≥ 1).
            adjacency: Adjacency matrix for Max-Cut problems.
            cost_layer: Custom cost layer function.
            mixer_layer: Custom mixer layer function.
            gammas: Cost parameters (random if None).
            betas: Mixer parameters (random if None).
            name: Optional circuit name.

        Returns:
            QuantumCircuit: The generated QAOA circuit.
        """
        # Validation
        if num_qubits < 2:
            raise ValueError("num_qubits must be ≥ 2")
        if p < 1:
            raise ValueError("p must be ≥ 1")

        if (adjacency is None) == (cost_layer is None):
            raise ValueError("Exactly one of adjacency or cost_layer must be provided")

        # Process adjacency matrix if provided
        edges = []
        if adjacency is not None:
            adj = np.asarray(adjacency, dtype=float)
            if adj.shape != (num_qubits, num_qubits):
                raise ValueError("adjacency must be an n×n matrix")
            if not np.allclose(adj, adj.T):
                raise ValueError(
                    "adjacency matrix must be symmetric (undirected graph)"
                )
            edges = [
                (u, v, adj[u, v])
                for u in range(num_qubits)
                for v in range(u + 1, num_qubits)
                if adj[u, v] != 0
            ]
            if not edges:
                raise ValueError("Graph has no edges – nothing to optimise")

            def cost_layer_func(qc: QuantumCircuit, qubits, gamma):
                for u, v, w in edges:
                    self._maxcut_edge_unitary(qc, qubits[u], qubits[v], gamma * w)

            cost_layer = cost_layer_func

        # Default mixer layer
        if mixer_layer is None:
            mixer_layer = self._default_rx_mixer

        # Generate parameters if not provided
        if gammas is None:
            gammas = qaoa_gamma_parameters(p, self.base_params.seed)
        if betas is None:
            betas = qaoa_beta_parameters(p, self.base_params.seed)

        if len(gammas) != p or len(betas) != p:
            raise ValueError("gammas and betas must have length p")

        # Create circuit
        qr = QuantumRegister(num_qubits, "q")
        if self.measure:
            cr = ClassicalRegister(num_qubits, "c")
            qc = QuantumCircuit(qr, cr)
        else:
            qc = QuantumCircuit(qr)

        qc.name = name or f"QAOA({num_qubits}q,{p}layers)"

        # Initial |+⟩ state
        qc.h(qr)

        # QAOA layers
        for layer in range(p):
            gamma = gammas[layer]
            beta = betas[layer]
            cost_layer(qc, qr, gamma)
            qc.barrier()
            mixer_layer(qc, qr, beta)
            if layer < p - 1:  # Add barrier between layers (except last)
                qc.barrier()

        # Add measurements if requested
        if self.measure:
            qc.barrier()
            qc.measure(qr, cr)

        # Metadata
        qc.metadata = {
            "algorithm": "QAOA",
            "n_qubits": num_qubits,
            "p_layers": p,
            "gammas": list(gammas),
            "betas": list(betas),
            "uses_adjacency": adjacency is not None,
            "num_edges": len(edges) if edges else 0,
            "measured": self.measure,
        }

        return qc

    def _maxcut_edge_unitary(self, qc: QuantumCircuit, u, v, gamma_weighted: float):
        """Apply Max-Cut edge unitary: e^{-i γ w (I - Z Z)/2}"""
        qc.cx(u, v)
        qc.rz(-2 * gamma_weighted, v)  # phase = -2γw  (global phase ignored)
        qc.cx(u, v)

    def _default_rx_mixer(self, qc: QuantumCircuit, qubits, beta: float):
        """Apply default RX mixer layer."""
        qc.rx(2 * beta, qubits)

    def generate_parameters(self) -> tuple[int, int, list[list[float]]]:
        """
        Generate parameters for the QAOA circuit.

        Returns:
            tuple: (num_qubits, p_layers, adjacency_matrix)
        """
        self.num_qubits = num_qbits(
            max(2, self.base_params.min_qubits),  # Ensure at least 2 qubits
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.p_layers = qaoa_layers(
            self.base_params.seed,
            min_layers=1,
            max_layers=min(5, self.base_params.max_depth),  # Limit by max_depth
        )

        # For now, always generate Max-Cut adjacency matrix
        # Future: could add support for custom cost functions
        self.adjacency_matrix = qaoa_adjacency_matrix(
            self.num_qubits, self.base_params.seed, edge_prob=0.5
        )

        return {
            "num_qubits": self.num_qubits,
            "p": self.p_layers,
            "adjacency": self.adjacency_matrix,
        }


# -----------------------------------------------------------------------------
# CLI convenience
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from qiskit.visualization import circuit_drawer
    import ast

    parser = argparse.ArgumentParser(
        description="Generate QAOA circuit and save image."
    )
    parser.add_argument("n", type=int, help="Number of qubits")
    parser.add_argument("p", type=int, help="Number of QAOA layers")
    parser.add_argument(
        "--adj", help="Adjacency matrix as Python literal (e.g. '[[0,1],[1,0]]')"
    )
    parser.add_argument("--measure", action="store_true", help="Add measurements")
    parser.add_argument("--outfile", default="qaoa.svg", help="Output filename")
    args = parser.parse_args()

    adj_mat = ast.literal_eval(args.adj) if args.adj else None

    # qc_cli = generate(n=args.n, p=args.p, adjacency=adj_mat, measure=args.measure)
    print(f"Saved to {args.outfile}")

    # Example usage of class-based approach
    print("\nExample using QAOAGenerator class:")
    from generators.lib.generator import BaseParams

    params = BaseParams(
        max_qubits=args.n,
        min_qubits=args.n,
        max_depth=args.p,
        min_depth=1,
        measure=args.measure,
        seed=42,
    )

    qaoa_gen = QAOA(params)
    params = qaoa_gen.generate_parameters()
    qc_class = qaoa_gen.generate(**params)
    circuit_drawer(qc_class, output="mpl", filename=args.outfile, style="iqp")

    print(
        f"Generated circuit: {qc_class.name}, qubits={qc_class.num_qubits}, depth={qc_class.depth()}"
    )
    print(
        f"Parameters: n={params['num_qubits']}, p={params['p']}, edges={qc_class.metadata.get('num_edges', 0)}"
    )
