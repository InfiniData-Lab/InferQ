"""
Pipeline Orchestrator

Coordinates the overall rerun pipeline execution.
"""

import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates the entire rerun pipeline"""
    
    def __init__(self, circuits_dir: str, checkpoint_manager, azure_table_client):
        """
        Initialize orchestrator.
        
        Args:
            circuits_dir: Directory containing circuit folders
            checkpoint_manager: CheckpointManager instance
            azure_table_client: Azure table client
        """
        self.circuits_dir = circuits_dir
        self.checkpoint_manager = checkpoint_manager
        self.azure_table_client = azure_table_client
    
    def get_folders_to_process(self) -> list:
        """
        Get list of folders to process.
        
        Returns:
            Sorted list of folder names
        """
        try:
            subdirs = [
                d for d in os.listdir(self.circuits_dir)
                if os.path.isdir(os.path.join(self.circuits_dir, d))
            ]
            subdirs.sort()
            logger.info(f"Found {len(subdirs)} folders to process")
            return subdirs
        except Exception as e:
            logger.error(f"Error listing directories in {self.circuits_dir}: {e}")
            return []
    
    def run_parallel(self, 
                     process_folder_func,
                     num_workers: int = None,
                     limit: int = None,
                     verbose: bool = False,
                     **kwargs) -> int:
        """
        Run pipeline in parallel across multiple workers.
        
        Args:
            process_folder_func: Function to process a single folder
            num_workers: Number of worker processes
            limit: Maximum number of circuits to process
            verbose: Enable verbose logging
            **kwargs: Additional arguments to pass to process_folder_func (e.g., mode, checkpoints_dir)
            
        Returns:
            Total number of circuits updated
        """
        # Load checkpoints
        processed_hashes = self.checkpoint_manager.load_processed_hashes()
        processed_buckets = self.checkpoint_manager.bucket_hashes_by_prefix(processed_hashes)
        
        # Get folders
        subdirs = self.get_folders_to_process()
        if not subdirs:
            logger.warning(f"No subdirectories found in {self.circuits_dir}")
            return 0
        
        # Determine workers
        if num_workers is None:
            num_workers = max(1, multiprocessing.cpu_count() - 1)
        
        logger.info(f"Starting parallel execution with {num_workers} workers")
        
        total_updated = 0
        
        try:
            with ProcessPoolExecutor(max_workers=num_workers) as executor:
                # Submit tasks per folder
                future_to_folder = {}
                for folder_name in subdirs:
                    folder_path = os.path.join(self.circuits_dir, folder_name)
                    folder_processed = processed_buckets.get(folder_name, set())
                    
                    # Build args tuple with folder info and any extra kwargs
                    args = (folder_path, folder_processed)
                    if kwargs:
                        # Add kwargs values in consistent order
                        args = args + tuple(kwargs.values())
                    
                    future = executor.submit(
                        process_folder_func,
                        args
                    )
                    future_to_folder[future] = folder_name
                
                # Process results as they complete
                for future in tqdm(
                    as_completed(future_to_folder),
                    total=len(subdirs),
                    desc="Processing Folders"
                ):
                    folder_name = future_to_folder[future]
                    try:
                        folder_results = future.result()
                        if verbose:
                            logger.info(
                                f"Folder {folder_name} returned {len(folder_results)} results"
                            )
                        
                        # Process results for stats
                        for result in folder_results:
                            if limit and total_updated >= limit:
                                break
                            
                            # Count both successful updates and skipped circuits (both are checkpointed)
                            if result.get("table_updated", False):
                                total_updated += 1
                                if verbose:
                                    logger.info(f"Success: {result['hash']}")
                            elif result.get("skipped", False):
                                total_updated += 1
                                if verbose:
                                    logger.info(f"Skipped: {result['hash']} - {result.get('error')}")
                            elif result.get("error") and verbose:
                                logger.warning(f"Failed {result['hash']}: {result['error']}")
                        
                        if limit and total_updated >= limit:
                            logger.info(f"Limit of {limit} reached. Stopping.")
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                    
                    except Exception as e:
                        logger.error(f"Error processing folder {folder_name}: {e}")
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user. Stopping...")
            executor.shutdown(wait=False, cancel_futures=True)
            raise  # Re-raise to allow caller to handle
        
        logger.info(f"Pipeline complete. Total circuits processed: {total_updated}")
        return total_updated
