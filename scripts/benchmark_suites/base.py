"""Common types for benchmark-suite loaders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from qiskit import QuantumCircuit


@dataclass(frozen=True)
class BenchmarkCircuit:
    """A single benchmark circuit with its source-suite tag.

    Attributes:
        circuit: Qiskit `QuantumCircuit` ready for feature extraction / simulation.
        source: Suite identifier — "mqt", "supermarq", or "qasmbench".
        benchmark_name: Stable name within the suite (e.g. "ghz", "ham_sim", "adder_n4").
        num_qubits: Convenience copy of `circuit.num_qubits` (set at construction
            so callers can filter without instantiating circuits they'll skip).
    """

    circuit: QuantumCircuit
    source: str
    benchmark_name: str
    num_qubits: int


class BenchmarkLoader(ABC):
    """Abstract loader yielding benchmark circuits from a single suite."""

    #: Suite identifier. Subclasses must override.
    source: str = ""

    @abstractmethod
    def iter_circuits(
        self,
        min_qubits: int,
        max_qubits: int,
    ) -> Iterator[BenchmarkCircuit]:
        """Yield circuits whose qubit counts lie in `[min_qubits, max_qubits]`.

        Loaders should yield lazily (one circuit at a time) so the caller can
        process and discard each before constructing the next — this matters
        because some suites have circuits with hundreds of qubits that we
        skip without ever instantiating.
        """
        raise NotImplementedError
