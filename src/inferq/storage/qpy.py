"""Shared helpers for reading QPY-serialized circuits.

``qiskit.qpy.load`` always returns a list of programs, but older payloads and
some Qiskit versions hand back a bare circuit. Every call site in this
repository used to re-implement the same unwrapping, so it lives here once.
"""

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import qiskit.qpy
from qiskit import QuantumCircuit


def circuit_from_qpy_programs(programs) -> QuantumCircuit:
    """Return the single circuit held by a ``qiskit.qpy.load`` result."""
    if isinstance(programs, QuantumCircuit):
        return programs
    programs = list(programs)
    if not programs:
        raise ValueError("QPY payload contains no circuits")
    return programs[0]


def load_circuit(source: str | Path | bytes | BinaryIO) -> QuantumCircuit:
    """Load a circuit from a QPY path, raw bytes, or an open binary stream."""
    if isinstance(source, (str, Path)):
        with open(source, "rb") as handle:
            return circuit_from_qpy_programs(qiskit.qpy.load(handle))
    if isinstance(source, (bytes, bytearray, memoryview)):
        return circuit_from_qpy_programs(qiskit.qpy.load(BytesIO(source)))
    return circuit_from_qpy_programs(qiskit.qpy.load(source))
