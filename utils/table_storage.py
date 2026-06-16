"""
Azure Table Storage utilities for quantum circuit metadata.

This module handles saving, retrieving, and managing circuit metadata
in Azure Table Storage.
"""

import json
import logging
import numpy as np
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from .azure_connection import table_safe

# Configure logging
logger = logging.getLogger(__name__)


def _json_serializer(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, "item"):  # numpy scalar
        return obj.item()

    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _convert_numpy_types(value):
    """Convert numpy types to Python native types for Azure Tables"""
    if isinstance(value, np.integer):
        return int(value)
    elif isinstance(value, np.floating):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    elif isinstance(value, np.ndarray):
        return value.tolist()
    elif hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def save_circuit_metadata_to_table(
    table_client: TableClient, features: Dict[str, Any]
) -> bool:
    """
    Save circuit metadata to Azure Table Storage.

    Args:
        table_client: Azure Table client for the circuits table
        features: Dictionary containing circuit metadata

    Returns:
        bool: True if successful, False otherwise
    """
    if "qpy_sha256" not in features:
        logger.error("Missing required 'qpy_sha256' in features dictionary")
        raise ValueError("'features' dict must contain 'qpy_sha256'")

    circuit_hash = features["qpy_sha256"]
    logger.info(f"Saving circuit metadata to table: {circuit_hash}")
    logger.debug(f"Features to save: {len(features)} items")

    try:
        # Prepare entity for Azure Tables
        logger.debug("Preparing entity for Azure Table Storage...")
        entity = {
            "PartitionKey": "circuits",  # Use a single partition for simplicity
            "RowKey": circuit_hash,  # Use hash as unique row key
            "Timestamp": datetime.now(timezone.utc),
        }

        # Add all features to the entity, ensuring property names are table-safe
        processed_features = 0
        for key, value in features.items():
            if key == "qpy_sha256":
                continue  # Already used as RowKey

            safe_key = table_safe(key)

            # Handle different data types for Azure Tables
            # First convert numpy types to Python native types
            converted_value = _convert_numpy_types(value)

            if isinstance(converted_value, (int, float, str, bool)):
                entity[safe_key] = converted_value
            elif isinstance(converted_value, (list, dict)):
                # Convert complex types to JSON strings
                entity[safe_key] = json.dumps(converted_value, default=_json_serializer)
            else:
                # Convert other types to string
                entity[safe_key] = str(converted_value)

            processed_features += 1

        logger.debug(f"✓ Processed {processed_features} features for table storage")

        # Try to insert or update the entity
        logger.debug("Attempting to save entity to Azure Table...")
        try:
            table_client.create_entity(entity)
            logger.info(f"✓ Circuit metadata saved to table: {circuit_hash}")
        except ResourceExistsError:
            # Entity exists, update it
            logger.debug("Entity exists, updating...")
            table_client.update_entity(entity, mode="replace")
            logger.info(f"✓ Circuit metadata updated in table: {circuit_hash}")

        return True

    except Exception as e:
        logger.error(f"Failed to save metadata to table for {circuit_hash}: {e}")
        return False


def update_circuit_metadata_in_table(
    table_client: TableClient, qpy_sha256: str, updates: Dict[str, Any]
) -> bool:
    """
    Update specific fields of circuit metadata in Azure Table Storage (merge).

    Args:
        table_client: Azure Table client for the circuits table
        qpy_sha256: Circuit hash (RowKey)
        updates: Dictionary containing fields to update

    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"Updating circuit metadata in table: {qpy_sha256}")

    try:
        entity = {
            "PartitionKey": "circuits",
            "RowKey": qpy_sha256,
        }

        for key, value in updates.items():
            safe_key = table_safe(key)
            converted_value = _convert_numpy_types(value)

            if isinstance(converted_value, (int, float, str, bool)):
                entity[safe_key] = converted_value
            elif isinstance(converted_value, (list, dict)):
                entity[safe_key] = json.dumps(converted_value, default=_json_serializer)
            else:
                entity[safe_key] = str(converted_value)

        table_client.update_entity(entity, mode="merge")
        logger.info(f"✓ Circuit metadata updated (merge) in table: {qpy_sha256}")
        return True

    except Exception as e:
        logger.error(f"Failed to update metadata in table for {qpy_sha256}: {e}")
        return False


def get_circuit_metadata_from_table(
    table_client: TableClient, qpy_sha256: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieve circuit metadata from Azure Table Storage.

    Args:
        table_client: Azure Table client for the circuits table
        qpy_sha256: Circuit hash to retrieve

    Returns:
        Dictionary containing circuit metadata or None if not found
    """
    logger.info(f"Retrieving circuit metadata from table: {qpy_sha256}")

    try:
        logger.debug("Querying Azure Table Storage...")
        entity = table_client.get_entity(partition_key="circuits", row_key=qpy_sha256)
        logger.debug("✓ Entity retrieved from table")

        # Convert entity back to regular dictionary
        logger.debug("Converting entity to metadata dictionary...")
        metadata = {}
        processed_fields = 0

        for key, value in entity.items():
            if key in ["PartitionKey", "RowKey", "Timestamp", "etag"]:
                continue  # Skip Azure Table system properties

            # Try to parse JSON strings back to objects
            if isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                    metadata[key] = parsed_value
                except (json.JSONDecodeError, TypeError):
                    metadata[key] = value
            else:
                metadata[key] = value

            processed_fields += 1

        # Add the hash back
        metadata["qpy_sha256"] = qpy_sha256

        logger.info(f"✓ Circuit metadata retrieved: {processed_fields} fields")
        return metadata

    except ResourceNotFoundError:
        logger.warning(f"Circuit metadata not found in table: {qpy_sha256}")
        return None
    except Exception as e:
        logger.error(f"Failed to retrieve metadata from table for {qpy_sha256}: {e}")
        return None


def list_circuits_from_table(table_client: TableClient, limit: int = 100) -> list:
    """
    List circuits from Azure Table Storage.

    Args:
        table_client: Azure Table client for the circuits table
        limit: Maximum number of circuits to return

    Returns:
        List of circuit metadata dictionaries
    """
    try:
        entities = table_client.list_entities(
            select=[
                "RowKey",
                "num_qubits",
                "circuit_depth",
                "circuit_size",
                "serialization_method",
                "Timestamp",
            ]
        )

        circuits = []
        count = 0
        for entity in entities:
            if count >= limit:
                break
            metadata=entity.metadata
            circuit_info = {
                "qpy_sha256": entity["RowKey"],
                "num_qubits": entity.get("num_qubits"),
                "circuit_depth": entity.get("circuit_depth"),
                "circuit_size": entity.get("circuit_size"),
                "serialization_method": entity.get("serialization_method"),
                "timestamp": metadata["timestamp"] if metadata else None,
            }
            circuits.append(circuit_info)
            count += 1

        return circuits

    except Exception as e:
        logger.error(f"Failed to list circuits from table: {e}")
        return []


def delete_circuit_metadata_from_table(
    table_client: TableClient, qpy_sha256: str
) -> bool:
    """
    Delete circuit metadata from Azure Table Storage.

    Args:
        table_client: Azure Table client for the circuits table
        qpy_sha256: Circuit hash to delete

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        table_client.delete_entity(partition_key="circuits", row_key=qpy_sha256)
        logger.info(f"✓ Circuit metadata deleted from table: {qpy_sha256}")
        return True

    except ResourceNotFoundError:
        logger.warning(f"Circuit metadata not found for deletion: {qpy_sha256}")
        return False
    except Exception as e:
        logger.error(f"Failed to delete metadata from table: {e}")
        return False
