from __future__ import annotations

from typing import Optional
import random
import math

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

"""Grover search (no–ancilla oracle) circuit generator
=====================================================
This module exposes a single public :pyfunc:`generate` function that builds a
Grover-search circuit entirely **without ancillary qubits**.  The oracle is
implemented as a phase-flip about the marked state using a multi‑controlled‑Z
built from an MCX gate in *no‑ancilla* mode.

**Example**
-----------
```python
from grover_no_ancilla import generate
qc = generate(n=5, target="10110")
print(qc.draw())
```

Parameters handled
------------------
* ``n`` – number of search qubits (integer ≥ 1 and ≤ 8 — the *no‑ancilla* MCX is
  available in Qiskit for up to 8 controls).
* ``target`` – bit‑string of length *n* marking the unique solution (if
  *None*, a random string is chosen).
* ``iterations`` – explicit Grover‑iteration count *k*; if *None* the
  near‑optimal value ``floor(pi/4 * sqrt(2**n))`` is used.
* ``name`` – optional custom circuit name.

The returned object is a :class:`qiskit.circuit.QuantumCircuit` ready for
simulation or transpilation.  All *n* qubits are measured into an *n*‑bit
classical register.
"""


# -----------------------------------------------------------------------------
# Helper subroutines
# -----------------------------------------------------------------------------


def _apply_mcz(qc: QuantumCircuit, qubits) -> None:
    """Apply an n‑qubit controlled‑Z using *no‑ancilla* technique.

    For qubits q[0]..q[n-1] (controls *and* target) we:
    1. Hadamard the *last* qubit to swap Z ↔ X.
    2. Apply multi‑controlled‑X (MCX) with *n‑1* controls (q[0..n-2]) targeting q[n-1].
       The Qiskit MCX 'noancilla' mode uses no extra ancilla qubits for up to 8 controls.
    3. Hadamard the target back, yielding an n‑controlled Z phase flip.
    """
    *controls, target = qubits
    qc.h(target)
    qc.mcx(controls, target, mode="noancilla")
    qc.h(target)


def _oracle_phase_flip(
    qc: QuantumCircuit, qr: QuantumRegister, *, bitstring: str
) -> None:
    """Phase‑flip oracle marking ``|bitstring⟩`` with a −1 phase.

    Implementation: X‑transform qubits where target bit is 0 → apply MCZ → undo X.
    Effectively adds a global phase −1 to |bitstring⟩ and leaves all other basis
    states unchanged.
    """
    # X on |0⟩ positions so that the marked state becomes |11…1⟩
    for idx, bit in enumerate(reversed(bitstring)):
        if bit == "0":
            qc.x(qr[idx])

    _apply_mcz(qc, qr)

    # Undo the X gates
    for idx, bit in enumerate(reversed(bitstring)):
        if bit == "0":
            qc.x(qr[idx])


def _diffuser(qc: QuantumCircuit, qr: QuantumRegister) -> None:
    """Standard Grover diffuser (inversion about the mean) without ancilla."""
    qc.h(qr)
    qc.x(qr)
    _apply_mcz(qc, qr)
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
    """Construct a Grover‑search circuit **without ancilla qubits**.

    Parameters
    ----------
    n
        Number of qubits that encode the search space (1 ≤ n ≤ 8).
    target
        Bit‑string specifying the unique marked item. If ``None`` a random
        target in ``[0, 2**n)`` is sampled.
    iterations
        Number of Grover iterations *k*.  If omitted, the canonical near‑optimal
        ``floor(pi/4 * sqrt(2**n))`` is used.
    name
        Optional custom circuit name.

    Returns
    -------
    qiskit.circuit.QuantumCircuit
        Circuit implementing Grover search and measuring all qubits.
    """

    if not (1 <= n <= 8):
        raise ValueError("n must be between 1 and 8 for the no‑ancilla MCX gate")

    if target is None:
        target = format(random.randrange(2**n), f"0{n}b")
    if len(target) != n or any(ch not in "01" for ch in target):
        raise ValueError("target must be an n‑length bit‑string of 0/1")

    if iterations is None:
        iterations = int(math.floor((math.pi / 4) * math.sqrt(2**n)))
    if iterations < 1:
        iterations = 1  # minimal useful iteration

    qr = QuantumRegister(n, name="q")
    cr = ClassicalRegister(n, name="c")
    circuit_name = name or f"Grover_noanc_{n}q"
    qc = QuantumCircuit(qr, cr, name=circuit_name)

    # Initial uniform superposition
    qc.h(qr)

    for _ in range(iterations):
        _oracle_phase_flip(qc, qr, bitstring=target)
        _diffuser(qc, qr)

    if measure:
        qc.barrier()  # Optional barrier before measurement
        qc.measure(qr, cr)

    qc.metadata = {
        "algorithm": "Grover-no-ancilla",
        "n_qubits": n,
        "target": target,
        "iterations": iterations,
    }
    return qc


# -----------------------------------------------------------------------------
# CLI convenience (optional)
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from qiskit.visualization import circuit_drawer

    parser = argparse.ArgumentParser(
        description="Generate a Grover circuit (no ancilla) and save as image."
    )
    parser.add_argument("n", type=int, help="Number of search qubits (1‑8)")
    parser.add_argument("--target", help="Marked bit‑string; random if omitted")
    parser.add_argument(
        "-k", "--iterations", type=int, help="Number of Grover iterations"
    )
    parser.add_argument(
        "--outfile", default="grover_noanc.svg", help="Output image filename"
    )

    args = parser.parse_args()
    qc = generate(
        n=args.n, target=args.target, iterations=args.iterations, measure=True
    )
    circuit_drawer(qc, output="mpl", filename=args.outfile, style="iqp")
    print(f"Circuit saved to {args.outfile}")
