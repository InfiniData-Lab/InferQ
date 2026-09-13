#!/usr/bin/env python3
"""
Rerun Simulations Script

CLI tool to rerun quantum simulations on existing circuits.

The implementation lives in ``rerun_cli``; this entry point pins its mode so
the historical flags, prompts and log file are unchanged.
"""


from inferq.rerun.rerun_cli import main as run_cli


def main():
    """Main entry point"""
    run_cli("simulations")


if __name__ == "__main__":
    main()
