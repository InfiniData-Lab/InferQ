import os
import sys
import argparse
import pandas as pd
import logging
import shutil
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
import qiskit.qpy

# Add project root to path
# This is needed because the script is inside scripts/azure/
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.azure_connection import AzureConnection
from utils.blob_storage import download_circuit_blob
from config import PipelineConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("download_circuits.log")],
)
logger = logging.getLogger(__name__)


def get_blob_path_from_url(blob_url, container_name):
    """
    Extracts the blob path from the full blob URL.
    Assumes URL format: https://<account>.blob.core.windows.net/<container>/<path>
    """
    parsed = urlparse(blob_url)
    path = parsed.path
    # path starts with /, so it's /<container>/<blob_path>
    # We want <blob_path>

    # Remove leading slash
    if path.startswith("/"):
        path = path[1:]

    # Remove container name
    if path.startswith(container_name + "/"):
        return path[len(container_name) + 1 :]

    return path


def download_circuits(data_dir, output_dir, limit=None):
    """
    Downloads circuits listed in parquet files in data_dir to output_dir.
    """
    # Ensure output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")

    # Initialize Azure connection
    try:
        azure_conn = AzureConnection()
        container_client = azure_conn.container_client
        container_name = container_client.container_name
        logger.info(f"Connected to Azure Blob Storage container: {container_name}")
    except Exception as e:
        logger.error(f"Failed to connect to Azure: {e}")
        return

    # Find parquet files
    parquet_files = sorted([f for f in os.listdir(data_dir) if f.endswith(".parquet")])
    if not parquet_files:
        logger.warning(f"No parquet files found in {data_dir}")
        return

    logger.info(f"Found {len(parquet_files)} parquet files.")

    count = 0

    for p_file in parquet_files:
        if limit and count >= limit:
            break

        file_path = os.path.join(data_dir, p_file)
        logger.info(f"Processing {file_path}...")

        try:
            df = pd.read_parquet(file_path)
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            continue

        # Check if required columns exist
        if "blob_url" not in df.columns:
            logger.warning(f"'blob_url' column not found in {p_file}. Skipping.")
            continue

        # Iterate over rows
        for _, row in tqdm(
            df.iterrows(), total=len(df), desc=f"Downloading from {p_file}"
        ):
            if limit and count >= limit:
                break

            blob_url = row["blob_url"]
            if pd.isna(blob_url):
                continue

            serialization_method = row.get("serialization_method", "qpy")
            if pd.isna(serialization_method):
                serialization_method = "qpy"  # Default

            # Extract blob path
            blob_path = get_blob_path_from_url(blob_url, container_name)

            # Determine local file path
            # We can use the blob path structure or flatten it.
            # Blob path is usually XX/hash.qpy
            # Let's keep the structure to avoid collisions and too many files in one dir
            local_file_path = os.path.join(output_dir, blob_path)
            local_file_dir = os.path.dirname(local_file_path)

            if not os.path.exists(local_file_dir):
                os.makedirs(local_file_dir)

            if os.path.exists(local_file_path):
                # Skip if already exists
                # logger.debug(f"File {local_file_path} already exists. Skipping.")
                count += 1
                continue

            # Check if it exists in the main circuits directory (cache)
            # This avoids re-downloading if we already have it in the main repo
            config = PipelineConfig()
            main_circuits_dir = str(config.circuits_dir)

            # Only check if output_dir is different from main_circuits_dir
            # We need to normalize paths to compare them correctly
            if os.path.abspath(output_dir) != os.path.abspath(main_circuits_dir):
                main_file_path = os.path.join(main_circuits_dir, blob_path)
                if os.path.exists(main_file_path):
                    try:
                        shutil.copy2(main_file_path, local_file_path)
                        # logger.info(f"Copied from local cache: {blob_path}")
                        count += 1
                        continue
                    except Exception as e:
                        logger.warning(
                            f"Failed to copy from cache {main_file_path}: {e}"
                        )

            try:
                # Download circuit
                qc = download_circuit_blob(
                    container_client, blob_path, serialization_method
                )

                # Save locally
                # We always save as QPY locally for consistency if possible,
                # or just write the bytes if we want to preserve exact format.
                # But download_circuit_blob returns a QuantumCircuit object.
                # So we should serialize it to QPY.

                with open(local_file_path, "wb") as f:
                    qiskit.qpy.dump(qc, f)

                count += 1

            except Exception as e:
                logger.error(f"Failed to download/save circuit {blob_path}: {e}")
                continue

    logger.info(f"Download complete. Total circuits processed: {count}")


if __name__ == "__main__":
    config = PipelineConfig()
    
    # Define default output directory relative to project root
    project_root_path = Path(__file__).resolve().parent.parent.parent
    default_output_dir = project_root_path / "data" / "downloaded_circuits_from_metadata"
    default_data_dir = project_root_path / "data" / "fetched_circuit_metadata"

    parser = argparse.ArgumentParser(
        description="Download circuits from Azure Blob Storage based on fetched metadata."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save downloaded circuits.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(default_data_dir),
        help="Directory containing parquet files with circuit metadata.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of circuits to download.",
    )

    args = parser.parse_args()

    output_dir = args.output_dir
    limit = args.limit
    data_dir = args.data_dir

    # Interactive prompts if arguments are not provided
    if output_dir is None:
        try:
            user_input = input(
                f"Enter output directory [default: {str(default_output_dir)}]: "
            ).strip()
            output_dir = user_input if user_input else str(default_output_dir)
        except EOFError:
            # Handle non-interactive environments gracefully
            output_dir = str(default_output_dir)

    if limit is None:
        try:
            user_input = input(
                "Enter number of circuits to download (or press Enter for all): "
            ).strip()
            if user_input:
                try:
                    limit = int(user_input)
                except ValueError:
                    print("Invalid number. Defaulting to all.")
                    limit = None
            else:
                limit = None
        except EOFError:
            limit = None

    print(f"Source directory: {data_dir}")
    print(f"Destination directory: {output_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")

    download_circuits(data_dir, output_dir, limit)
