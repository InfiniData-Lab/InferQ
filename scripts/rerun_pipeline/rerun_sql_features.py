#!/usr/bin/env python3
"""
Rerun SQL Features Script

CLI tool to extract SQL features from existing circuits without running simulations.

The implementation lives in ``rerun_cli``; this entry point pins its mode so
the historical flags, prompts and log file are unchanged.
"""

import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from scripts.rerun_pipeline.rerun_cli import main as run_cli


def main():
    """Main entry point"""
    run_cli("sql")


if __name__ == "__main__":
    main()
