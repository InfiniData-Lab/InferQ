"""QASMBench loader.

QASMBench (Li et al., NPJ QI 2022; https://github.com/pnnl/QASMBench) is
distributed as a tree of `.qasm` files organized into `small/`, `medium/`,
and `large/` tiers. We vendor `small/` and `medium/` under
`scripts/benchmark_suites/qasmbench_qasm/` so the benchmark stays frozen for
paper reproducibility — the upstream repo evolves and we want our SIGMOD
revision to be exactly reproducible against a recorded commit SHA (see
`MANIFEST.txt` in that directory).

Each circuit lives at `<tier>/<algo_name>/<algo_name>.qasm` (the tier
directory has one subdirectory per algo, with the QASM file inside named
the same as the directory). We parse with `qiskit.qasm2.loads`.

`large/` is intentionally excluded — those circuits exceed InferQ's max_qubits
budget and would time out the simulation phase.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from qiskit import QuantumCircuit

from .base import BenchmarkCircuit, BenchmarkLoader

logger = logging.getLogger(__name__)

VENDOR_DIR = Path(__file__).parent / "qasmbench_qasm"


class QASMBenchLoader(BenchmarkLoader):
    """Iterates the vendored QASMBench small + medium tiers."""

    source = "qasmbench"

    def __init__(self, vendor_dir: Path | None = None) -> None:
        self.vendor_dir = vendor_dir if vendor_dir is not None else VENDOR_DIR

    def iter_circuits(
        self,
        min_qubits: int,
        max_qubits: int,
    ) -> Iterator[BenchmarkCircuit]:
        if not self.vendor_dir.exists():
            logger.warning(
                f"QASMBench vendor dir {self.vendor_dir} not found. The QASM "
                f"files are vendored into the repo; see "
                f"scripts/benchmark_suites/README.md for the folder inventory."
            )
            return

        # Lazy import — qasm2 is bundled with qiskit but the import is non-trivial.
        from qiskit import qasm2

        # QASMBench uses a handful of OpenQASM 2.0 extensions (e.g. `c4x`)
        # that aren't in the base parser whitelist. `LEGACY_CUSTOM_INSTRUCTIONS`
        # covers the most common ones. We pass them explicitly so unfamiliar
        # gates are turned into opaque instructions instead of raising.
        custom_instructions = list(qasm2.LEGACY_CUSTOM_INSTRUCTIONS)

        # Walk both tiers in deterministic order so re-runs hit the same
        # circuits in the same sequence (helps with --limit smoke tests).
        for tier in sorted(p for p in self.vendor_dir.iterdir() if p.is_dir()):
            if tier.name not in {"small", "medium"}:
                continue
            for algo_dir in sorted(p for p in tier.iterdir() if p.is_dir()):
                # Convention: algo_dir/algo_dir.qasm
                qasm_path = algo_dir / f"{algo_dir.name}.qasm"
                if not qasm_path.exists():
                    # Some algos ship multiple variants — fall back to any *.qasm
                    matches = sorted(algo_dir.glob("*.qasm"))
                    if not matches:
                        continue
                    qasm_path = matches[0]

                try:
                    qc: QuantumCircuit = qasm2.load(
                        str(qasm_path),
                        custom_instructions=custom_instructions,
                    )
                except Exception as e:
                    logger.debug(
                        f"qasmbench skip {algo_dir.name}: {type(e).__name__}: {e}"
                    )
                    continue

                if qc.num_qubits < min_qubits or qc.num_qubits > max_qubits:
                    continue

                yield BenchmarkCircuit(
                    circuit=qc,
                    source=self.source,
                    benchmark_name=algo_dir.name,
                    num_qubits=qc.num_qubits,
                )
