#!/usr/bin/env python3
"""
Pipeline Manager Module

Orchestrates the high-performance parallel quantum circuit processing pipeline.
Manages worker processes, Azure uploads, system monitoring, and overall
pipeline coordination.
"""

import time
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from pathlib import Path
from typing import Optional, Dict, Any, List, Set

from utils.azure_connection import AzureConnection
from utils.duplicate_detector import (
    initialize_duplicate_detection, get_duplicate_detector,
    mark_circuits_pending_upload, mark_circuits_uploaded_to_azure, mark_circuits_upload_failed,
    coordinate_batch_session_hashes, get_current_session_hashes
)
from pipeline.worker import run_single_pipeline, setup_worker_signal_handling
from config import get_pipeline_config, get_storage_config
from pipeline.azure_manager import (
    upload_batch_to_azure, should_trigger_upload, 
    log_upload_trigger, log_final_upload
)
from pipeline.system_utils import (
    monitor_system_resources, cleanup_old_circuits, log_system_startup,
    should_cleanup, log_cleanup_results
)

# Configure logging
logger = logging.getLogger(__name__)

class PipelineManager:
    """
    High-performance parallel quantum circuit processing pipeline manager.
    
    Coordinates worker processes, Azure uploads, system monitoring,
    and overall pipeline execution.
    """
    
    def __init__(self, num_workers: Optional[int] = None, azure_upload_interval: int = 100, batch_timeout_seconds: Optional[int] = None):
        """
        Initialize the pipeline manager.
        
        Args:
            num_workers: Number of parallel workers (default: CPU count - 2)
            azure_upload_interval: Upload to Azure every N circuits
            batch_timeout_seconds: Timeout for individual worker tasks (default: from config)
        """
        # Set optimal worker count
        if num_workers is None:
            num_workers = min(22, mp.cpu_count() - 2)  # Leave 2 cores for system
        
        self.num_workers = num_workers
        self.azure_upload_interval = azure_upload_interval
        
        # Get batch timeout from config if not provided
        if batch_timeout_seconds is None:
            pipeline_config = get_pipeline_config()
            batch_timeout_seconds = pipeline_config['batch_timeout_seconds']
        self.batch_timeout_seconds = batch_timeout_seconds
        
        self.azure_conn: Optional[AzureConnection] = None
        self.shutdown_flag = mp.Value('i', 0)
        
        # Statistics tracking
        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'timed_out': 0,  # Track timeouts
            'uploaded_to_azure': 0,
            'upload_failures': 0,
            'start_time': time.time(),
            'last_azure_upload': 0
        }
        
        # Upload buffer
        self.upload_buffer: List[Dict[str, Any]] = []
        
        # Session coordination
        self.current_session_hashes: Set[str] = set()
    
    def initialize(self) -> bool:
        """
        Initialize the pipeline manager and all subsystems.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Log system startup
            log_system_startup(self.num_workers)
            logger.warning(f"⏱️  Batch timeout: {self.batch_timeout_seconds}s")
            
            # Initialize Azure connection ONCE for both duplicate detection and uploads (if enabled)
            from config import get_azure_config
            azure_config = get_azure_config()
            
            if azure_config['enabled']:
                try:
                    self.azure_conn = AzureConnection()
                    logger.warning("✓ Azure connection established for remote storage")
                except Exception as e:
                    logger.warning(f"⚠️  Azure connection failed: {e}")
                    logger.warning("⚠️  Remote storage disabled - LOCAL ONLY mode")
            else:
                logger.warning("⚠️  Azure disabled in configuration - LOCAL ONLY mode")
            
            # Initialize duplicate detection system with shared Azure connection
            logger.warning("🔍 Initializing duplicate detection system...")
            duplicate_init_success = initialize_duplicate_detection(azure_conn=self.azure_conn)
            if duplicate_init_success:
                detector_stats = get_duplicate_detector().get_stats()
                logger.warning(f"✅ Duplicate detection ready: {detector_stats['known_hashes_count']} known circuits")
                logger.warning(f"   📊 Azure: {detector_stats['azure_hashes_count']}, Pending: {detector_stats['pending_hashes_count']}, Session: {detector_stats['session_hashes_count']}")
            else:
                logger.warning("⚠️  Duplicate detection initialization failed - will check locally only")
            
            # Create local storage directory from config
            storage_config = get_storage_config()
            storage_path = Path(storage_config['local_circuits_dir'])
            storage_path.mkdir(parents=True, exist_ok=True)
            logger.warning(f"📁 Local storage directory: {storage_path.absolute()}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize pipeline manager: {e}")
            return False
    
    def run_pipeline(self, max_iterations: Optional[int] = None, batch_size: int = 50) -> Dict[str, Any]:
        """
        Run the parallel pipeline with continuous operation.
        
        Args:
            max_iterations: Maximum iterations (None for infinite)
            batch_size: Circuits per batch before status update
            
        Returns:
            Dictionary with final pipeline statistics
        """
        iteration = 0
        
        try:
            with ProcessPoolExecutor(max_workers=self.num_workers, 
                                   initializer=setup_worker_signal_handling) as executor:
                
                while max_iterations is None or iteration < max_iterations:
                    if self.shutdown_flag.value:
                        logger.warning("Shutdown flag detected, stopping pipeline...")
                        break
                    
                    try:
                        # Process a batch of circuits
                        batch_results = self._process_batch(executor, batch_size, iteration)
                        
                        # Update statistics and handle uploads
                        self._update_stats(batch_results)
                        self._handle_azure_uploads()
                        # self._handle_cleanup()
                        
                        # Log batch status
                        self._log_batch_status(iteration + 1, batch_results)
                        
                        iteration += 1
                        
                        # Brief pause to prevent system overload
                        time.sleep(0.05)
                        
                    except KeyboardInterrupt:
                        logger.warning("KeyboardInterrupt in batch processing, setting shutdown flag...")
                        self.shutdown_flag.value = 1
                        break
                    except TimeoutError:
                        logger.warning("Batch processing timed out, continuing...")
                        continue
                    except Exception as e:
                        logger.error(f"Batch processing error: {e}, continuing...")
                        continue
        
        except KeyboardInterrupt:
            logger.warning("KeyboardInterrupt received, shutting down...")
            self.shutdown_flag.value = 1
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
        finally:
            # Final cleanup and uploads
            self._finalize_pipeline()
        
        return self._get_final_stats()
    
    def _process_batch(self, executor: ProcessPoolExecutor, batch_size: int, iteration: int) -> List[Dict[str, Any]]:
        """
        Process a batch of circuits using the executor.
        
        Args:
            executor: Process pool executor
            batch_size: Number of circuits in batch
            iteration: Current iteration number
            
        Returns:
            List of batch results
        """
        # Submit batch of work
        futures = []
        for i in range(batch_size):
            if self.shutdown_flag.value:
                break
            future = executor.submit(run_single_pipeline, i % self.num_workers, iteration * batch_size + i, self.current_session_hashes)
            futures.append(future)
        
        # Process completed work with timeout
        batch_results = []
        for future in as_completed(futures, timeout=self.batch_timeout_seconds):
            if self.shutdown_flag.value:
                break
            
            try:
                result = future.result(timeout=1)  # Quick timeout since future is already done
                batch_results.append(result)
            except TimeoutError:
                # This shouldn't happen since we're using as_completed with timeout
                logger.warning("Individual future timed out unexpectedly")
                batch_results.append({
                    'success': False,
                    'worker_id': -1,
                    'error': 'Worker task timed out',
                    'timeout': True,
                    'timestamp': time.time()
                })
            except Exception as e:
                logger.warning(f"Future result error: {e}")
                batch_results.append({
                    'success': False,
                    'worker_id': -1,
                    'error': f'Future error: {str(e)}',
                    'timestamp': time.time()
                })
        
        # Handle any remaining futures that didn't complete within timeout
        for future in futures:
            if not future.done():
                future.cancel()
                logger.warning("Cancelled incomplete worker task due to timeout")
                batch_results.append({
                    'success': False,
                    'worker_id': -1,
                    'error': f'Worker task timed out after {self.batch_timeout_seconds}s',
                    'timeout': True,
                    'timestamp': time.time()
                })
        
        return batch_results
    
    def _update_stats(self, batch_results: List[Dict[str, Any]]) -> None:
        """
        Update pipeline statistics based on batch results.
        
        Args:
            batch_results: Results from the current batch
        """
        # Collect session hashes from all workers for coordination
        worker_session_hashes = []
        
        for result in batch_results:
            self.stats['total_processed'] += 1
            
            # Collect worker session hashes
            if 'worker_session_hashes' in result:
                worker_session_hashes.append(result['worker_session_hashes'])
            
            if result['success']:
                self.stats['successful'] += 1
                
                # Log duplicate detection results
                if result.get('duplicate', False):
                    logger.debug(f"Worker-{result['worker_id']}: Duplicate circuit skipped")
                
                # Add to upload buffer if Azure is available and circuit was written (not duplicate)
                if self.azure_conn and result.get('written'):
                    self.upload_buffer.append(result)
                    # Mark circuit as pending upload in duplicate detector
                    circuit_hash = result.get('circuit_hash')
                    if circuit_hash:
                        mark_circuits_pending_upload([circuit_hash])
                        logger.debug(f"📤 Marked {circuit_hash[:8]}... as pending upload")
            else:
                if result.get('timeout', False):
                    self.stats['timed_out'] += 1
                    logger.warning(f"Worker task timed out: {result.get('error', 'Unknown timeout')}")
                else:
                    self.stats['failed'] += 1
                    logger.warning(f"Pipeline failed: {result.get('error', 'Unknown error')}")
        
        # Coordinate session hashes from all workers
        if worker_session_hashes:
            coordinate_batch_session_hashes(worker_session_hashes)
            # Update current session hashes for next batch
            self.current_session_hashes = get_current_session_hashes()
            logger.debug(f"🔄 Updated session hashes: {len(self.current_session_hashes)} total")
    
    def _handle_azure_uploads(self) -> None:
        """Handle Azure uploads when buffer reaches threshold."""
        if self.azure_conn and should_trigger_upload(self.upload_buffer, self.azure_upload_interval):
            log_upload_trigger(len(self.upload_buffer), self.azure_upload_interval)
            
            # Extract circuit hashes before upload
            circuit_hashes = [result.get('circuit_hash') for result in self.upload_buffer if result.get('circuit_hash')]
            
            upload_stats = upload_batch_to_azure(self.upload_buffer, self.azure_conn)
            self.stats['uploaded_to_azure'] += upload_stats['uploaded']
            self.stats['upload_failures'] += upload_stats['failed']
            
            # Update duplicate detector with upload results
            if upload_stats.get('successful_hashes'):
                mark_circuits_uploaded_to_azure(upload_stats['successful_hashes'])
                logger.debug(f"☁️  Marked {len(upload_stats['successful_hashes'])} circuits as uploaded to Azure")
            if upload_stats.get('failed_hashes'):
                mark_circuits_upload_failed(upload_stats['failed_hashes'])
                logger.debug(f"❌ Marked {len(upload_stats['failed_hashes'])} circuits as upload failed")
            
            # Clear buffer
            self.upload_buffer = []
            self.stats['last_azure_upload'] = self.stats['total_processed']
    
    def _handle_cleanup(self) -> None:
        """Handle periodic cleanup of old circuit files."""
        if should_cleanup(self.stats['total_processed']):
            storage_config = get_storage_config()
            cleanup_stats = cleanup_old_circuits(Path(storage_config['local_circuits_dir']), max_age_hours=24)
            log_cleanup_results(cleanup_stats)
    
    def _log_batch_status(self, batch_num: int, batch_results: List[Dict[str, Any]]) -> None:
        """
        Log status after each batch completion.
        
        Args:
            batch_num: Current batch number
            batch_results: Results from the current batch
        """
        # Calculate batch statistics
        batch_successful = sum(1 for r in batch_results if r.get('success', False))
        batch_failed = len(batch_results) - batch_successful
        
        # Calculate rates
        elapsed = time.time() - self.stats['start_time']
        rate = self.stats['total_processed'] / elapsed * 60 if elapsed > 0 else 0
        
        # Monitor system resources
        resources = monitor_system_resources()
        
        # Enhanced status with Azure upload info
        azure_status = ""
        if self.azure_conn:
            azure_status = f" | Azure: {self.stats['uploaded_to_azure']}↑ | Buffer: {len(self.upload_buffer)}"
        
        logger.warning(
            f"Batch {batch_num}: {batch_successful}✓/{batch_failed}✗ | "
            f"Total: {self.stats['successful']}✓/{self.stats['failed']}✗ | "
            f"Rate: {rate:.1f}/min | "
            f"CPU: {resources['cpu_percent']:.1f}% | "
            f"RAM: {resources['memory_percent']:.1f}% | "
            f"Disk: {resources['disk_free_gb']:.1f}GB{azure_status}"
        )
    
    def _finalize_pipeline(self) -> None:
        """Finalize pipeline execution with cleanup and final uploads."""
        # Upload remaining circuits in buffer
        if self.azure_conn and self.upload_buffer:
            log_final_upload(len(self.upload_buffer))
            
            # Extract circuit hashes before upload
            circuit_hashes = [result.get('circuit_hash') for result in self.upload_buffer if result.get('circuit_hash')]
            
            upload_stats = upload_batch_to_azure(self.upload_buffer, self.azure_conn)
            self.stats['uploaded_to_azure'] += upload_stats['uploaded']
            self.stats['upload_failures'] += upload_stats['failed']
            
            # Update duplicate detector with upload results
            if upload_stats.get('successful_hashes'):
                mark_circuits_uploaded_to_azure(upload_stats['successful_hashes'])
            if upload_stats.get('failed_hashes'):
                mark_circuits_upload_failed(upload_stats['failed_hashes'])
    
    def _get_final_stats(self) -> Dict[str, Any]:
        """
        Get final pipeline statistics.
        
        Returns:
            Dictionary with final statistics
        """
        elapsed = time.time() - self.stats['start_time']
        rate = self.stats['total_processed'] / elapsed * 60 if elapsed > 0 else 0
        
        # Log final statistics
        logger.warning("=" * 80)
        logger.warning("PIPELINE COMPLETED")
        logger.warning(f"Total processed: {self.stats['total_processed']}")
        logger.warning(f"Successful: {self.stats['successful']}")
        logger.warning(f"Failed: {self.stats['failed']}")
        logger.warning(f"Timed out: {self.stats['timed_out']}")
        if self.stats['total_processed'] > 0:
            logger.warning(f"Success rate: {self.stats['successful']/self.stats['total_processed']*100:.1f}%")
        if self.azure_conn:
            logger.warning(f"Uploaded to Azure: {self.stats['uploaded_to_azure']}")
            logger.warning(f"Upload failures: {self.stats['upload_failures']}")
            total_uploads = self.stats['uploaded_to_azure'] + self.stats['upload_failures']
            if total_uploads > 0:
                logger.warning(f"Upload success rate: {self.stats['uploaded_to_azure']/total_uploads*100:.1f}%")
        logger.warning(f"Average rate: {rate:.1f} circuits/minute")
        logger.warning(f"Total runtime: {elapsed/3600:.1f} hours")
        logger.warning("=" * 80)
        
        return {
            **self.stats,
            'elapsed_time': elapsed,
            'rate_per_minute': rate,
            'success_rate': self.stats['successful']/self.stats['total_processed']*100 if self.stats['total_processed'] > 0 else 0
        }
    
    def set_shutdown_flag(self) -> None:
        """Set the shutdown flag to gracefully stop the pipeline."""
        self.shutdown_flag.value = 1


def run_parallel_pipeline(num_workers: Optional[int] = None, max_iterations: Optional[int] = None, 
                         batch_size: Optional[int] = None, azure_upload_interval: Optional[int] = None,
                         batch_timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
    """
    Run the parallel pipeline with the specified parameters.
    
    Args:
        num_workers: Number of parallel workers (default: from config)
        max_iterations: Maximum iterations (default: from config)
        batch_size: Circuits per batch before status update (default: from config)
        azure_upload_interval: Upload to Azure every N circuits (default: from config)
        batch_timeout_seconds: Timeout for individual worker tasks (default: from config)
        
    Returns:
        Dictionary with final pipeline statistics
    """
    # Get configuration from centralized config, with parameter overrides
    pipeline_config = get_pipeline_config()
    
    # Use provided parameters or fall back to config defaults
    num_workers = num_workers or pipeline_config['workers']
    max_iterations = max_iterations or pipeline_config['max_iterations']
    batch_size = batch_size or pipeline_config['batch_size']
    azure_upload_interval = azure_upload_interval or pipeline_config['azure_upload_interval']
    batch_timeout_seconds = batch_timeout_seconds or pipeline_config['batch_timeout_seconds']
    
    # Create and initialize pipeline manager
    manager = PipelineManager(
        num_workers=num_workers, 
        azure_upload_interval=azure_upload_interval,
        batch_timeout_seconds=batch_timeout_seconds
    )
    
    if not manager.initialize():
        logger.error("❌ Failed to initialize pipeline manager")
        return {'error': 'Initialization failed'}
    
    # Run the pipeline
    return manager.run_pipeline(max_iterations=max_iterations, batch_size=batch_size)