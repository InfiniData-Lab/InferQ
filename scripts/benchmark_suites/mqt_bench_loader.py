"""MQT Bench loader.

Uses the v2 API: `mqt.bench.get_benchmark(benchmark=<name>, level=BenchmarkLevel.ALG, circuit_size=N)`.
Algorithm-level circuits are returned as `qiskit.QuantumCircuit` directly —
no transpilation, no native-gate mapping — which matches what InferQ produces
internally so the resulting feature distributions are comparable.
"""

from __future__ import annotations

import logging
from typing import Iterator

from .base import BenchmarkCircuit, BenchmarkLoader

logger = logging.getLogger(__name__)

# Curated allowlist drawn from `mqt.bench.benchmarks.get_available_benchmark_names()`.
# Covers all functional categories of the suite: state preparation (ghz, wstate,
# graphstate), spectral (qft, qpe), oracle (dj, grover, bv), variational
# (qaoa, vqe-*, qnn, ae), dynamics (qwalk, randomcircuit), and quantum-error-
# correction toy circuits (steane).
#
# Excluded by design:
#   - shor / hhl / shors_nine_qubit_code: large fixed-size circuits that would
#     dominate the storage budget and aren't representative of the workloads
#     InferQ targets.
#   - Adders/multipliers (>10 variants in the suite): we keep only one
#     representative (`full_adder`) to avoid skewing the corpus toward
#     arithmetic primitives.
#   - bmw_quark_*: industry-specific, not in the SIGMOD baseline comparison set.
ALGORITHMS: list[str] = [
    "ae",
    "dj",
    "ghz",
    "graphstate",
    "wstate",
    "qft",
    "qftentangled",
    "qpeexact",
    "qpeinexact",
    "grover",
    "qaoa",
    "qnn",
    "qwalk",
    "randomcircuit",
    "vqe_real_amp",
    "vqe_su2",
    "vqe_two_local",
    "bv",
    "full_adder",
    "seven_qubit_steane_code",
]


class MQTBenchLoader(BenchmarkLoader):
    """Iterates the curated MQT Bench algorithms across a qubit sweep."""

    source = "mqt"

    def __init__(self, algorithms: list[str] | None = None) -> None:
        self.algorithms = list(algorithms) if algorithms is not None else ALGORITHMS

    def iter_circuits(
        self,
        min_qubits: int,
        max_qubits: int,
    ) -> Iterator[BenchmarkCircuit]:
        # Imported lazily so test environments without mqt.bench can still
        # import this module to inspect ALGORITHMS.
        from mqt.bench import BenchmarkLevel, get_benchmark

        for algo in self.algorithms:
            for n in range(max(2, min_qubits), max_qubits + 1):
                try:
                    qc = get_benchmark(
                        benchmark=algo,
                        level=BenchmarkLevel.ALG,
                        circuit_size=n,
                    )
                except Exception as e:
                    # Several algos have constraints (e.g. qpe needs n>=2 with
                    # specific eval-qubit budgets, qaoa needs n>=3). Skip and
                    # keep going — we don't want one bad combo to abort the run.
                    logger.debug(f"mqt.bench skip {algo} n={n}: {type(e).__name__}: {e}")
                    continue

                if qc.num_qubits < min_qubits or qc.num_qubits > max_qubits:
                    # mqt.bench occasionally returns circuits with a different
                    # qubit count than requested (e.g. qpe adds eval qubits).
                    continue

                yield BenchmarkCircuit(
                    circuit=qc,
                    source=self.source,
                    benchmark_name=f"{algo}_n{n}",
                    num_qubits=qc.num_qubits,
                )
