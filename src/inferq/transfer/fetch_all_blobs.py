#!/usr/bin/env python3
"""Fetch every circuit directly from the configured object store.

The implementation lives in ``download_circuits`` (mode ``all``); this entry
point pins the mode so the historical flags and interactive prompts are
unchanged.
"""

import argparse

from inferq.transfer.download_circuits import (
    DEFAULT_OUTPUT_DIRS,
    configure_logging,
    prompt_for_limit,
    prompt_for_output_dir,
    run_all,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch all circuits directly from cloud object storage."
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory to save downloaded circuits.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of circuits to download.",
    )
    args = parser.parse_args()

    default_output_dir = DEFAULT_OUTPUT_DIRS["all"]
    output_dir = args.output_dir or prompt_for_output_dir(default_output_dir)
    limit = args.limit if args.limit is not None else prompt_for_limit()

    print(f"Destination directory: {output_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")

    configure_logging("all")
    run_all(output_dir, limit)


if __name__ == "__main__":
    main()
