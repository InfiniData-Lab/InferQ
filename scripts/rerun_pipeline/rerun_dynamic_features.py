#!/usr/bin/env python3
"""
Rerun Dynamic Features Script

CLI tool to rerun dynamic feature extraction (entropy, sparsity) from saved statevector simulations.
This script processes circuits that already have statevector_saved simulation data and extracts/updates
the dynamic features (shannon_entropy, von_neumann_entropy, sparsity) without re-running simulations.
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
from circuit_processor import CircuitProcessor
from folder_processor import FolderProcessor
from orchestrator import PipelineOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_dynamic_features.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)


class DynamicFeatureProcessor(CircuitProcessor):
    """Processes circuits to extract dynamic features using statevector simulation"""
    
    def __init__(self, simulator, max_qubits=None, max_depth=None):
        """
        Initialize with a QuantumSimulator instance.
        
        Args:
            simulator: Initialized QuantumSimulator
            max_qubits: Maximum qubit count to process (None = no limit)
            max_depth: Maximum circuit depth to process (None = no limit)
        """
        self.simulator = simulator
        self.max_qubits = max_qubits
        self.max_depth = max_depth
    
    def process_circuit_file(self, file_path: str) -> dict:
        """
        Process a circuit file to extract dynamic features.
        
        Args:
            file_path: Path to circuit file
            
        Returns:
            Dictionary with processing results
        """
        try:
            qc, circuit_hash, _ = self.load_circuit_from_file(file_path)
            
            updates = {}
            success_flag = False
            skipped_flag = False
            error_msg = None
            
            logger.info(f"Processing dynamic features for circuit {circuit_hash}")
            
            # Check circuit size limits
            if self.max_qubits is not None and qc.num_qubits > self.max_qubits:
                logger.info(f"Skipping circuit {circuit_hash}: {qc.num_qubits} qubits exceeds limit of {self.max_qubits}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit has {qc.num_qubits} qubits, exceeds limit of {self.max_qubits}",
                    "file_path": file_path,
                }
            
            if self.max_depth is not None and qc.depth() > self.max_depth:
                logger.info(f"Skipping circuit {circuit_hash}: depth {qc.depth()} exceeds limit of {self.max_depth}")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": f"Circuit depth {qc.depth()} exceeds limit of {self.max_depth}",
                    "file_path": file_path,
                }
            
            # Run statevector simulation with save_statevector to extract dynamic features
            from simulators.lib.types import SimulationMethod
            
            qc_copy = qc.copy()
            qc_copy.save_statevector()
            result = self.simulator._run_simulation(qc_copy, SimulationMethod.STATEVECTOR)
            
            if result.get("success"):
                success_flag = True
                data = result.get("data", {})
                
                # Extract dynamic features
                updates = {}
                if "shannon_entropy" in data:
                    updates["statevector_saved_shannon_entropy"] = data["shannon_entropy"]
                if "von_neumann_entropy" in data:
                    updates["statevector_saved_von_neumann_entropy"] = data["von_neumann_entropy"]
                if "sparsity" in data:
                    updates["statevector_saved_sparsity"] = data["sparsity"]
                
                logger.info(f"Dynamic features extracted - "
                           f"Entropy: {data.get('shannon_entropy', 0):.4f}, "
                           f"Sparsity: {data.get('sparsity', 0):.4f}")
                           
            elif result.get("skipped"):
                skipped_flag = True
                error_msg = result.get("error")
                logger.info(f"Dynamic feature extraction skipped: {error_msg}")
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"Dynamic feature extraction failed: {error_msg}")
            
            return {
                "hash": circuit_hash,
                "success": success_flag,
                "skipped": skipped_flag,
                "updates": updates,
                "error": error_msg,
                "file_path": file_path,
            }
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {
                "hash": None,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e),
                "file_path": file_path,
            }


def process_folder_wrapper(args):
    """
    Wrapper function for processing a folder with dynamic feature extraction.
    This runs in a worker process.
    
    Args:
        args: Tuple of (folder_path, processed_hashes, checkpoints_dir, max_qubits, max_depth)
        
    Returns:
        List of results
    """
    folder_path, processed_hashes, checkpoints_dir, max_qubits, max_depth = args
    try:
        # Initialize components in worker process
        from simulators.simulate import QuantumSimulator
        sim_config = PipelineConfig.SIMULATION
        simulator = QuantumSimulator(
            timeout_seconds=sim_config.get("timeout_seconds", 60),
            infiniquantum_config=sim_config.get("infiniquantum")
        )
        
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        
        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = DynamicFeatureProcessor(simulator, max_qubits, max_depth)
        
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
        description="Rerun dynamic feature extraction (entropy, sparsity) from saved statevector simulations."
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
        "--checkpoints-dir", type=str, default=None,
        help="Directory to store processed circuit hashes per folder."
    )
    parser.add_argument(
        "--workers", type=int, default=None, 
        help="Number of worker processes."
    )
    parser.add_argument(
        "--skip-confirmation", action="store_true",
        help="Skip confirmation prompt before starting."
    )
    parser.add_argument(
        "--max-qubits", type=int, default=None,
        help="Maximum qubit count to process (circuits with more qubits will be skipped)."
    )
    parser.add_argument(
        "--max-depth", type=int, default=None,
        help="Maximum circuit depth to process (circuits with greater depth will be skipped)."
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
    
    checkpoints_dir = args.checkpoints_dir
    if checkpoints_dir is None:
        checkpoints_dir = "checkpoints_dynamic_features"
    
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
    
    verbose = args.verbose
    
    # Get circuit limits
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
                    print("Invalid number. No qubit limit will be applied.")
                    max_qubits = None
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
                    print("Invalid number. No depth limit will be applied.")
                    max_depth = None
        except EOFError:
            pass
    
    # Display configuration
    print("\n" + "="*60)
    print("DYNAMIC FEATURES EXTRACTION CONFIGURATION")
    print("="*60)
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Features: Shannon Entropy, Von Neumann Entropy, Sparsity")
    print(f"Source: statevector_saved simulation data")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    print(f"Max Qubits: {max_qubits if max_qubits is not None else 'No limit'}")
    print(f"Max Depth: {max_depth if max_depth is not None else 'No limit'}")
    print(f"Verbose: {verbose}")
    print("="*60 + "\n")
    
    # Confirmation prompt
    if not args.skip_confirmation:
        try:
            confirm = input("Proceed with dynamic feature extraction? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Aborted.")
                return
        except EOFError:
            print("No input received. Proceeding...")
    
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
    
    # Run pipeline with dynamic feature extraction parameters
    total_updated = orchestrator.run_parallel(
        process_folder_wrapper,
        checkpoints_dir=checkpoints_dir,
        max_qubits=max_qubits,
        max_depth=max_depth,
        num_workers=workers,
        limit=limit,
        verbose=verbose
    )
    
    logger.info(f"Dynamic feature extraction complete. Total circuits updated: {total_updated}")
    print(f"\n{'='*60}")
    print(f"COMPLETED: {total_updated} circuits updated with dynamic features")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
