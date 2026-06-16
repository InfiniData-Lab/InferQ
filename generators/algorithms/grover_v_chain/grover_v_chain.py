from __future__ import annotations
from typing import Optional
import random
import math

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

"""Grover search circuit generator (V‑chain ancilla mode)
========================================================
This module offers a :pyfunc:`generate` function producing a Grover-search
circuit that implements the multi‑controlled phase‑flip oracle and diffuser
with the *V‑chain* method.  V‑chain uses *n − 2* ancillary qubits, achieving
log‑depth relative to the naïve decomposition while requiring fewer ancillas
than conventional linear‑depth techniques.

Example
-------
```python
from grover_v_chain import generate
qc = generate(n=7, target="0101101")
qc.draw("mpl")
```

Parameters
~~~~~~~~~~
* ``n`` – number of search qubits (*n ≥ 3*).
* ``target`` – length‑``n`` bit‑string marking the unique solution; random if
  *None*.
* ``iterations`` – Grover iteration count *k*; default ``⌊π/4 √(2ⁿ)⌋``.
* ``name`` – optional circuit name.

Return value is a :class:`qiskit.circuit.QuantumCircuit` with measurement of
all search qubits.
"""


# -----------------------------------------------------------------------------
# Helper subroutines
# -----------------------------------------------------------------------------


def _apply_mcz_vchain(qc: QuantumCircuit, controls, target, ancilla) -> None:
    """n‑controlled‑Z (phase flip) using V‑chain ancilla construction.

    Controls: list[Qubit]; target: Qubit; ancilla: QuantumRegister (len = n‑2).
    Steps: H(target) → MCX(mode="v‑chain") → H(target).
    """
    qc.h(target)
    qc.mcx(controls, target, ancilla_qubits=ancilla, mode="v-chain")
    qc.h(target)


def _oracle_phase_flip(
    qc: QuantumCircuit, qr: QuantumRegister, anc: QuantumRegister, *, bitstring: str
) -> None:
    """Phase oracle that flips |bitstring⟩ via V‑chain MCZ."""
    # Transform target state to |11…1⟩ by X on 0‑bits
    for i, bit in enumerate(reversed(bitstring)):
        if bit == "0":
            qc.x(qr[i])
    # Apply MCZ with V‑chain ancillas
    _apply_mcz_vchain(qc, qr[:-1], qr[-1], anc)
    # Undo X gates
    for i, bit in enumerate(reversed(bitstring)):
        if bit == "0":
            qc.x(qr[i])


def _diffuser(qc: QuantumCircuit, qr: QuantumRegister, anc: QuantumRegister) -> None:
    """Grover diffuser using V‑chain MCZ."""
    qc.h(qr)
    qc.x(qr)
    _apply_mcz_vchain(qc, qr[:-1], qr[-1], anc)
    qc.x(qr)
    qc.h(qr)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def generate(
    *,
    n: int,
    target: Optional[str] = None,
    iterations: Optional[int] = None,
    name: Optional[str] = None,
    measure: bool = False,
) -> QuantumCircuit:  # noqa: D401
    """Generate a Grover circuit with V‑chain ancilla strategy."""
    if n < 3:
        raise ValueError("n must be ≥ 3 for V‑chain (requires n‑2 ancillas)")

    # Derive / validate target pattern
    if target is None:
        target = format(random.randrange(2**n), f"0{n}b")
    if len(target) != n or any(ch not in "01" for ch in target):
        raise ValueError("target must be an n‑length bit‑string of 0/1")

    # Optimal iteration count if unspecified
    if iterations is None:
        iterations = int(math.floor((math.pi / 4) * math.sqrt(2**n)))
    iterations = max(1, iterations)

    # Registers: search qubits + ancillas + classical bits
    qr = QuantumRegister(n, name="q")
    anc = QuantumRegister(n - 2, name="anc")
    cr = ClassicalRegister(n, name="c")
    qc = QuantumCircuit(qr, anc, cr, name=name or f"Grover_vchain_{n}q")

    # Uniform superposition
    qc.h(qr)

    # Grover iterations
    for _ in range(iterations):
        _oracle_phase_flip(qc, qr, anc, bitstring=target)
        _diffuser(qc, qr, anc)

    if measure:
        # Measure all search qubits
        qc.barrier()
        qc.measure(qr, cr)

    # Metadata
    qc.metadata = {
        "algorithm": "Grover-v-chain",
        "n_qubits": n,
        "target": target,
        "iterations": iterations,
        "ancillas": n - 2,
    }
    return qc


# -----------------------------------------------------------------------------
# CLI convenience (optional)
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from qiskit.visualization import circuit_drawer

    parser = argparse.ArgumentParser(
        description="Generate Grover V‑chain circuit and save an image."
    )
    parser.add_argument("n", type=int, help="Number of search qubits (≥3)")
    parser.add_argument("--target", help="Marked bit‑string; random if omitted")
    parser.add_argument("-k", "--iterations", type=int, help="Grover iteration count")
    parser.add_argument(
        "--outfile", default="grover_vchain.svg", help="Output image filename"
    )
    args = parser.parse_args()

    qc = generate(
        n=args.n, target=args.target, iterations=args.iterations, measure=True
    )
    circuit_drawer(qc, output="mpl", filename=args.outfile, style="iqp")
    print(f"Circuit saved to {args.outfile}")
