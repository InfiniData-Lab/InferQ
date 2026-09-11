#!/usr/bin/env python3
"""Download circuits whose hashes are listed in a CSV column.

The implementation lives in ``scripts.azure.download_circuits`` (mode
``hashes``, ``--from-csv``); this entry point pins the mode so the historical
flags are unchanged. It used to shell out to ``download_circuits_by_hash.py``
via ``subprocess``, which is why it carried a ``--script`` flag; the call is now
in-process and that flag is gone.
"""

import argparse
import sys
from pathlib import Path

INFERQ_ROOT = Path(__file__).resolve().parents[1]
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from scripts.azure.download_circuits import configure_logging, run_hashes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download circuits from hashes listed in a CSV file."
    )
    parser.add_argument(
        "--input-csv", required=True,
        help="Path to input CSV file containing a 'RowKey' column.",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory where downloaded circuits will be saved.",
    )
    args = parser.parse_args()

    csv_path = Path(args.input_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    configure_logging("hashes")
    run_hashes([], args.output_dir, from_csv=csv_path)


if __name__ == "__main__":
    main()
