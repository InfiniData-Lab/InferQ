"""
Quantum Circuit Simulation Module

This module provides comprehensive quantum circuit simulation capabilities
using various methods available in Qiskit, including:

- Statevector simulation
- Matrix Product State (MPS) simulation  
- Unitary simulation
- Density matrix simulation
- Stabilizer simulation
- Extended stabilizer simulation
- QASM simulation

Classes:
    QuantumSimulator: Main simulator class supporting all methods
    SimulationAnalyzer: Analysis and comparison utilities
    SimulationMethod: Enumeration of available simulation methods

Functions:
    process_simulation_data_for_features: Reduce raw simulation output to features
    extract_essential_simulation_data: Trim simulation results to stored fields
    benchmark_simulation_methods: Comprehensive benchmarking utility
"""

from .simulate import QuantumSimulator, SimulationMethod
from .lib.metrics import SimulationMetrics
from .lib.analyzer import SimulationAnalyzer
from .lib.processor import (
    process_simulation_data_for_features, 
    extract_essential_simulation_data
)
from .lib.benchmark import benchmark_simulation_methods

__all__ = [
    'QuantumSimulator',
    'SimulationMethod', 
    'SimulationAnalyzer',
    'SimulationMetrics',
    'process_simulation_data_for_features',
    'extract_essential_simulation_data',
    'benchmark_simulation_methods'
]