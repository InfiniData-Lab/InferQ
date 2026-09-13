"""QASMBench loader.

QASMBench (Li et al., NPJ QI 2022; https://github.com/pnnl/QASMBench) is a tree
of ``.qasm`` files organised into ``small/``, ``medium/`` and ``large/`` tiers,
one directory per algorithm with the QASM file inside named after the directory.

The corpus is fetched, not vendored: :mod:`inferq.datasets.registry` pins the
upstream commit and a sha256 for every file, and ``inferq data fetch qasmbench``
unpacks the ``small`` and ``medium`` tiers under ``$INFERQ_DATA_DIR``. That is
strictly more reproducible than the vendored copy it replaces, which recorded a
commit SHA but no checksums, so nothing could confirm the bytes matched it.

``large/`` is excluded deliberately: those circuits exceed InferQ's max_qubits
budget and would time out the simulation phase.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BenchmarkCircuit, BenchmarkLoader
from .registry import spec

if TYPE_CHECKING:  # pragma: no cover
    from qiskit import QuantumCircuit

logger = logging.getLogger(__name__)

DATASET_KEY = "qasmbench"


class QASMBenchLoader(BenchmarkLoader):
    """Iterates the QASMBench small + medium tiers from the fetched dataset."""

    source = "qasmbench"

    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        max_file_bytes: int | None = None,
        auto_fetch: bool = False,
    ) -> None:
        dataset_spec = spec(DATASET_KEY)
        self.data_dir = Path(data_dir) if data_dir is not None else dataset_spec.root
        # A single 81 MB, 14-qubit file sits inside the default qubit range, so
        # without a size guard every full ingest hands it to the QASM parser.
        self.max_file_bytes = (
            max_file_bytes if max_file_bytes is not None else dataset_spec.max_file_bytes
        )
        self.auto_fetch = auto_fetch

    def _ensure_present(self) -> bool:
        if self.data_dir.exists():
            return True
        if self.auto_fetch:
            from .fetch import fetch

            fetch(DATASET_KEY)
            return self.data_dir.exists()
        logger.warning(
            "QASMBench data dir %s not found. Run `inferq data fetch qasmbench` "
            "to download and verify it.",
            self.data_dir,
        )
        return False

    def iter_circuits(
        self,
        min_qubits: int,
        max_qubits: int,
    ) -> Iterator[BenchmarkCircuit]:
        if not self._ensure_present():
            return

        # Lazy import: qasm2 ships with qiskit but the import is non-trivial.
        from qiskit import qasm2

        # QASMBench uses a handful of OpenQASM 2.0 extensions (e.g. `c4x`) that
        # are not in the base parser whitelist. Passing the legacy set turns an
        # unfamiliar gate into an opaque instruction instead of an exception.
        custom_instructions = list(qasm2.LEGACY_CUSTOM_INSTRUCTIONS)

        # Deterministic order, so a --limit smoke run hits the same circuits in
        # the same sequence every time.
        for tier in sorted(p for p in self.data_dir.iterdir() if p.is_dir()):
            if tier.name not in {"small", "medium"}:
                continue
            for algo_dir in sorted(p for p in tier.iterdir() if p.is_dir()):
                qasm_path = algo_dir / f"{algo_dir.name}.qasm"
                if not qasm_path.exists():
                    matches = sorted(algo_dir.glob("*.qasm"))
                    if not matches:
                        continue
                    qasm_path = matches[0]

                if self.max_file_bytes is not None:
                    size = qasm_path.stat().st_size
                    if size > self.max_file_bytes:
                        logger.info(
                            "qasmbench skip %s: %d bytes exceeds max_file_bytes=%d",
                            algo_dir.name,
                            size,
                            self.max_file_bytes,
                        )
                        continue

                try:
                    qc: QuantumCircuit = qasm2.load(
                        str(qasm_path),
                        custom_instructions=custom_instructions,
                    )
                except Exception as exc:
                    logger.debug("qasmbench skip %s: %s: %s", algo_dir.name, type(exc).__name__, exc)
                    continue

                if qc.num_qubits < min_qubits or qc.num_qubits > max_qubits:
                    continue

                yield BenchmarkCircuit(
                    circuit=qc,
                    source=self.source,
                    benchmark_name=algo_dir.name,
                    num_qubits=qc.num_qubits,
                )
