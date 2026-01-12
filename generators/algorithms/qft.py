from __future__ import annotations
from typing import Optional
import random
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit.library import QFT
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    qft_inverse_flag,
    qft_swaps_flag,
    qft_entanglement_flag,
)

"""Quantum Fourier Transform (QFT) circuit generator
====================================================
This module provides both a class-based QFT generator and a functional interface
for generating Quantum Fourier Transform circuits using **Qiskit**'s built‑in
:class:`qiskit.circuit.library.QFT` template.  It supports both forward and
inverse transforms, optional qubit‑reversal swaps, and entangled QFT mode.

Quick example
~~~~~~~~~~~~~
```python
# Class-based approach
from qft import QFTGenerator
from generators.lib.generator import BaseParams

params = BaseParams(max_qubits=5, min_qubits=2, measure=True)
qft_gen = QFTGenerator(params)
n, inverse, do_swaps, entangled = qft_gen.generate_parameters()
qc = qft_gen.generate(n, inverse, do_swaps, entangled)

# Function-based approach
from qft import generate
qc = generate(n=5)              # 5‑qubit forward QFT with swaps + measurement
print(qc.draw())

qc_inv = generate(n=5, inverse=True, do_swaps=False)
```

Parameters
~~~~~~~~~~
* ``n`` – number of qubits (``n ≥ 1``). For entangled mode, this is qubits per register.
* ``inverse`` – if ``True`` build the inverse QFT (*QFT†*). Default ``False``.
* ``do_swaps`` – include the canonical qubit‑reversal swaps. Default ``True``.
* ``entangled`` – if ``True`` create entangled QFT with two registers. Default ``False``.
* ``measure`` – whether to add classical register and measure qubits. Default ``True``.
* ``name`` – optional circuit name.

Returns
~~~~~~~
:class:`qiskit.circuit.QuantumCircuit` containing the QFT (and optionally
measurements). For entangled mode, returns a circuit with two quantum registers.
"""


class QFTGenerator(Generator):
    """
    Class to generate a Quantum Fourier Transform circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        num_qubits: int,
        inverse: bool = False,
        do_swaps: bool = True,
        entangled: bool = False,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a QFT (or inverse QFT) circuit, optionally with entanglement.

        Args:
            num_qubits (int): Number of qubits per register (≥ 1).
            inverse (bool): If True, build inverse QFT. Default False.
            do_swaps (bool): Include qubit-reversal swaps. Default True.
            entangled (bool): If True, create entangled QFT with two registers. Default False.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated QFT circuit.
        """
        if num_qubits < 1:
            raise ValueError("num_qubits must be ≥ 1")

        if entangled:
            # Create entangled QFT with two registers
            src = QuantumRegister(num_qubits, "src")  # register that will undergo QFT
            tgt = QuantumRegister(num_qubits, "tgt")  # entangled partner register
            total_qubits = 2 * num_qubits
            cr = ClassicalRegister(total_qubits, name="c") if self.measure else None

            qc = QuantumCircuit(src, tgt, cr) if cr else QuantumCircuit(src, tgt)
            qc.name = name or (
                f"EntangledQFT†({num_qubits})"
                if inverse
                else f"EntangledQFT({num_qubits})"
            )

            # Create entanglement between registers
            qc.h(src)  # put |src⟩ in equal superposition
            for i in range(num_qubits):
                qc.cx(src[i], tgt[i])

            # Apply QFT to src register
            qft_gate = QFT(
                num_qubits=num_qubits,
                approximation_degree=0,
                inverse=inverse,
                do_swaps=do_swaps,
                name="QFT†" if inverse else "QFT",
            )
            qc.append(qft_gate, src)

            if self.measure:
                qc.barrier()
                qc.measure(src, cr[:num_qubits])  # type: ignore[arg-type]
                qc.measure(tgt, cr[num_qubits:])  # type: ignore[arg-type]

            # Metadata
            qc.metadata = {
                "algorithm": "EntangledQFT" if not inverse else "EntangledInverseQFT",
                "n_qubits_per_reg": num_qubits,
                "inverse": inverse,
                "do_swaps": do_swaps,
                "entangled": entangled,
                "measured": self.measure,
            }

        else:
            # Regular QFT with single register
            qr = QuantumRegister(num_qubits, name="q")
            cr = ClassicalRegister(num_qubits, name="c") if self.measure else None

            qc = QuantumCircuit(qr, cr) if cr else QuantumCircuit(qr)
            qc.name = name or (
                f"QFT†({num_qubits})" if inverse else f"QFT({num_qubits})"
            )

            # Append the QFT template
            qft_gate = QFT(
                num_qubits=num_qubits,
                approximation_degree=0,
                inverse=inverse,
                do_swaps=do_swaps,
                name="QFT†" if inverse else "QFT",
            )
            qc.append(qft_gate, qr)

            if self.measure:
                qc.barrier()
                qc.measure(qr, cr)  # type: ignore[arg-type]

            # Metadata
            qc.metadata = {
                "algorithm": "QFT" if not inverse else "InverseQFT",
                "n_qubits": num_qubits,
                "inverse": inverse,
                "do_swaps": do_swaps,
                "entangled": entangled,
                "measured": self.measure,
            }

        return qc.decompose().decompose()

    def generate_parameters(self) -> tuple[int, bool, bool, bool]:
        """
        Generate parameters for the QFT circuit.

        Returns:
            tuple: (num_qubits, inverse, do_swaps, entangled)
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        self.inverse = qft_inverse_flag(self.base_params.seed)
        self.do_swaps = qft_swaps_flag(self.base_params.seed)
        self.entangled = qft_entanglement_flag(self.base_params.seed)

        return {
            "num_qubits": self.num_qubits,
            "inverse": self.inverse,
            "do_swaps": self.do_swaps,
            "entangled": self.entangled,
        }


# -----------------------------------------------------------------------------
# CLI for quick visualization
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from qiskit.visualization import circuit_drawer

    parser = argparse.ArgumentParser(
        description="Generate a QFT circuit and save to SVG."
    )
    parser.add_argument("n", type=int, help="Number of qubits (≥1)")
    parser.add_argument("--inverse", action="store_true", help="Generate inverse QFT")
    parser.add_argument(
        "--no‑swaps",
        dest="do_swaps",
        action="store_false",
        help="Omit final qubit‑reversal swaps",
    )
    parser.add_argument(
        "--no‑measure",
        dest="measure",
        action="store_false",
        help="Do not add measurements",
    )
    parser.add_argument("--outfile", default="qft.svg", help="Output SVG filename")
    args = parser.parse_args()

    print(f"Circuit saved to {args.outfile}")

    # Example usage of class-based approach
    print("\nExample using QFTGenerator class:")
    params = BaseParams(
        max_qubits=args.n,
        min_qubits=args.n,
        max_depth=1,
        min_depth=1,
        measure=False,
        seed=3
    )
    random.seed(params.seed)
    np.random.seed(params.seed)

    qft_gen = QFTGenerator(params)
    params = qft_gen.generate_parameters()
    qc_class = qft_gen.generate(**params)
    print(
        f"Generated circuit: {qc_class.name}, qubits={qc_class.num_qubits}, depth={qc_class.depth()}"
    )
    print(
        f"Parameters: n={params['num_qubits']}, inverse={params['inverse']}, swaps={params['do_swaps']}, entangled={params['entangled']}"
    )
    circuit_drawer(qc_class, output="mpl", filename=args.outfile, style="iqp")