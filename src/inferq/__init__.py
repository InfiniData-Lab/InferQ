"""InferQ — generation, simulation and feature extraction for quantum-circuit datasets.

The pipeline generates quantum circuits, simulates them with Qiskit Aer and (when
installed) with InfiniQuantumSim's tensor-network-to-SQL lowering, extracts static,
graph and SQL features, and stores circuits content-addressed locally or in the cloud.

Attribute access is lazy (PEP 562), so ``import inferq`` costs almost nothing:
Qiskit, Aer and the cloud SDKs are imported only when a name that needs them is first
touched.

API tiers
---------
**Stable** — covered by semantic versioning: the generators, ``QuantumSimulator``,
the feature extractors, and :mod:`inferq.paths`.

**Provisional** — may change in a minor release: :mod:`inferq.pipeline`,
:mod:`inferq.transfer`, :mod:`inferq.rerun`, :mod:`inferq.datasets`.

**Internal** — no guarantees: anything underscore-prefixed, and any sub-module not
re-exported here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:  # pragma: no cover - trivial, and only the fallback is ever uncovered
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("inferq")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

# Public name -> the sub-module that defines it. Sub-modules listed as values of
# themselves are re-exported as modules, not attributes.
_EXPORTS: dict[str, str] = {
    # stable: generators
    "AmplitudeEstimation": "inferq.generators",
    "CircuitMerger": "inferq.generators",
    "CompositionStep": "inferq.generators",
    "DeutschJozsa": "inferq.generators",
    "EfficientU2": "inferq.generators",
    "GHZ": "inferq.generators",
    "Generator": "inferq.generators",
    "GraphState": "inferq.generators",
    "GroverNoAncilla": "inferq.generators",
    "GroverVChain": "inferq.generators",
    "QAOA": "inferq.generators",
    "QFTGenerator": "inferq.generators",
    "QNN": "inferq.generators",
    "QPE": "inferq.generators",
    "QuantumWalk": "inferq.generators",
    "RandomCircuit": "inferq.generators",
    "RealAmplitudes": "inferq.generators",
    "TwoLocal": "inferq.generators",
    "VQEGenerator": "inferq.generators",
    "WState": "inferq.generators",
    # stable: simulation
    "QuantumSimulator": "inferq.simulation",
    "SimulationMethod": "inferq.simulation",
    "SimulationMetrics": "inferq.simulation",
    # stable: storage identity
    "compute_circuit_hash": "inferq.storage",
    "load_circuit": "inferq.storage",
    "save_circuit_locally": "inferq.storage",
}

# Sub-packages reachable as ``inferq.<name>`` without an explicit import.
_SUBMODULES = frozenset(
    {
        "cli",
        "config",
        "datasets",
        "features",
        "generators",
        "paths",
        "pipeline",
        "remote",
        "rerun",
        "simulation",
        "sql",
        "storage",
        "transfer",
    }
)

__all__ = [*sorted(_EXPORTS), *sorted(_SUBMODULES), "__version__"]


def __getattr__(name: str):
    from importlib import import_module

    if name in _SUBMODULES:
        value = import_module(f".{name}", __name__)
    elif name in _EXPORTS:
        value = getattr(import_module(_EXPORTS[name]), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:  # pragma: no cover - keeps type checkers and IDEs informed
    from . import (
        cli,
        config,
        datasets,
        features,
        generators,
        paths,
        pipeline,
        remote,
        rerun,
        simulation,
        sql,
        storage,
        transfer,
    )
    from .generators import (
        GHZ,
        QAOA,
        QNN,
        QPE,
        AmplitudeEstimation,
        CircuitMerger,
        CompositionStep,
        DeutschJozsa,
        EfficientU2,
        Generator,
        GraphState,
        GroverNoAncilla,
        GroverVChain,
        QFTGenerator,
        QuantumWalk,
        RandomCircuit,
        RealAmplitudes,
        TwoLocal,
        VQEGenerator,
        WState,
    )
    from .simulation import QuantumSimulator, SimulationMethod, SimulationMetrics
    from .storage import compute_circuit_hash, load_circuit, save_circuit_locally
