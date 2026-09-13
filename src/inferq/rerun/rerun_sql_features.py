#!/usr/bin/env python3
"""
Rerun SQL Features Script

CLI tool to extract SQL features from existing circuits without running simulations.

The implementation lives in ``rerun_cli``; this entry point pins its mode so
the historical flags, prompts and log file are unchanged.
"""


from inferq.rerun.rerun_cli import main as run_cli


def main():
    """Main entry point"""
    run_cli("sql")


if __name__ == "__main__":
    main()
