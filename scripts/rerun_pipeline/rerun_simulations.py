#!/usr/bin/env python3
"""
Rerun Simulations Script

CLI tool to rerun quantum simulations on existing circuits.

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
    run_cli("simulations")


if __name__ == "__main__":
    main()
