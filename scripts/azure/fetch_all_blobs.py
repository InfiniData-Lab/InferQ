import os
import sys
import argparse
import logging
from tqdm import tqdm
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
    handlers=[logging.StreamHandler(), logging.FileHandler("fetch_all_blobs.log")],
)
logger = logging.getLogger(__name__)


def fetch_all_blobs(output_dir, limit=None):
    """
    Fetches all blobs from the Azure storage container and saves them locally.
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

    logger.info("Listing blobs...")
    try:
        # List all blobs with metadata
        blobs = container_client.list_blobs(include=["metadata"])
    except Exception as e:
        logger.error(f"Failed to list blobs: {e}")
        return

    count = 0

    # We can't easily get the total count without iterating, so tqdm might not show total initially
    # or we can convert to list first if it's not too huge.
    # Let's just iterate.

    for blob in tqdm(blobs, desc="Downloading blobs"):
        if limit and count >= limit:
            break

        blob_path = blob.name
        metadata = blob.metadata or {}
        serialization_method = metadata.get("format", "qpy")

        # Determine local file path
        # Blob path is usually XX/hash.ext
        # We'll mirror the structure
        local_file_path = os.path.join(output_dir, blob_path)

        # If the blob path doesn't have an extension or we are converting to qpy,
        # we might want to ensure it ends in .qpy if we are saving as qpy.
        # But let's stick to the blob name for the file structure,
        # UNLESS we are converting.
        # The previous script saved as QPY.

        # If we download and convert to QPY, we should probably change extension to .qpy
        base, ext = os.path.splitext(local_file_path)
        if ext != ".qpy":
            local_file_path = base + ".qpy"

        local_file_dir = os.path.dirname(local_file_path)

        if not os.path.exists(local_file_dir):
            os.makedirs(local_file_dir)

        if os.path.exists(local_file_path):
            # Skip if already exists
            # logger.debug(f"File {local_file_path} already exists. Skipping.")
            count += 1
            continue

        try:
            # Download circuit
            # download_circuit_blob handles deserialization based on method
            qc = download_circuit_blob(
                container_client, blob_path, serialization_method
            )

            # Save locally as QPY
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
    default_output_dir = project_root_path / "data" / "fetched_raw_blobs"

    parser = argparse.ArgumentParser(
        description="Fetch all circuits directly from Azure Blob Storage."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save downloaded circuits.",
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

    # Interactive prompts if arguments are not provided
    if output_dir is None:
        try:
            user_input = input(
                f"Enter output directory [default: {str(default_output_dir)}]: "
            ).strip()
            output_dir = user_input if user_input else str(default_output_dir)
        except EOFError:
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

    print(f"Destination directory: {output_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")

    fetch_all_blobs(output_dir, limit)
