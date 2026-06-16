from __future__ import annotations
from typing import Optional
import random

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

"""Deutsch–Jozsa circuit generator
==================================
This module provides a single public entry‑point :pyfunc:`generate` that
constructs a Deutsch–Jozsa circuit for an *n*‑bit oracle that is promised to be
either *constant* or *balanced*.

Example
-------
>>> from deutsch_jozsa import generate
>>> qc = generate(n=4, oracle_type="balanced")
>>> print(qc.draw())

The returned object is a :class:`~qiskit.circuit.QuantumCircuit` ready for
simulation or transpilation.

Parameters handled
------------------
* ``n`` – number of input qubits (integer ≥ 1).
* ``oracle_type`` – ``"balanced"`` or ``"constant"``.
* ``bitstring`` – for a *balanced* oracle, an ``n``‑length bit‑string (e.g.
  "1010") specifying the hidden string *a* in ``f(x)=a·x (mod 2)``. If
  *None*, a random non‑zero string is picked.
* ``constant_output`` – for a *constant* oracle, choose 0 (default) or 1.
* ``name`` – optional circuit name.

The circuit layout is::

    ┌───┐┌───────┐      ┌───┐┌─┐  
 q: ┤ H ├┤ Oracle ├─────┤ H ├┤M├──
    └───┘└───────┘┌───┐└───┘└╥┘
anc:┤ X ├─────────┤ H ├──────╫──
    └───┘         └───┘      ║  
                           classical bits

The ancilla (bottom line) starts in |1⟩, ensuring phase kickback implements
``f`` as a phase oracle.
"""


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def _balanced_oracle(
    qc: QuantumCircuit, controls: QuantumRegister, ancilla, *, bitstring: str
) -> None:  # noqa: D401
    """Append a *balanced* oracle U_f for f(x)=a·x (mod 2).

    The oracle flips the ancilla qubit iff the dot‑product of *x* and *a* is 1.
    Implementation: for each 1‑bit in |a| apply CNOT(control, ancilla).
    """
    for idx, bit in enumerate(reversed(bitstring)):
        if bit == "1":
            qc.cx(controls[idx], ancilla)


def _constant_oracle(qc: QuantumCircuit, ancilla, *, output: int) -> None:  # noqa: D401
    """Append a *constant* oracle that maps any x → *output* (0 or 1)."""
    if output % 2 == 1:
        qc.x(ancilla)  # Flip ancilla unconditionally to encode f(x)=1


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def generate(
    *,
    n: int,
    oracle_type: str = "balanced",
    bitstring: Optional[str] = None,
    constant_output: int = 0,
    name: str | None = None,
    measure: bool = False,
) -> QuantumCircuit:  # noqa: D401
    """Construct and return a Deutsch–Jozsa quantum circuit.

    Parameters
    ----------
    n
        Number of input qubits (must be ≥ 1).
    oracle_type
        Either ``"balanced"`` or ``"constant"``.
    bitstring
        For *balanced* oracles, an n‑length string of 0/1 characters defining the
        hidden string *a*. If ``None`` a random non‑zero bit‑string is chosen.
        Ignored for *constant* oracles.
    constant_output
        For *constant* oracles choose 0 (default) or 1. Ignored if
        *oracle_type* is *balanced*.
    name
        Optional custom circuit name.

    Returns
    -------
    qiskit.circuit.QuantumCircuit
        The complete Deutsch–Jozsa algorithm circuit including measurement of
        the first *n* qubits.
    """

    if n < 1:
        raise ValueError("n must be ≥ 1")

    oracle_type = oracle_type.lower()
    if oracle_type not in {"balanced", "constant"}:
        raise ValueError("oracle_type must be 'balanced' or 'constant'")

    # Auto‑generate a valid bitstring if none supplied for balanced oracle
    if oracle_type == "balanced":
        if bitstring is None:
            # ensure non‑zero so it is indeed balanced
            bitstring = format(random.randint(1, 2**n - 1), f"0{n}b")
        if len(bitstring) != n or any(ch not in "01" for ch in bitstring):
            raise ValueError("bitstring must be an n‑length string of 0/1")
    else:
        bitstring = "0" * n  # dummy, unused

    # ------------------------------------------------------------------
    # Registers & pre‑oracle preparation
    # ------------------------------------------------------------------
    qr = QuantumRegister(n, name="q")
    anc = QuantumRegister(1, name="anc")
    cr = ClassicalRegister(n, name="c")
    circuit_name = name or f"Deutsch‑Jozsa_{oracle_type}_{n}q"
    qc = QuantumCircuit(qr, anc, cr, name=circuit_name)

    # Put ancilla to |1⟩ and apply Hadamard to all qubits
    qc.x(anc)
    qc.h(qr)
    qc.h(anc)

    # ------------------------------------------------------------------
    # Oracle
    # ------------------------------------------------------------------
    if oracle_type == "balanced":
        _balanced_oracle(qc, qr, anc[0], bitstring=bitstring)
    else:
        _constant_oracle(qc, anc[0], output=constant_output)

    # ------------------------------------------------------------------
    # Interference & measurement
    # ------------------------------------------------------------------
    qc.h(qr)
    if measure:
        qc.barrier()  # Optional barrier before measurement
        qc.measure(qr, cr)

    # Attach metadata for later inspection
    qc.metadata = {
        "algorithm": "Deutsch‑Jozsa",
        "n_qubits": n,
        "oracle_type": oracle_type,
        "bitstring": bitstring if oracle_type == "balanced" else None,
        "constant_output": constant_output if oracle_type == "constant" else None,
    }

    return qc


# -----------------------------------------------------------------------------
# Command‑line entry‑point (optional convenience)
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from qiskit.visualization import circuit_drawer

    parser = argparse.ArgumentParser(
        description="Generate a Deutsch–Jozsa circuit and save as image."
    )
    parser.add_argument("n", type=int, help="Number of input qubits")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--balanced",
        dest="oracle_type",
        action="store_const",
        const="balanced",
        help="Use a balanced oracle (default)",
    )
    group.add_argument(
        "--constant",
        dest="oracle_type",
        action="store_const",
        const="constant",
        help="Use a constant oracle",
    )
    parser.add_argument(
        "--bitstring", help="Bitstring for balanced oracle; random if omitted"
    )
    parser.add_argument(
        "--const",
        dest="constant_output",
        type=int,
        choices=[0, 1],
        default=0,
        help="Constant output value (0 or 1) for constant oracle",
    )
    parser.add_argument(
        "--outfile", default="dj_circuit.svg", help="Output image filename"
    )

    args = parser.parse_args()
    oracle_type = args.oracle_type or "balanced"
    qc = generate(
        n=args.n,
        oracle_type=oracle_type,
        bitstring=args.bitstring,
        constant_output=args.constant_output,
        measure=True,  # Always measure for visualization
    )
    circuit_drawer(qc, output="mpl", filename=args.outfile, style="iqp")
    print(f"Circuit saved to {args.outfile}")
