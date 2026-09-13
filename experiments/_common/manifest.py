"""Shared persistence for the OOC manifest builders.

Every builder emits the same two artefacts: ``.qpy`` circuit files laid out in
hash-prefixed subdirectories under ``circuits/``, and a JSONL manifest in the
schema ``experiments/ooc/run_experiment.py`` consumes.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from qiskit.qpy import dump as qpy_dump


def persist_qpy(
    circuit,
    circuit_hash: str,
    circuits_dir: Path,
    overwrite: bool = False,
) -> Path:
    """Serialise a circuit into the hash-sharded circuit store.

    Args:
        circuit: The ``QuantumCircuit`` to serialise.
        circuit_hash: Content hash used for both the subdirectory and filename.
        circuits_dir: Root of the circuit store.
        overwrite: Re-serialise even when the target file already exists.

    Returns:
        Path of the ``.qpy`` file, whether or not it was rewritten.
    """
    subdir = circuits_dir / circuit_hash[:2]
    subdir.mkdir(parents=True, exist_ok=True)
    qpy_path = subdir / f"{circuit_hash}.qpy"
    if overwrite or not qpy_path.exists():
        with qpy_path.open("wb") as f:
            qpy_dump(circuit, f)
    return qpy_path


def write_manifest(out_path: Path, rows: Iterable[Mapping]) -> int:
    """Write manifest rows as JSON Lines, one compact object per line.

    Args:
        out_path: Destination file, truncated if it exists.
        rows: Manifest rows in emission order.

    Returns:
        Number of rows written.
    """
    written = 0
    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
            written += 1
    return written
