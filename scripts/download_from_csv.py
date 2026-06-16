import argparse
import csv
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Download circuits from hashes listed in a CSV file."
    )

    parser.add_argument(
        "--input-csv",
        required=True,
        help="Path to input CSV file containing a 'RowKey' column.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where downloaded circuits will be saved.",
    )

    parser.add_argument(
        "--script",
        default="scripts/download_circuits_by_hash.py",
        help="Path to download_circuits_by_hash.py script.",
    )

    args = parser.parse_args()

    csv_path = Path(args.input_csv)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Read hashes from CSV
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if "RowKey" not in reader.fieldnames:
            raise ValueError(
                f"'RowKey' column not found in CSV. "
                f"Columns: {reader.fieldnames}"
            )

        hashes = [row["RowKey"] for row in reader]

    if not hashes:
        raise ValueError("No hashes found in CSV.")

    # Use the exact same Python interpreter currently running this script
    cmd = [
        sys.executable,
        args.script,
        *hashes,
        "--output-dir",
        args.output_dir,
    ]

    print("Running command:")
    print(" ".join(cmd))

    # Execute
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()