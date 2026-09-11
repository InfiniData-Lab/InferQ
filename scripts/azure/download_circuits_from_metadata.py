#!/usr/bin/env python3
"""Download circuits named by the fetched parquet metadata.

The implementation lives in ``download_circuits`` (mode ``metadata``); this
entry point pins the mode so the historical flags and interactive prompts are
unchanged.
"""

import argparse
import sys
from pathlib import Path

INFERQ_ROOT = Path(__file__).resolve().parents[2]
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from scripts.azure.download_circuits import (  # noqa: E402
    DEFAULT_METADATA_DIR,
    DEFAULT_OUTPUT_DIRS,
    configure_logging,
    prompt_for_limit,
    prompt_for_output_dir,
    run_metadata,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download circuits from Azure Blob Storage based on fetched metadata."
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory to save downloaded circuits.",
    )
    parser.add_argument(
        "--data-dir", type=str, default=str(DEFAULT_METADATA_DIR),
        help="Directory containing parquet files with circuit metadata.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of circuits to download.",
    )
    args = parser.parse_args()

    default_output_dir = DEFAULT_OUTPUT_DIRS["metadata"]
    output_dir = args.output_dir or prompt_for_output_dir(default_output_dir)
    limit = args.limit if args.limit is not None else prompt_for_limit()

    print(f"Source directory: {args.data_dir}")
    print(f"Destination directory: {output_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")

    configure_logging("metadata")
    run_metadata(args.data_dir, output_dir, limit)


if __name__ == "__main__":
    main()
