"""
Upload all local circuits to Azure Blob Storage and Table Storage.

This script scans the local circuits directory, reads each circuit and its metadata,
then uploads both to Azure services:
- Circuit QPY files → Azure Blob Storage
- Circuit metadata → Azure Table Storage
"""

import json
import logging
import shutil
import sys
from pathlib import Path

from tqdm import tqdm

from inferq import paths
from inferq.config import get_storage_config
from inferq.remote.blob import upload_circuit_blob

# Import Azure utilities
from inferq.remote.connection import AzureConnection
from inferq.remote.table import save_circuit_metadata_to_table
from inferq.storage.qpy import load_circuit

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(paths.log_file('upload_circuits_to_azure.log'))
    ]
)
logger = logging.getLogger(__name__)


def load_circuit_from_qpy(qpy_path: Path):
    """Load a quantum circuit from a QPY file."""
    try:
        return load_circuit(qpy_path)
    except Exception as e:
        logger.error(f"Failed to load circuit from {qpy_path}: {e}")
        return None


def load_metadata(meta_path: Path):
    """Load circuit metadata from JSON file."""
    try:
        with open(meta_path) as f:
            metadata = json.load(f)
        return metadata
    except Exception as e:
        logger.error(f"Failed to load metadata from {meta_path}: {e}")
        return None


def discover_circuits(circuits_dir: Path):
    """
    Discover all circuit directories in the circuits folder.
    Each circuit directory should contain:
    - circuit.qpy (the quantum circuit)
    - meta.json (circuit metadata)
    
    Returns:
        List of tuples: [(circuit_dir, circuit_id), ...]
    """
    circuit_dirs = []
    
    if not circuits_dir.exists():
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return circuit_dirs
    
    # Iterate through all subdirectories (circuit hash directories)
    for item in circuits_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            # Check if it contains the required files
            qpy_file = item / "circuit.qpy"
            meta_file = item / "meta.json"
            
            if qpy_file.exists() and meta_file.exists():
                circuit_id = item.name
                circuit_dirs.append((item, circuit_id))
                logger.debug(f"Found circuit: {circuit_id}")
            else:
                logger.warning(f"Skipping incomplete circuit directory: {item.name}")
    
    logger.info(f"Discovered {len(circuit_dirs)} circuits")
    return circuit_dirs


def upload_circuit(circuit_dir: Path, circuit_id: str, azure_conn: AzureConnection, dry_run: bool = False, delete_after_upload: bool = False):
    """
    Upload a single circuit to Azure.
    
    Args:
        circuit_dir: Path to the circuit directory
        circuit_id: Circuit hash/ID
        azure_conn: Azure connection object
        dry_run: If True, only simulate the upload
        delete_after_upload: If True, delete local circuit folder after successful upload
        
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"Processing circuit: {circuit_id}")
    
    # Load circuit files
    qpy_file = circuit_dir / "circuit.qpy"
    meta_file = circuit_dir / "meta.json"
    
    # Load metadata
    metadata = load_metadata(meta_file)
    if metadata is None:
        logger.error(f"Failed to load metadata for {circuit_id}")
        return False
    
    # Load circuit
    circuit = load_circuit_from_qpy(qpy_file)
    if circuit is None:
        logger.error(f"Failed to load circuit for {circuit_id}")
        return False
    
    if dry_run:
        logger.info(f"[DRY RUN] Would upload circuit {circuit_id} ({circuit.num_qubits} qubits, depth {circuit.depth()})")
        return True
    
    try:
        # Upload circuit to Blob Storage
        logger.info(f"Uploading circuit {circuit_id} to Blob Storage...")
        blob_url = upload_circuit_blob(
            azure_conn.get_container_client(),
            circuit,
            circuit_id,
            serialization_method="qpy"
        )
        logger.info(f"✓ Circuit uploaded to blob: {blob_url}")
        
        # Add blob URL to metadata
        metadata['blob_url'] = blob_url
        metadata['qpy_sha256'] = circuit_id  # Ensure hash is in metadata
        
        # Upload metadata to Table Storage
        logger.info(f"Uploading metadata for {circuit_id} to Table Storage...")
        success = save_circuit_metadata_to_table(
            azure_conn.get_circuits_table_client(),
            metadata
        )
        
        if success:
            logger.info(f"✓ Circuit {circuit_id} uploaded successfully")
            
            # Delete local folder if requested
            if delete_after_upload and not dry_run:
                try:
                    shutil.rmtree(circuit_dir)
                    logger.info(f"🗑️  Deleted local folder: {circuit_dir.name}")
                except Exception as e:
                    logger.warning(f"⚠ Failed to delete local folder {circuit_dir.name}: {e}")
                    # Don't fail the upload if deletion fails
            
            return True
        else:
            logger.error(f"✗ Failed to upload metadata for {circuit_id}")
            return False
            
    except Exception as e:
        logger.error(f"✗ Failed to upload circuit {circuit_id}: {e}")
        return False


def upload_all_circuits(circuits_dir: Path, dry_run: bool = False, skip_existing: bool = True, delete_after_upload: bool = False):
    """
    Upload all circuits from the local circuits directory to Azure.
    
    Args:
        circuits_dir: Path to the circuits directory
        dry_run: If True, only simulate the upload
        skip_existing: If True, skip circuits that already exist in Azure
        delete_after_upload: If True, delete local circuit folders after successful upload
        
    Returns:
        dict: Statistics about the upload process
    """
    logger.info("=" * 80)
    logger.info("Starting bulk circuit upload to Azure")
    logger.info("=" * 80)
    
    # Initialize Azure connection
    logger.info("Connecting to Azure...")
    try:
        azure_conn = AzureConnection()
        logger.info("✓ Azure connection established")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Azure: {e}")
        return None
    
    # Discover all circuits
    logger.info(f"Scanning circuits directory: {circuits_dir}")
    circuit_dirs = discover_circuits(circuits_dir)
    
    if not circuit_dirs:
        logger.warning("No circuits found to upload")
        return {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
    
    # Upload each circuit
    stats = {
        'total': len(circuit_dirs),
        'successful': 0,
        'failed': 0,
        'skipped': 0,
        'deleted': 0
    }
    
    logger.info(f"Starting upload of {stats['total']} circuits...")
    
    with tqdm(total=stats['total'], desc="Uploading circuits") as pbar:
        for circuit_dir, circuit_id in circuit_dirs:
            try:
                # Check if circuit already exists in Azure (if skip_existing is True)
                if skip_existing and not dry_run:
                    try:
                        # Try to fetch metadata from table
                        from inferq.remote.table import get_circuit_metadata_from_table
                        existing = get_circuit_metadata_from_table(
                            azure_conn.get_circuits_table_client(),
                            circuit_id
                        )
                        if existing:
                            logger.info(f"⊘ Circuit {circuit_id} already exists in Azure, skipping")
                            stats['skipped'] += 1
                            pbar.update(1)
                            continue
                    except Exception as e:
                        logger.debug(f"Circuit {circuit_id} not found in Azure (will upload): {e}")
                
                # Upload the circuit
                success = upload_circuit(circuit_dir, circuit_id, azure_conn, dry_run, delete_after_upload)
                
                if success:
                    stats['successful'] += 1
                    if delete_after_upload and not dry_run:
                        stats['deleted'] += 1
                else:
                    stats['failed'] += 1
                    
            except Exception as e:
                logger.error(f"✗ Unexpected error uploading circuit {circuit_id}: {e}")
                stats['failed'] += 1
            
            pbar.update(1)
    
    # Print summary
    logger.info("=" * 80)
    logger.info("Upload Summary")
    logger.info("=" * 80)
    logger.info(f"Total circuits: {stats['total']}")
    logger.info(f"Successfully uploaded: {stats['successful']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Skipped (already exist): {stats['skipped']}")
    if delete_after_upload:
        logger.info(f"Local folders deleted: {stats['deleted']}")
    logger.info("=" * 80)
    
    return stats


def main():
    """Main entry point for the upload script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Upload all local circuits to Azure Blob Storage and Table Storage"
    )
    parser.add_argument(
        '--circuits-dir',
        type=str,
        default=None,
        help='Path to circuits directory (default: from config)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate the upload without actually uploading'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Upload all circuits even if they already exist in Azure (overwrite)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--delete-after-upload',
        action='store_true',
        help='Delete local circuit folders after successful upload to Azure (saves disk space)'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Get circuits directory
    if args.circuits_dir:
        circuits_dir = Path(args.circuits_dir)
    else:
        storage_config = get_storage_config()
        circuits_dir = Path(storage_config['local_circuits_dir'])
    
    logger.info(f"Using circuits directory: {circuits_dir}")
    
    # Warn if delete option is used
    if args.delete_after_upload and not args.dry_run:
        logger.warning("⚠️  DELETE MODE: Local circuit folders will be deleted after successful upload!")
        logger.warning("⚠️  Make sure you have backups or can regenerate these circuits!")
    
    # Run upload
    skip_existing = not args.force
    stats = upload_all_circuits(
        circuits_dir=circuits_dir,
        dry_run=args.dry_run,
        skip_existing=skip_existing,
        delete_after_upload=args.delete_after_upload
    )
    
    # Exit with appropriate code
    if stats:
        if stats['failed'] > 0:
            sys.exit(1)  # Error occurred
        else:
            sys.exit(0)  # Success
    else:
        sys.exit(1)  # Connection failed


if __name__ == "__main__":
    main()
