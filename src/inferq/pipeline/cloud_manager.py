#!/usr/bin/env python3
"""
Cloud Upload Manager Module

Handles batch uploads of circuits to cloud storage with detailed logging and
error handling. Works against the provider-neutral connection interface, so
the same batch logic serves Azure Blob + Table and S3 + DynamoDB. Log lines
name whichever provider is in use.
"""

import logging
from typing import Any

from inferq.remote import CloudConnection, save_circuit_metadata, upload_circuit_blob

# Configure logging
logger = logging.getLogger(__name__)

def upload_batch_to_cloud(circuit_batch: list[dict[str, Any]], cloud_conn: CloudConnection) -> dict[str, Any]:
    """
    Upload a batch of circuits to cloud storage.

    Args:
        circuit_batch: List of circuit results to upload
        cloud_conn: Connected cloud storage backend

    Returns:
        Dictionary with upload statistics including successful and failed hashes
    """
    if not cloud_conn:
        return {'uploaded': 0, 'failed': 0, 'error': 'No cloud connection', 'successful_hashes': [], 'failed_hashes': []}

    provider = cloud_conn.provider.upper()
    uploaded = 0
    failed = 0
    successful_hashes = []
    failed_hashes = []

    # Log the start of the upload batch
    logger.warning(f"🔄 {provider} UPLOAD STARTING: Processing {len(circuit_batch)} circuits for cloud storage")

    try:
        object_store = cloud_conn.objects
        metadata_store = cloud_conn.metadata

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

                # Upload the serialized circuit to object storage
                features["blob_path"] = upload_circuit_blob(
                    object_store, circuit, qpy_hash, serialization_method
                )

                # Save metadata to the metadata store
                metadata_success = save_circuit_metadata(metadata_store, features)

                if metadata_success:
                    uploaded += 1
                    successful_hashes.append(qpy_hash)
                    logger.debug(f"✅ {provider} SUCCESS [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... uploaded to cloud storage")
                else:
                    failed += 1
                    failed_hashes.append(qpy_hash)
                    logger.warning(f"❌ {provider} METADATA FAILED [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... object uploaded but metadata failed")

            except Exception as e:
                failed += 1
                failed_hashes.append(qpy_hash)
                logger.warning(f"❌ {provider} UPLOAD FAILED [{i}/{len(circuit_batch)}]: Circuit {qpy_hash[:8]}... - {str(e)}")

    except Exception as e:
        logger.warning(f"❌ {provider} BATCH FAILED: Critical error during batch upload - {str(e)}")
        # Mark all circuits as failed
        all_hashes = [result.get('circuit_hash') for result in circuit_batch if result.get('circuit_hash')]
        return {'uploaded': 0, 'failed': len(circuit_batch), 'error': str(e), 'successful_hashes': [], 'failed_hashes': all_hashes}

    # Log the completion of the upload batch
    if uploaded > 0:
        logger.warning(f"🎉 {provider} UPLOAD COMPLETED: {uploaded} circuits successfully stored in cloud, {failed} failed")
    else:
        logger.warning(f"⚠️  {provider} UPLOAD COMPLETED: No circuits uploaded, {failed} failed")

    return {
        'uploaded': uploaded,
        'failed': failed,
        'successful_hashes': successful_hashes,
        'failed_hashes': failed_hashes
    }

def should_trigger_upload(upload_buffer: list[dict[str, Any]], cloud_upload_interval: int) -> bool:
    """
    Check if a cloud upload should be triggered based on buffer size.

    Args:
        upload_buffer: Current upload buffer
        cloud_upload_interval: Upload threshold

    Returns:
        True if upload should be triggered, False otherwise
    """
    return len(upload_buffer) >= cloud_upload_interval

def log_upload_trigger(buffer_size: int, threshold: int) -> None:
    """
    Log when a cloud upload is triggered.

    Args:
        buffer_size: Current buffer size
        threshold: Upload threshold
    """
    logger.warning(f"🚀 CLOUD UPLOAD TRIGGERED: Buffer reached {buffer_size} circuits (threshold: {threshold})")

def log_final_upload(buffer_size: int) -> None:
    """
    Log when the final cloud upload is triggered during shutdown.

    Args:
        buffer_size: Current buffer size
    """
    logger.warning(f"🏁 FINAL CLOUD UPLOAD: Processing {buffer_size} remaining circuits before shutdown")
