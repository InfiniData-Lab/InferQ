"""Benchmark-suite circuit loaders for InferQ ingestion (standalone, not part of the merger).

These loaders pull `qiskit.QuantumCircuit` objects from established benchmark suites:
- MQT Bench (Quetschlich et al., 2023)
- SupermarQ (Tomesh et al., 2022)
- QASMBench (Li et al., 2022)

They are consumed by `scripts/ingest_benchmarks.py`, which feeds the resulting
circuits through the existing feature-extraction + simulation + storage pipeline
without modifying any pipeline code.
"""

from .base import BenchmarkCircuit, BenchmarkLoader
from .mqt_bench_loader import MQTBenchLoader
from .supermarq_loader import SupermarqLoader
from .qasmbench_loader import QASMBenchLoader

__all__ = [
    "BenchmarkCircuit",
    "BenchmarkLoader",
    "MQTBenchLoader",
    "SupermarqLoader",
    "QASMBenchLoader",
]
