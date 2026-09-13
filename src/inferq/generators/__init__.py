"""Quantum circuit generators.

Every generator subclasses :class:`~inferq.generators.base.Generator` and exposes a
uniform ``generate()`` entry point, so the composer and merger can treat state-prep
circuits and algorithm circuits interchangeably.
"""

from .algorithms.amplitude_estimation import AmplitudeEstimation
from .algorithms.deutsch_jozsa import DeutschJozsa
from .algorithms.grover_no_ancilla import GroverNoAncilla
from .algorithms.grover_v_chain import GroverVChain
from .algorithms.qaoa import QAOA
from .algorithms.qft import QFTGenerator
from .algorithms.qnn import QNN
from .algorithms.qpe import QPE
from .algorithms.qwalk import QuantumWalk
from .algorithms.vqe import VQEGenerator
from .base import Generator
from .merger import CircuitMerger, CompositionStep
from .state_prep.efficient_u2 import EfficientU2
from .state_prep.ghz import GHZ
from .state_prep.graph_state import GraphState
from .state_prep.random_circuit import RandomCircuit
from .state_prep.real_amplitudes import RealAmplitudes
from .state_prep.two_local import TwoLocal
from .state_prep.wstate import WState

__all__ = [
    "AmplitudeEstimation",
    "CircuitMerger",
    "CompositionStep",
    "DeutschJozsa",
    "EfficientU2",
    "GHZ",
    "Generator",
    "GraphState",
    "GroverNoAncilla",
    "GroverVChain",
    "QAOA",
    "QFTGenerator",
    "QNN",
    "QPE",
    "QuantumWalk",
    "RandomCircuit",
    "RealAmplitudes",
    "TwoLocal",
    "VQEGenerator",
    "WState",
]
