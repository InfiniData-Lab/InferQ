#!/usr/bin/env python3
"""Download every blob from an anonymous public container, byte-for-byte.

The implementation lives in ``inferq.transfer.download_circuits`` (mode
``public``); this entry point pins the mode. The container URL used to be a
``None`` placeholder edited in by hand before each run, so it is now a required
argument.
"""

import argparse
from pathlib import Path

from inferq.transfer.download_circuits import configure_logging, run_public


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download all blobs from a public Azure container anonymously."
    )
    parser.add_argument(
        "--container-url", required=True, help="Full URL of the public container."
    )
    parser.add_argument(
        "--output-dir", default="downloaded_circuits_public", help="Output directory"
    )
    args = parser.parse_args()

    print(f"Target Container: {args.container_url}")
    print(f"Target Directory: {Path(args.output_dir).absolute()}")

    configure_logging("public")
    run_public(args.container_url, args.output_dir)


if __name__ == "__main__":
    main()
