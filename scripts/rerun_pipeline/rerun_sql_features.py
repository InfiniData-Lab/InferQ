#!/usr/bin/env python3
"""
Rerun SQL Features Script

CLI tool to extract SQL features from existing circuits without running simulations.
"""

import os
import sys
import argparse
import logging
import multiprocessing

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from utils.azure_connection import AzureConnection
from config import PipelineConfig

from checkpoint_manager import CheckpointManager
from circuit_processor import SQLFeatureProcessor
from folder_processor import FolderProcessor
from orchestrator import PipelineOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_sql_features.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)


def process_folder_wrapper(folder_path: str, processed_hashes: set, 
                          checkpoints_dir: str) -> list:
    """
    Wrapper function for processing a folder with SQL feature extraction.
    This runs in a worker process.
    
    Args:
        folder_path: Path to folder
        processed_hashes: Set of processed hashes
        checkpoints_dir: Checkpoint directory
        
    Returns:
        List of results
    """
    try:
        # Initialize components in worker process
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        
        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = SQLFeatureProcessor()
        
        folder_processor = FolderProcessor(
            circuit_processor,
            table_client,
            checkpoint_manager
        )
        
        return folder_processor.process_folder(folder_path, processed_hashes)
        
    except Exception as e:
        logger.error(f"Failed to process folder {folder_path}: {e}")
        return []


def main():
    """Main entry point"""
    config = PipelineConfig()
    
    parser = argparse.ArgumentParser(
        description="Extract SQL features from circuits in parallel and update Azure Table."
    )
    parser.add_argument(
        "--circuits-dir", type=str, default=None,
        help="Directory containing circuits."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of circuits to process."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose output."
    )
    parser.add_argument(
        "--checkpoints-dir", type=str, default="checkpoints_sql_features",
        help="Directory to store processed circuit hashes per folder."
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Number of worker processes."
    )
    
    args = parser.parse_args()
    
    # Get or prompt for arguments
    circuits_dir = args.circuits_dir
    if circuits_dir is None:
        default_dir = str(config.circuits_dir)
        try:
            user_input = input(
                f"Enter circuits directory [default: {default_dir}]: "
            ).strip()
            circuits_dir = user_input if user_input else default_dir
        except EOFError:
            circuits_dir = default_dir
    
    limit = args.limit
    if limit is None:
        try:
            user_input = input(
                "Enter number of circuits to process (or press Enter for all): "
            ).strip()
            if user_input:
                try:
                    limit = int(user_input)
                except ValueError:
                    print("Invalid number. Defaulting to all.")
                    limit = None
        except EOFError:
            pass
    
    workers = args.workers
    if workers is None:
        try:
            default_workers = max(1, multiprocessing.cpu_count() - 1)
            user_input = input(
                f"Enter number of workers [default: {default_workers}]: "
            ).strip()
            workers = int(user_input) if user_input else default_workers
        except:
            workers = None
    
    checkpoints_dir = args.checkpoints_dir
    verbose = args.verbose
    
    # Display configuration
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    
    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return
    
    # Check if InfiniQuantumSim is available
    from circuit_processor import INFINI_QUANTUM_AVAILABLE
    if not INFINI_QUANTUM_AVAILABLE:
        logger.error("InfiniQuantumSim is required but not installed. Please install it first.")
        return
    
    # Initialize Azure connection
    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        logger.info("Connected to Azure Table Storage")
    except Exception as e:
        logger.error(f"Failed to connect to Azure: {e}")
        return
    
    # Initialize components
    checkpoint_manager = CheckpointManager(checkpoints_dir)
    orchestrator = PipelineOrchestrator(circuits_dir, checkpoint_manager, table_client)
    
    # Create wrapper with bound parameters
    def process_folder_bound(folder_path, processed_hashes):
        return process_folder_wrapper(folder_path, processed_hashes, checkpoints_dir)
    
    # Run pipeline
    total_updated = orchestrator.run_parallel(
        process_folder_bound,
        num_workers=workers,
        limit=limit,
        verbose=verbose
    )
    
    logger.info(f"SQL feature extraction complete. Total circuits updated: {total_updated}")


if __name__ == "__main__":
    main()
