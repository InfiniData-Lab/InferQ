#!/usr/bin/env python3
"""
System Utilities Module

Provides system monitoring, cleanup, and resource management utilities
for the high-performance quantum circuit pipeline.
"""

import time
import logging
import psutil
import shutil
from pathlib import Path
from typing import Dict, Any

# Configure logging
logger = logging.getLogger(__name__)

def monitor_system_resources() -> Dict[str, Any]:
    """
    Monitor system resources and return current usage.
    
    Returns:
        Dictionary with system resource information
    """
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('.')
    
    return {
        'cpu_percent': cpu_percent,
        'memory_percent': memory.percent,
        'memory_available_gb': memory.available / (1024**3),
        'disk_free_gb': disk.free / (1024**3)
    }

def cleanup_old_circuits(circuits_dir: Path, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Clean up old circuit files to free disk space.
    
    Args:
        circuits_dir: Directory containing circuit files
        max_age_hours: Maximum age in hours before deletion
        
    Returns:
        Dictionary with cleanup statistics
    """
    if not circuits_dir.exists():
        return {'deleted': 0, 'freed_gb': 0}
    
    deleted_count = 0
    freed_bytes = 0
    cutoff_time = time.time() - (max_age_hours * 3600)
    
    try:
        for circuit_dir in circuits_dir.iterdir():
            if circuit_dir.is_dir():
                # Check if directory is old enough
                dir_mtime = circuit_dir.stat().st_mtime
                if dir_mtime < cutoff_time:
                    # Calculate size before deletion
                    dir_size = sum(f.stat().st_size for f in circuit_dir.rglob('*') if f.is_file())
                    
                    # Delete the directory
                    shutil.rmtree(circuit_dir)
                    
                    deleted_count += 1
                    freed_bytes += dir_size
    
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")
    
    freed_gb = freed_bytes / (1024**3)
    return {'deleted': deleted_count, 'freed_gb': freed_gb}

def get_system_info() -> Dict[str, Any]:
    """
    Get comprehensive system information.
    
    Returns:
        Dictionary with system information
    """
    import multiprocessing as mp
    
    return {
        'cpu_count': mp.cpu_count(),
        'memory_total_gb': psutil.virtual_memory().total / (1024**3),
        'disk_total_gb': psutil.disk_usage('.').total / (1024**3),
        'disk_free_gb': psutil.disk_usage('.').free / (1024**3)
    }

def log_system_startup(num_workers: int) -> None:
    """
    Log system information at pipeline startup.
    
    Args:
        num_workers: Number of worker processes
    """
    import multiprocessing as mp
    
    logger.warning(f"🚀 Starting parallel pipeline with {num_workers} workers")
    logger.warning(f"System: {mp.cpu_count()} cores, {psutil.virtual_memory().total / (1024**3):.1f}GB RAM")

def should_cleanup(total_processed: int, cleanup_interval: int = 1000) -> bool:
    """
    Check if cleanup should be performed based on processed count.
    
    Args:
        total_processed: Total circuits processed
        cleanup_interval: Cleanup interval
        
    Returns:
        True if cleanup should be performed, False otherwise
    """
    return total_processed % cleanup_interval == 0

def log_cleanup_results(cleanup_stats: Dict[str, Any]) -> None:
    """
    Log cleanup results.
    
    Args:
        cleanup_stats: Cleanup statistics
    """
    if cleanup_stats['deleted'] > 0:
        logger.warning(f"🧹 Cleaned up {cleanup_stats['deleted']} old circuits, freed {cleanup_stats['freed_gb']:.1f}GB")