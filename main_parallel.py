#!/usr/bin/env python3
"""
High-Performance Parallel Quantum Circuit Processing Pipeline
Optimized for Intel Xeon E5-6248R 24C 3.0GHz with 185GB RAM

Features:
- Parallel pipeline execution
- Minimal logging (warnings and essential messages only)
- Continuous operation
- Efficient memory usage
- Local disk storage priority
- Early duplicate detection
- Azure cloud storage integration

Author: InferQ Pipeline System
"""

import os
import sys
import logging
import signal
import multiprocessing as mp
import numpy as np

# Import centralized configuration
from config import config



# Suppress numpy array printing to stdout
np.set_printoptions(suppress=True, threshold=0)

# Configure logging using centralized config
log_config = config.LOGGING
file_handler = logging.FileHandler('pipeline.log')
file_handler.setLevel(getattr(logging, log_config['level']))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(getattr(logging, log_config['level']))

formatter = logging.Formatter(log_config['format'])
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logging.basicConfig(
    level=getattr(logging, log_config['level']),
    handlers=[file_handler, console_handler]
)

# Suppress ALL verbose logging - comprehensive list (BEFORE imports)
verbose_loggers = [
    'qiskit', 'qiskit.passmanager', 'qiskit.passmanager.base_tasks', 'qiskit.compiler', 'qiskit.transpiler', 'qiskit_aer',
    'azure.core', 'azure.storage', 'azure.data.tables', 'azure.storage.blob',
    'azure.core.pipeline.policies.http_logging_policy',
    'simulators.simulate', 'simulators.lib.infiniquantum', 'simulators.lib.result_extractor',
    'feature_extractors.extractors', 'feature_extractors.static_features',
    'feature_extractors.graph_features', 'feature_extractors.dynamic_features', 'feature_extractors.graphs',
    'generators.circuit_merger', 'utils.local_storage', 'utils.table_storage',
    'utils.blob_storage', 'utils.azure_connection', 'utils.save_utils',
    'rustworkx', 'rx',  # Suppress rustworkx matrix outputs
    '__main__'  # Suppress main module info logging
]

for logger_name in verbose_loggers:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

# Import pipeline components AFTER logging setup
from pipeline.manager import run_parallel_pipeline

# Global flag for graceful shutdown
shutdown_flag = mp.Value('i', 0)

# Get logger after logging setup
logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.warning(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag.value = 1
    # Force exit if signal received multiple times
    import sys
    if hasattr(signal_handler, 'call_count'):
        signal_handler.call_count += 1
        if signal_handler.call_count > 2:
            logger.warning("Multiple interrupts received, forcing exit...")
            sys.exit(1)
    else:
        signal_handler.call_count = 1
    # Force exit if signal received multiple times
    if hasattr(signal_handler, 'call_count'):
        signal_handler.call_count += 1
        if signal_handler.call_count >= 3:
            logger.error("Multiple interrupts received, forcing exit...")
            os._exit(1)
    else:
        signal_handler.call_count = 1


def main():
    """Main entry point with command line argument support."""
    import argparse
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='High-Performance Quantum Circuit Pipeline')
    parser.add_argument('--workers', type=int, default=None, 
                       help='Number of parallel workers (default: CPU count - 2)')
    parser.add_argument('--iterations', type=int, default=None,
                       help='Maximum iterations (default: infinite)')
    parser.add_argument('--batch-size', type=int, default=None,
                       help='Circuits per batch (default: from config)')
    parser.add_argument('--azure-interval', type=int, default=None,
                       help='Azure upload interval (default: from config)')
    parser.add_argument('--profile', action='store_true',
                       help='Enable performance profiling')
    
    args = parser.parse_args()
    
    # Performance profiling (optional)
    if args.profile:
        import cProfile
        import pstats
        
        profiler = cProfile.Profile()
        profiler.enable()
        
        try:
            run_parallel_pipeline(
                num_workers=args.workers,
                max_iterations=args.iterations,
                batch_size=args.batch_size,
                azure_upload_interval=args.azure_interval
            )
        finally:
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats('cumulative')
            stats.print_stats(20)  # Top 20 functions
    else:
        run_parallel_pipeline(
            num_workers=args.workers,
            max_iterations=args.iterations,
            batch_size=args.batch_size,
            azure_upload_interval=args.azure_interval
        )

if __name__ == "__main__":
    main()