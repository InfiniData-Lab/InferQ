"""
Checkpoint Manager

Handles loading and saving of processing checkpoints to avoid reprocessing circuits.
"""

import os
import logging

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages checkpoint files to track processed circuits"""
    
    def __init__(self, checkpoints_dir: str):
        self.checkpoints_dir = checkpoints_dir
        self._ensure_directory_exists()
    
    def _ensure_directory_exists(self):
        """Create checkpoints directory if it doesn't exist"""
        if not os.path.exists(self.checkpoints_dir):
            try:
                os.makedirs(self.checkpoints_dir)
                logger.info(f"Created checkpoints directory: {self.checkpoints_dir}")
            except Exception as e:
                logger.error(f"Failed to create checkpoints directory: {e}")
                raise
    
    def load_processed_hashes(self) -> set:
        """
        Load all processed circuit hashes from checkpoint files.
        
        Returns:
            Set of circuit hashes that have been processed
        """
        processed_hashes = set()
        
        if not os.path.exists(self.checkpoints_dir):
            return processed_hashes
        
        try:
            for filename in os.listdir(self.checkpoints_dir):
                if filename.endswith(".txt"):
                    filepath = os.path.join(self.checkpoints_dir, filename)
                    with open(filepath, "r") as f:
                        file_hashes = set(line.strip() for line in f if line.strip())
                        processed_hashes.update(file_hashes)
            
            logger.info(f"Loaded {len(processed_hashes)} processed circuit hashes from checkpoints")
            return processed_hashes
            
        except Exception as e:
            logger.error(f"Failed to load checkpoints: {e}")
            return processed_hashes
    
    def bucket_hashes_by_prefix(self, processed_hashes: set, prefix_length: int = 2) -> dict:
        """
        Organize hashes into buckets by prefix for efficient lookup.
        
        Args:
            processed_hashes: Set of circuit hashes
            prefix_length: Length of prefix to use for bucketing
            
        Returns:
            Dictionary mapping prefix -> set of hashes
        """
        buckets = {}
        
        if not processed_hashes:
            return buckets
        
        logger.info("Bucketing processed hashes by prefix...")
        for h in processed_hashes:
            if len(h) >= prefix_length:
                prefix = h[:prefix_length]
                if prefix not in buckets:
                    buckets[prefix] = set()
                buckets[prefix].add(h)
        
        return buckets
    
    def get_checkpoint_path(self, folder_name: str) -> str:
        """
        Get the checkpoint file path for a given folder.
        
        Args:
            folder_name: Name of the folder
            
        Returns:
            Full path to the checkpoint file
        """
        return os.path.join(self.checkpoints_dir, f"{folder_name}.txt")
    
    def write_checkpoint(self, checkpoint_path: str, circuit_hash: str):
        """
        Write a circuit hash to a checkpoint file.
        
        Args:
            checkpoint_path: Path to checkpoint file
            circuit_hash: Hash to write
        """
        try:
            with open(checkpoint_path, "a") as f:
                f.write(f"{circuit_hash}\n")
                f.flush()
        except Exception as e:
            logger.error(f"Failed to write checkpoint: {e}")
            raise
