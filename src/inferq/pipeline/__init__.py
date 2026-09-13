"""
High-Performance Quantum Circuit Processing Pipeline

This package provides a modular, high-performance parallel processing pipeline
for quantum circuits with the following components:

- worker.py: Individual circuit processing workers
- manager.py: Pipeline orchestration and coordination  
- azure_manager.py: Azure cloud storage integration
- system_utils.py: System monitoring and resource management

Author: InferQ Pipeline System
"""

from .azure_manager import upload_batch_to_azure
from .manager import PipelineManager, run_parallel_pipeline
from .system_utils import cleanup_old_circuits, monitor_system_resources
from .worker import run_single_pipeline

__all__ = [
    'run_parallel_pipeline',
    'PipelineManager', 
    'run_single_pipeline',
    'upload_batch_to_azure',
    'monitor_system_resources',
    'cleanup_old_circuits'
]