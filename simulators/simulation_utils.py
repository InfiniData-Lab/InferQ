"""
Utility functions for quantum circuit simulation analysis and comparison.
This module now re-exports refactored components from .lib
"""

from .lib.metrics import SimulationMetrics
from .lib.analyzer import SimulationAnalyzer
from .lib.processor import (
    process_simulation_data_for_features, 
    extract_essential_simulation_data
)
from .lib.benchmark import benchmark_simulation_methods
