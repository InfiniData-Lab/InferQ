#!/usr/bin/env python3
"""
Azure Upload Manager Module

Handles batch uploads of circuits to Azure storage with detailed logging
and error handling. Provides efficient batch processing and comprehensive
status reporting.
"""

import logging
from typing import Any

from inferq.remote.blob import upload_circuit_blob
from inferq.remote.connection import AzureConnection
from inferq.remote.table import save_circuit_metadata_to_table

# Configure logging
logger = logging.getLogger(__name__)

def upload_batch_to_azure(circuit_batch: list[dict[str, Any]], azure_conn: AzureConnection) -> dict[str, Any]:
    """
    Upload a batch of circuits to Azure storage in parallel.
    
    Args:
        circuit_batch: List of circuit results to upload
        azure_conn: Azure connection instance
        
    Returns:
        Dictionary with upload statistics including successful and failed hashes
    """
    if not azure_conn:
        return {'uploaded': 0, 'failed': 0, 'error': 'No Azure connection', 'successful_hashes': [], 'failed_hashes': []}
    
    uploaded = 0
    failed = 0
    successful_hashes = []
    failed_hashes = []
    
    # Log the start of Azure upload batch
    logger.warning(f"🔄 AZURE UPLOAD STARTING: Processing {len(circuit_batch)} circuits for cloud storage")
    
    try:
        container_client = azure_conn.get_container_client()
        table_client = azure_conn.get_circuits_table_client()
        
        for i, result in enumerate(circuit_batch, 1):
            if not result.get('success') or not result.get('written'):
                continue
                
            qpy_hash = result['circuit_hash']
            
            try:
                circuit = result['circuit']
                features = result['features']
                serialization_method = result['serialization_method']
                worker_id = result.get('worker_id', 'unknown')
                
                logger.debug(f"☁️  UPLOADING [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... from Worker-{worker_id} ({circuit.num_qubits}q, depth={circuit.depth()})")
                
                # Upload to blob storage
                blob_path = upload_circuit_blob(
                    container_client, circuit, qpy_hash, serialization_method
                )
                features["blob_path"] = blob_path.split("circuits/")[1] if "circuits/" in blob_path else blob_path
                
                # Save metadata to table storage
                table_success = save_circuit_metadata_to_table(table_client, features)
                
                if table_success:
                    uploaded += 1
                    successful_hashes.append(qpy_hash)
                    logger.debug(f"✅ AZURE SUCCESS [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... uploaded to cloud storage")
                else:
                    failed += 1
                    failed_hashes.append(qpy_hash)
                    logger.warning(f"❌ AZURE METADATA FAILED [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... blob uploaded but metadata failed")
                    
            except Exception as e:
                failed += 1
                failed_hashes.append(qpy_hash)
                logger.warning(f"❌ AZURE UPLOAD FAILED [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... - {str(e)}")
                
    except Exception as e:
        logger.warning(f"❌ AZURE BATCH FAILED: Critical error during batch upload - {str(e)}")
        # Mark all circuits as failed
        all_hashes = [result.get('circuit_hash') for result in circuit_batch if result.get('circuit_hash')]
        return {'uploaded': 0, 'failed': len(circuit_batch), 'error': str(e), 'successful_hashes': [], 'failed_hashes': all_hashes}
    
    # Log the completion of Azure upload batch
    if uploaded > 0:
        logger.warning(f"🎉 AZURE UPLOAD COMPLETED: {uploaded} circuits successfully stored in cloud, {failed} failed")
    else:
        logger.warning(f"⚠️  AZURE UPLOAD COMPLETED: No circuits uploaded, {failed} failed")
    
    return {
        'uploaded': uploaded, 
        'failed': failed,
        'successful_hashes': successful_hashes,
        'failed_hashes': failed_hashes
    }

def should_trigger_upload(upload_buffer: list[dict[str, Any]], azure_upload_interval: int) -> bool:
    """
    Check if Azure upload should be triggered based on buffer size.
    
    Args:
        upload_buffer: Current upload buffer
        azure_upload_interval: Upload threshold
        
    Returns:
        True if upload should be triggered, False otherwise
    """
    return len(upload_buffer) >= azure_upload_interval

def log_upload_trigger(buffer_size: int, threshold: int) -> None:
    """
    Log when Azure upload is triggered.
    
    Args:
        buffer_size: Current buffer size
        threshold: Upload threshold
    """
    logger.warning(f"🚀 AZURE UPLOAD TRIGGERED: Buffer reached {buffer_size} circuits (threshold: {threshold})")

def log_final_upload(buffer_size: int) -> None:
    """
    Log when final Azure upload is triggered during shutdown.
    
    Args:
        buffer_size: Current buffer size
    """
    logger.warning(f"🏁 FINAL AZURE UPLOAD: Processing {buffer_size} remaining circuits before shutdown")