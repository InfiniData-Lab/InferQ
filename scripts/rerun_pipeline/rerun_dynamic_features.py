#!/usr/bin/env python3
"""
Rerun Dynamic Features Script

CLI tool to rerun dynamic feature extraction (entropy, sparsity) from saved statevector simulations.
This script processes circuits that already have statevector_saved simulation data and extracts/updates
the dynamic features (shannon_entropy, von_neumann_entropy, sparsity) without re-running simulations.

The implementation lives in ``rerun_cli``; this entry point pins its mode so
the historical flags, prompts and log file are unchanged.
"""

import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from scripts.rerun_pipeline.circuit_processor import DynamicFeatureProcessor  # noqa: F401
from scripts.rerun_pipeline.rerun_cli import main as run_cli


def main():
    """Main entry point"""
    run_cli("dynamic")


if __name__ == "__main__":
    main()
