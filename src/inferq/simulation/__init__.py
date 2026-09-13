"""Quantum circuit simulation.

Simulation backends wrap Qiskit Aer (statevector, matrix product state, unitary,
density matrix, stabilizer, extended stabilizer, QASM) and, when InfiniQuantumSim
is installed, the tensor-network-to-SQL lowering path.

Attribute access is lazy (PEP 562): importing this package does not import Qiskit
or Aer, so ``inferq.simulation.SimulationMethod`` stays cheap for callers that only
need the enum. Sub-modules also remain importable directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

_EXPORTS = {
    "QuantumSimulator": "simulate",
    "SimulationMethod": "types",
    "SimulationMetrics": "metrics",
    "SimulationAnalyzer": "analyzer",
    "DynamicFeatureExtractor": "dynamic_feature_extractor",
    "INFINI_QUANTUM_AVAILABLE": "infiniquantum",
    "process_simulation_data_for_features": "processor",
    "extract_essential_simulation_data": "processor",
    "sql_artifact_from_results": "processor",
    "benchmark_simulation_methods": "benchmark",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if TYPE_CHECKING:  # pragma: no cover - import-time cost is the whole point
    from .analyzer import SimulationAnalyzer
    from .benchmark import benchmark_simulation_methods
    from .dynamic_feature_extractor import DynamicFeatureExtractor
    from .infiniquantum import INFINI_QUANTUM_AVAILABLE
    from .metrics import SimulationMetrics
    from .processor import (
        extract_essential_simulation_data,
        process_simulation_data_for_features,
        sql_artifact_from_results,
    )
    from .simulate import QuantumSimulator
    from .types import SimulationMethod
