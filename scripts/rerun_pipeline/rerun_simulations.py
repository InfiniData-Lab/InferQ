#!/usr/bin/env python3
"""
Rerun Simulations Script

CLI tool to rerun quantum simulations on existing circuits.
"""

import os
import sys
import argparse
import logging
import multiprocessing

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from utils.azure_connection import AzureConnection
from simulators.simulate import QuantumSimulator
from config import PipelineConfig

from checkpoint_manager import CheckpointManager
from circuit_processor import SimulationProcessor
from folder_processor import FolderProcessor
from orchestrator import PipelineOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_simulations.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)


def process_folder_wrapper(args):
    """
    Wrapper function for processing a folder with simulations.
    This runs in a worker process.
    
    Args:
        args: Tuple of (folder_path, processed_hashes, mode, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth)
        
    Returns:
        List of results
    """
    folder_path, processed_hashes, mode, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth = args
    try:
        # Initialize components in worker process
        sim_config = PipelineConfig.SIMULATION
        simulator = QuantumSimulator(
            timeout_seconds=sim_config.get("timeout_seconds", 60),
            infiniquantum_config=sim_config.get("infiniquantum")
        )
        
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        
        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = SimulationProcessor(
            simulator,
            min_qubits=min_qubits,
            max_qubits=max_qubits,
            min_depth=min_depth,
            max_depth=max_depth
        )
        
        folder_processor = FolderProcessor(
            circuit_processor,
            table_client,
            checkpoint_manager
        )
        folder_processor.mode = mode  # Add mode for simulation
        
        return folder_processor.process_folder(folder_path, processed_hashes)
        
    except Exception as e:
        logger.error(f"Failed to process folder {folder_path}: {e}")
        return []


def main():
    """Main entry point"""
    config = PipelineConfig()
    
    parser = argparse.ArgumentParser(
        description="Rerun simulations in parallel and update Azure Table."
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
        "--mode", type=str, choices=["auto", "all", "rdbms"], default=None,
        help="Simulation mode: 'auto', 'all', or 'rdbms'."
    )
    parser.add_argument(
        "--checkpoints-dir", type=str, default=None,
        help="Directory to store processed circuit hashes per folder."
    )
    parser.add_argument(
        "--workers", type=int, default=None, 
        help="Number of worker processes."
    )
    parser.add_argument(
        "--min-qubits", type=int, default=None,
        help="Minimum number of qubits."
    )
    parser.add_argument(
        "--max-qubits", type=int, default=None,
        help="Maximum number of qubits."
    )
    parser.add_argument(
        "--min-depth", type=int, default=None,
        help="Minimum circuit depth."
    )
    parser.add_argument(
        "--max-depth", type=int, default=None,
        help="Maximum circuit depth."
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
    
    mode = args.mode
    if mode is None:
        try:
            user_input = input(
                "Enter simulation mode (auto/all/rdbms) [default: auto]: "
            ).strip().lower()
            mode = user_input if user_input in ["auto", "all", "rdbms"] else "auto"
        except EOFError:
            mode = "auto"
    
    checkpoints_dir = args.checkpoints_dir
    if checkpoints_dir is None:
        checkpoints_dir = "checkpoints_rdbms" if mode == "rdbms" else "checkpoints"
    
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
    
    # Get circuit limits
    min_qubits = args.min_qubits
    if min_qubits is None:
        try:
            user_input = input(
                "Enter minimum qubit count (or press Enter for no limit): "
            ).strip()
            if user_input:
                try:
                    min_qubits = int(user_input)
                except ValueError:
                    print("Invalid number. No minimum qubit limit will be applied.")
                    min_qubits = None
        except EOFError:
            pass

    max_qubits = args.max_qubits
    if max_qubits is None:
        try:
            user_input = input(
                "Enter maximum qubit count (or press Enter for no limit): "
            ).strip()
            if user_input:
                try:
                    max_qubits = int(user_input)
                except ValueError:
                    print("Invalid number. No maximum qubit limit will be applied.")
                    max_qubits = None
        except EOFError:
            pass

    min_depth = args.min_depth
    if min_depth is None:
        try:
            user_input = input(
                "Enter minimum circuit depth (or press Enter for no limit): "
            ).strip()
            if user_input:
                try:
                    min_depth = int(user_input)
                except ValueError:
                    print("Invalid number. No minimum depth limit will be applied.")
                    min_depth = None
        except EOFError:
            pass

    max_depth = args.max_depth
    if max_depth is None:
        try:
            user_input = input(
                "Enter maximum circuit depth (or press Enter for no limit): "
            ).strip()
            if user_input:
                try:
                    max_depth = int(user_input)
                except ValueError:
                    print("Invalid number. No maximum depth limit will be applied.")
                    max_depth = None
        except EOFError:
            pass

    verbose = args.verbose
    
    # Display configuration
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Mode: {mode}")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    print(f"Min Qubits: {min_qubits if min_qubits is not None else 'No limit'}")
    print(f"Max Qubits: {max_qubits if max_qubits is not None else 'No limit'}")
    print(f"Min Depth: {min_depth if min_depth is not None else 'No limit'}")
    print(f"Max Depth: {max_depth if max_depth is not None else 'No limit'}")
    
    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
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
    
    # Run pipeline with mode and checkpoints_dir passed through
    total_updated = orchestrator.run_parallel(
        process_folder_wrapper,
        mode=mode,
        checkpoints_dir=checkpoints_dir,
        min_qubits=min_qubits,
        max_qubits=max_qubits,
        min_depth=min_depth,
        max_depth=max_depth,
        num_workers=workers,
        limit=limit,
        verbose=verbose
    )
    
    logger.info(f"Rerun complete. Total circuits updated: {total_updated}")


if __name__ == "__main__":
    main()
