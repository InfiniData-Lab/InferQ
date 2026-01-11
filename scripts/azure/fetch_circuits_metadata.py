import os
import sys
from pathlib import Path

# Add project root to sys.path to allow importing utils
# This is needed because the script is inside scripts/azure/
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import argparse
import json
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from tqdm import tqdm
from utils.azure_connection import AzureConnection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("fetch_circuits_metadata.log")],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = "data/fetched_circuit_metadata"
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")
PAGE_SIZE = 1000  # Azure Table Storage limit is 1000


def ensure_output_dir():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logger.info(f"Created output directory: {OUTPUT_DIR}")


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Checkpoint file corrupted. Starting over.")
            return None
    return None


def save_checkpoint(continuation_token, file_counter, total_rows):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(
            {
                "continuation_token": continuation_token,
                "file_counter": file_counter,
                "total_rows": total_rows,
                "last_updated": datetime.now().isoformat(),
            },
            f,
        )


def fetch_circuit_by_id(circuit_id):
    """
    Fetches a single circuit entity by its RowKey (circuit_id).
    """
    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.get_circuits_table_client()

        logger.info(f"Fetching circuit with ID: {circuit_id}")
        entity = table_client.get_entity(partition_key="circuits", row_key=circuit_id)

        print(json.dumps(dict(entity), indent=4, default=str))
        return entity

    except Exception as e:
        logger.error(f"Failed to fetch circuit {circuit_id}: {e}")
        return None


def fetch_data():
    ensure_output_dir()

    checkpoint = load_checkpoint()
    continuation_token = None
    file_counter = 0
    total_rows = 0

    if checkpoint:
        continuation_token = checkpoint.get("continuation_token")
        file_counter = checkpoint.get("file_counter", 0)
        total_rows = checkpoint.get("total_rows", 0)
        logger.info(
            f"Resuming from checkpoint. File counter: {file_counter}, Rows fetched so far: {total_rows}"
        )
    else:
        logger.info("Starting new fetch job.")

    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.get_circuits_table_client()

        logger.info(f"Querying Azure Table 'circuits' with page size {PAGE_SIZE}...")

        # query_entities returns an ItemPaged object
        query = table_client.query_entities(
            query_filter="PartitionKey eq 'circuits'", results_per_page=PAGE_SIZE
        )

        # Get iterator with continuation token if available
        pages = query.by_page(continuation_token=continuation_token)

        # Iterate over pages
        for page in tqdm(pages, desc="Fetching pages", unit="page"):
            # Convert page to list of dicts
            rows = [dict(item) for item in page]

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
            # Azure Table entities can have different schemas per row, so we might have sparse columns.
            # Parquet handles sparse data well.

            df.to_parquet(output_file, index=False)
            logger.info(f"Saved {len(rows)} rows to {output_file}")

            total_rows += len(rows)
            file_counter += 1

            # Get the continuation token for the NEXT page
            next_token = pages.continuation_token

            if next_token:
                save_checkpoint(next_token, file_counter, total_rows)
            else:
                # No more pages
                logger.info("Fetching complete. No more continuation token.")
                if os.path.exists(CHECKPOINT_FILE):
                    os.remove(CHECKPOINT_FILE)
                break

        logger.info(f"Total rows fetched: {total_rows}")

    except Exception as e:
        logger.error(f"Error occurred during fetch: {e}")
        logger.info(
            "Progress has been saved to checkpoint. Run the script again to resume."
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch circuit data from Azure Table Storage.")
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

    args = parser.parse_args()

    # Interactive mode if no arguments provided
    if not args.id and not args.all:
        print("No arguments provided. Interactive mode:")
        print("1. Fetch all circuits")
        print("2. Fetch a specific circuit by ID")
        
        try:
            choice = input("Enter your choice (1/2): ").strip()
            if choice == "1":
                fetch_data()
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
        fetch_data()
