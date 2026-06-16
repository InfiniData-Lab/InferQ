"""
Quantum circuit storage utilities - main module.

This module provides a unified interface to all storage utilities.
Individual storage modules are organized by functionality:

- local_storage.py: Local filesystem storage
- table_storage.py: Azure Table Storage
- blob_storage.py: Azure Blob Storage
"""

# Import all storage functions for backward compatibility
from .local_storage import (
    save_circuit_locally,
    load_circuit_locally,
    get_circuit_info
)

from .table_storage import (
    save_circuit_metadata_to_table,
    get_circuit_metadata_from_table,
    list_circuits_from_table,
    delete_circuit_metadata_from_table
)

from .blob_storage import (
    upload_circuit_blob,
    download_circuit_blob
)

# Removed SQL storage imports - no longer using SQL database

# Re-export for convenience
__all__ = [
    # Local storage
    'save_circuit_locally',
    'load_circuit_locally', 
    'get_circuit_info',
    
    # Table storage
    'save_circuit_metadata_to_table',
    'get_circuit_metadata_from_table',
    'list_circuits_from_table',
    'delete_circuit_metadata_from_table',
    
    # Blob storage
    'upload_circuit_blob',
    'download_circuit_blob',
    
    # Removed SQL storage functions - no longer using SQL database
]