"""SupermarQ loader.

SupermarQ exposes 8 application benchmarks in `supermarq.benchmarks`. They
return Cirq `Circuit` objects (or a list of them, for `VQEProxy`); we convert
to Qiskit via the package's own `cirq_to_qiskit` to avoid OpenQASM
round-tripping (which would lose conditionals on some benchmarks).

Some constructors take parameters beyond `num_qubits` — `PhaseCode` and
`BitCode` need a stabilizer state and a number of rounds; `VQEProxy` needs a
layer count and emits two parametrized circuits per call. We pick conservative
defaults that match the SupermarQ paper's reference configuration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

from qiskit import QuantumCircuit

from .base import BenchmarkCircuit, BenchmarkLoader

logger = logging.getLogger(__name__)


# Builder closure type: (num_qubits) -> (cirq_circuit, qubit_list)
# Returning the qubit list explicitly avoids re-deriving it; some SupermarQ
# benchmarks insert ancillas with non-default ordering, so we let each builder
# state which qubits to register on the qiskit side.
def _build_ghz(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.GHZ(num_qubits=n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_ham_sim(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.HamiltonianSimulation(num_qubits=n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_mermin_bell(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.MerminBell(num_qubits=n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_phase_code(n: int) -> tuple:
    """PhaseCode QEC benchmark with `n` data qubits, 1 syndrome round, all-zero state.

    The total qubit count is 2*n - 1 (data + syndrome ancillas).
    """
    import supermarq.benchmarks as sb

    b = sb.PhaseCode(num_data_qubits=n, num_rounds=1, phase_state=[0] * n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_bit_code(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.BitCode(num_data_qubits=n, num_rounds=1, bit_state=[0] * n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_qaoa_fermionic(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.QAOAFermionicSwapProxy(num_qubits=n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_qaoa_vanilla(n: int) -> tuple:
    import supermarq.benchmarks as sb

    b = sb.QAOAVanillaProxy(num_qubits=n)
    c = b.circuit()
    return c, sorted(c.all_qubits())


def _build_vqe_proxy(n: int) -> tuple:
    """VQEProxy returns *two* Cirq circuits per call (an Ansatz + a measurement
    rotation). We yield only the first — it dominates the work and is the one
    consumed by SupermarQ's reference runner.
    """
    import supermarq.benchmarks as sb

    b = sb.VQEProxy(num_qubits=n, num_layers=1)
    circuits = b.circuit()
    c = circuits[0]
    return c, sorted(c.all_qubits())


# Each entry: (benchmark_name, builder_fn, min_qubits_supported)
# Minimum qubit counts come from each benchmark's source — most demand n>=2,
# the QEC codes need n>=3 data qubits to be non-trivial.
BENCHMARKS: list[tuple[str, Callable[[int], tuple], int]] = [
    ("ghz", _build_ghz, 2),
    ("ham_sim", _build_ham_sim, 2),
    ("mermin_bell", _build_mermin_bell, 3),
    ("phase_code", _build_phase_code, 3),
    ("bit_code", _build_bit_code, 3),
    ("qaoa_fermionic", _build_qaoa_fermionic, 4),
    ("qaoa_vanilla", _build_qaoa_vanilla, 4),
    ("vqe_proxy", _build_vqe_proxy, 4),
]


class SupermarqLoader(BenchmarkLoader):
    """Iterates SupermarQ's 8 application benchmarks across a qubit sweep."""

    source = "supermarq"

    def iter_circuits(
        self,
        min_qubits: int,
        max_qubits: int,
    ) -> Iterator[BenchmarkCircuit]:
        from supermarq.converters import cirq_to_qiskit

        for name, builder, suite_min in BENCHMARKS:
            n_lo = max(min_qubits, suite_min)
            for n in range(n_lo, max_qubits + 1):
                try:
                    cirq_c, qubits = builder(n)
                    qc: QuantumCircuit = cirq_to_qiskit(cirq_c, qubits)
                except Exception as e:
                    logger.debug(
                        f"supermarq skip {name} n={n}: {type(e).__name__}: {e}"
                    )
                    continue

                if qc.num_qubits < min_qubits or qc.num_qubits > max_qubits:
                    # PhaseCode/BitCode emit 2n-1 qubits — the requested
                    # `n` is data-qubit count, not total qubit count, so the
                    # final circuit can overshoot max_qubits. Filter here.
                    continue

                yield BenchmarkCircuit(
                    circuit=qc,
                    source=self.source,
                    benchmark_name=f"{name}_n{qc.num_qubits}",
                    num_qubits=qc.num_qubits,
                )
