import os
import sys
import argparse
import logging
import qiskit.qpy
from pathlib import Path

# Add project root to path
# This script is in scripts/ so parent.parent is root
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Try imports
try:
    from utils.azure_connection import AzureConnection
    from utils.blob_storage import download_circuit_blob
except ImportError:
    # If specific utils import fails, try to see if we can import just 'utils'
    # Adjust path if in scripts/azure/ or similar
    if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
         sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from utils.azure_connection import AzureConnection
    from utils.blob_storage import download_circuit_blob

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def download_circuits(hashes, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")
    
    try:
        azure_conn = AzureConnection()
        container_client = azure_conn.container_client
        logger.info(f"Connected to Azure Blob Storage container: {container_client.container_name}")
    except Exception as e:
        logger.error(f"Failed to connect to Azure: {e}")
        return

    success_count = 0
    for h in hashes:
        h = h.strip()
        if not h:
            continue
            
        # Construct blob path: XX/hash.qpy
        # Assuming standard storage structure
        blob_path = f"{h[:2]}/{h}.qpy"
        local_file_path = os.path.join(output_dir, f"{h}.qpy")
        
        if os.path.exists(local_file_path):
            logger.info(f"Circuit {h} already exists at {local_file_path}")
            success_count += 1
            continue
            
        try:
            logger.info(f"Downloading {blob_path}...")
            qc = download_circuit_blob(container_client, blob_path, "qpy")
            
            with open(local_file_path, "wb") as f:
                qiskit.qpy.dump(qc, f)
            logger.info(f"Saved {h} to {local_file_path}")
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to download {h}: {e}")
            
    logger.info(f"Download process finished. Successfully downloaded/found: {success_count}/{len(hashes)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download specific circuits by hash.")
    parser.add_argument("hashes", nargs='+', help="List of circuit hashes to download")
    parser.add_argument("--output-dir", default="downloaded_circuits", help="Output directory")
    
    args = parser.parse_args()
    
    # Check if a single arg is passed and it's a file?
    # Keeping it simple: arguments are hashes.
    
    download_circuits(args.hashes, args.output_dir)
