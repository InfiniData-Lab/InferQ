"""Benchmark-suite circuit loaders and the dataset registry.

The loaders pull :class:`qiskit.QuantumCircuit` objects from established
benchmark suites -- MQT Bench (Quetschlich et al., 2023), SupermarQ (Tomesh
et al., 2022) and QASMBench (Li et al., 2022) -- and are consumed by
``inferq ingest``, which feeds them through the ordinary feature-extraction,
simulation and storage pipeline.

Nothing is vendored. :mod:`inferq.datasets.registry` names an immutable upstream
and a per-file sha256 for each corpus, and :func:`inferq.datasets.fetch.fetch`
downloads, verifies and unpacks it under ``$INFERQ_DATA_DIR``.

Attribute access is lazy: MQT Bench and SupermarQ are optional extras, so
importing this package must not require them to be installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

_EXPORTS = {
    "BenchmarkCircuit": "inferq.datasets.base",
    "BenchmarkLoader": "inferq.datasets.base",
    "DatasetSpec": "inferq.datasets.registry",
    "FetchError": "inferq.datasets.fetch",
    "MQTBenchLoader": "inferq.datasets.mqt_bench_loader",
    "QASMBenchLoader": "inferq.datasets.qasmbench_loader",
    "SupermarqLoader": "inferq.datasets.supermarq_loader",
    "VerificationResult": "inferq.datasets.registry",
    "available": "inferq.datasets.registry",
    "fetch": "inferq.datasets.fetch",
    "spec": "inferq.datasets.registry",
    "verify": "inferq.datasets.registry",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return __all__


if TYPE_CHECKING:  # pragma: no cover - import-time contract for type checkers
    from .base import BenchmarkCircuit, BenchmarkLoader
    from .fetch import FetchError, fetch
    from .mqt_bench_loader import MQTBenchLoader
    from .qasmbench_loader import QASMBenchLoader
    from .registry import DatasetSpec, VerificationResult, available, spec, verify
    from .supermarq_loader import SupermarqLoader
