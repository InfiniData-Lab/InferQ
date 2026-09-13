#!/usr/bin/env python3
"""Download specific circuits by hash, flat into one directory.

The implementation lives in ``inferq.transfer.download_circuits`` (mode
``hashes``); this entry point pins the mode so the historical flags and output
layout are unchanged.
"""

import argparse

from inferq.transfer.download_circuits import configure_logging, run_hashes


def main() -> None:
    parser = argparse.ArgumentParser(description="Download specific circuits by hash.")
    parser.add_argument("hashes", nargs="+", help="List of circuit hashes to download")
    parser.add_argument(
        "--output-dir", default="downloaded_circuits", help="Output directory"
    )
    args = parser.parse_args()

    configure_logging("hashes")
    run_hashes(args.hashes, args.output_dir)


if __name__ == "__main__":
    main()
