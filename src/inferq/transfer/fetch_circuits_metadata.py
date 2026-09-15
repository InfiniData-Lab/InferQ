import argparse
import json
import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
from tqdm import tqdm

from inferq import paths
from inferq.remote import CIRCUITS_PARTITION, encode_cursor, get_circuit_metadata, get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(paths.log_file("fetch_circuits_metadata.log"))],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = str(paths.data_dir() / "fetched_circuit_metadata")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")
PAGE_SIZE = 1000  # The smallest page cap across providers (Azure Tables)


def ensure_output_dir():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logger.info(f"Created output directory: {OUTPUT_DIR}")


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Checkpoint file corrupted. Starting over.")
            return None
    return None


def save_checkpoint(cursor, file_counter, total_rows):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(
            {
                "cursor": cursor,
                "file_counter": file_counter,
                "total_rows": total_rows,
                "last_updated": datetime.now().isoformat(),
            },
            f,
        )


def checkpoint_cursor(checkpoint):
    """Read the resume cursor out of a checkpoint, old format included.

    Checkpoints written before the provider split stored a raw Azure
    continuation token under ``continuation_token``; wrap one of those into
    the neutral cursor format rather than making an operator restart a
    multi-hour export.
    """
    cursor = checkpoint.get("cursor")
    if cursor:
        return cursor
    legacy_token = checkpoint.get("continuation_token")
    if legacy_token:
        return encode_cursor({"continuation_token": legacy_token})
    return None


def fetch_circuit_by_id(circuit_id):
    """
    Fetches a single circuit entity by its RowKey (circuit_id).
    """
    try:
        conn = get_connection()

        logger.info(f"Fetching circuit with ID: {circuit_id}")
        metadata = get_circuit_metadata(conn.metadata, circuit_id)
        if metadata is None:
            logger.warning(f"Circuit not found: {circuit_id}")
            return None

        print(json.dumps(metadata, indent=4, default=str))
        return metadata

    except Exception as e:
        logger.error(f"Failed to fetch circuit {circuit_id}: {e}")
        return None


def fetch_data(export_csv: bool = False):
    ensure_output_dir()

    analysis_dir = str(paths.out_dir() / "analysis")
    csv_output_path = os.path.join(analysis_dir, "fetched_circuits.csv")
    
    if export_csv:
        if not os.path.exists(analysis_dir):
            os.makedirs(analysis_dir)
        # If starting fresh (no checkpoint) or if we want to ensure clean state, 
        # we might want to delete existing CSV. 
        # However, to be safe with checkpoints, we rely on append mode.
        # But if it's a new run (no checkpoint loaded later), we should probably reset it?
        # Logic below handles checking checkpoint.

    checkpoint = load_checkpoint()
    cursor = None
    file_counter = 0
    total_rows = 0

    if checkpoint:
        cursor = checkpoint_cursor(checkpoint)
        file_counter = checkpoint.get("file_counter", 0)
        total_rows = checkpoint.get("total_rows", 0)
        resume_msg = f"Resuming from checkpoint. File counter: {file_counter}, Rows fetched so far: {total_rows}"
        logger.info(resume_msg)
        print(resume_msg)
    else:
        logger.info("Starting new fetch job.")
        print("Starting new fetch job.")
        # If new job and exporting to CSV, clean up old CSV
        if export_csv and os.path.exists(csv_output_path):
            os.remove(csv_output_path)
            logger.info(f"Removed old CSV file: {csv_output_path}")

    try:
        conn = get_connection()

        logger.info(f"Scanning the '{CIRCUITS_PARTITION}' partition with page size {PAGE_SIZE}...")

        pages = conn.metadata.scan_records(
            CIRCUITS_PARTITION, page_size=PAGE_SIZE, cursor=cursor
        )

        # Iterate over pages
        for page in tqdm(pages, desc="Fetching pages", unit="page"):
            rows = [
                {
                    "PartitionKey": record.partition,
                    "RowKey": record.key,
                    "Timestamp": record.timestamp,
                    **record.fields,
                }
                for record in page.records
            ]

            if not rows:
                logger.info("Empty page received. Stopping.")
                break

            # Convert to DataFrame
            df = pd.DataFrame(rows)

            # Clean up data to avoid PyArrow errors
            # Replace string "None" with np.nan which PyArrow can handle in numeric columns
            df = df.replace("None", np.nan)

            # Save to Parquet
            output_file = os.path.join(
                OUTPUT_DIR, f"circuits_part_{file_counter:05d}.parquet"
            )

            # Ensure we handle potential data type issues for Parquet
            # Convert object columns that might contain mixed types to string if needed,
            # but pandas usually handles it.
            # Records can have different schemas per row on either provider,
            # so the frame may have sparse columns.
            # Parquet handles sparse data well.

            df.to_parquet(output_file, index=False)
            logger.info(f"Saved {len(rows)} rows to {output_file}")

            if export_csv:
                # Append to CSV
                # Check if file exists to determine if header is needed
                header = not os.path.exists(csv_output_path)
                df.to_csv(csv_output_path, mode="a", index=False, header=header)

            total_rows += len(rows)
            file_counter += 1

            # The cursor that resumes after this page
            if page.cursor:
                save_checkpoint(page.cursor, file_counter, total_rows)
            else:
                # No more pages
                logger.info("Fetching complete. No more pages.")
                print("Fetching complete. No more pages.")
                if os.path.exists(CHECKPOINT_FILE):
                    os.remove(CHECKPOINT_FILE)
                break

        logger.info(f"Total rows fetched: {total_rows}")
        print(f"Total rows fetched: {total_rows}")

    except Exception as e:
        logger.error(f"Error occurred during fetch: {e}")
        logger.info(
            "Progress has been saved to checkpoint. Run the script again to resume."
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch circuit data from the cloud metadata store.")
    parser.add_argument(
        "--id",
        type=str,
        help="Fetch a specific circuit by its ID (RowKey).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch all circuits with pagination and checkpointing.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Export all fetched data to a CSV file in 'analysis/' folder.",
    )

    args = parser.parse_args()

    # Interactive mode if no arguments provided
    if not args.id and not args.all:
        print("No arguments provided. Interactive mode:")
        print("1. Fetch all circuits")
        print("2. Fetch a specific circuit by ID")
        
        try:
            choice = input("Enter your choice (1/2): ").strip()
            if choice == "1":
                csv_input = input("Do you want to export everything to a CSV in analysis folder? (y/n): ").strip().lower()
                export_csv_flag = csv_input == 'y'
                fetch_data(export_csv=export_csv_flag)
            elif choice == "2":
                circuit_id = input("Enter Circuit ID (RowKey): ").strip()
                if circuit_id:
                    fetch_circuit_by_id(circuit_id)
                else:
                    print("No ID provided. Exiting.")
            else:
                print("Invalid choice. Exiting.")
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
    
    elif args.id:
        fetch_circuit_by_id(args.id)
    
    elif args.all:
        fetch_data(export_csv=args.csv)
