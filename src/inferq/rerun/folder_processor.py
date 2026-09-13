"""
Folder Processor

Handles processing all circuits within a folder.
"""

import logging
import os
import time

import psutil

logger = logging.getLogger(__name__)

MEMORY_THRESHOLD_PERCENT = 90
MEMORY_CHECK_INTERVAL = 5


class FolderProcessor:
    """Processes all circuits in a folder"""
    
    def __init__(self, circuit_processor, azure_table_client, checkpoint_manager):
        """
        Initialize folder processor.
        
        Args:
            circuit_processor: Instance of CircuitProcessor (Simulation or SQL)
            azure_table_client: Azure table client for updates
            checkpoint_manager: CheckpointManager instance
        """
        self.circuit_processor = circuit_processor
        self.azure_table_client = azure_table_client
        self.checkpoint_manager = checkpoint_manager
    
    def process_folder(self, folder_path: str, processed_hashes: set) -> list:
        """
        Process all circuits in a folder.
        
        Args:
            folder_path: Path to folder containing circuit files
            processed_hashes: Set of already processed circuit hashes
            
        Returns:
            List of result dictionaries
        """
        from inferq.remote.table import update_circuit_metadata_in_table
        
        logger.info(f"Processing folder: {folder_path}")
        results = []
        
        try:
            folder_name = os.path.basename(folder_path)
            checkpoint_path = self.checkpoint_manager.get_checkpoint_path(folder_name)
            
            # List files in the folder
            try:
                files = [f for f in os.listdir(folder_path) if f.endswith(".qpy")]
            except FileNotFoundError:
                logger.warning(f"Folder not found: {folder_path}")
                return []
            
            # Process each file
            with open(checkpoint_path, "a") as checkpoint_f:
                for filename in files:
                    # Memory hold-off
                    while psutil.virtual_memory().percent > MEMORY_THRESHOLD_PERCENT:
                        time.sleep(MEMORY_CHECK_INTERVAL)
                    
                    circuit_hash = os.path.splitext(filename)[0]
                    
                    # Skip if already processed
                    if circuit_hash in processed_hashes:
                        continue
                    
                    file_path = os.path.join(folder_path, filename)
                    result = self._process_single_circuit(
                        file_path, 
                        circuit_hash,
                        checkpoint_f,
                        update_circuit_metadata_in_table
                    )
                    results.append(result)
            
        except Exception as e:
            logger.error(f"Error processing folder {folder_path}: {e}")
        
        return results
    
    def _process_single_circuit(self, file_path: str, circuit_hash: str, 
                                checkpoint_f, update_func) -> dict:
        """
        Process a single circuit and handle checkpointing.
        
        Args:
            file_path: Path to circuit file
            circuit_hash: Hash of the circuit
            checkpoint_f: Open checkpoint file handle
            update_func: Function to update Azure table
            
        Returns:
            Result dictionary
        """
        # Check if processor has mode parameter (SimulationProcessor)
        if hasattr(self.circuit_processor, 'process_circuit_file'):
            # For SimulationProcessor, need to pass mode
            if hasattr(self, 'mode'):
                result = self.circuit_processor.process_circuit_file(file_path, self.mode)
            else:
                # For SQLFeatureProcessor, no mode needed
                result = self.circuit_processor.process_circuit_file(file_path)
        else:
            raise ValueError("Invalid circuit processor")
        
        # Handle successful processing
        if result["success"]:
            try:
                table_success = update_func(
                    self.azure_table_client, 
                    circuit_hash, 
                    result["updates"]
                )
                result["table_updated"] = table_success
                if table_success:
                    checkpoint_f.write(f"{circuit_hash}\n")
                    checkpoint_f.flush()
            except Exception as e:
                logger.error(f"Azure update error for {circuit_hash}: {e}")
                result["table_updated"] = False
                result["error"] = f"Azure update failed: {e}"
        
        # Handle skipped circuits
        elif result.get("skipped"):
            logger.info(f"Skipping {circuit_hash}: {result.get('error')}")
            checkpoint_f.write(f"{circuit_hash}\n")
            checkpoint_f.flush()
        
        return result
