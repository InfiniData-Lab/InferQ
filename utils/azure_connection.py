import os
import struct
from azure import identity
from dotenv import load_dotenv
import re
from azure.storage.blob import ContainerClient
from azure.data.tables import TableServiceClient, TableClient
import logging

load_dotenv()

# Configuration
container_connection_string = os.environ["AZURE_CONTAINER_SAS_URL"]
storage_account_name = os.environ["AZURE_STORAGE_ACCOUNT"]
sas_token = os.environ["AZURE_STORAGE_SAS_TOKEN"]

# Try to get account key from environment (more reliable for tables)
storage_account_key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")

# Table configuration
CIRCUITS_TABLE_NAME = "circuits"

logger = logging.getLogger(__name__)

def table_safe(name: str) -> str:
    """
    Turn arbitrary feature names into Azure Table-safe property names.
    Azure Tables have restrictions on property names.
    """
    # Replace invalid characters with underscores
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", name.strip())
    # Ensure it doesn't start with a number
    if cleaned and cleaned[0].isdigit():
        cleaned = f"prop_{cleaned}"
    return cleaned.lower()

# Removed sql_safe function - no longer needed

class AzureConnection:
    def __init__(self):
        # Get Azure configuration from centralized config
        from config import get_azure_config
        self.azure_config = get_azure_config()
        
        self.container_client = self.create_container_client()
        self.table_service_client = self.create_table_service_client()
        self.circuits_table_client = self.create_circuits_table_client()

    # Removed create_sql_conn method - no longer needed
    
    def create_container_client(self) -> ContainerClient:
        """Create blob container client"""
        # Use container name from config
        container_name = self.azure_config.get('container_name', 'circuits')
        
        # If we have a full container connection string, use it directly
        # Otherwise, build the container client using the configured container name
        if container_connection_string and container_name in container_connection_string:
            container_client = ContainerClient.from_container_url(container_connection_string)
        else:
            # Build container client from account details with configured container name
            account_url = f"https://{storage_account_name}.blob.core.windows.net"
            if storage_account_key:
                connection_string = f"DefaultEndpointsProtocol=https;AccountName={storage_account_name};AccountKey={storage_account_key};EndpointSuffix=core.windows.net"
                container_client = ContainerClient.from_connection_string(connection_string, container_name=container_name)
            else:
                from azure.core.credentials import AzureSasCredential
                clean_sas = sas_token.lstrip('?')
                credential = AzureSasCredential(clean_sas)
                container_client = ContainerClient(account_url=account_url, container_name=container_name, credential=credential)
        
        return container_client
    
    def create_table_service_client(self) -> TableServiceClient:
        """Create table service client"""
        account_url = f"https://{storage_account_name}.table.core.windows.net"
        
        # Try different authentication methods
        if storage_account_key:
            # Use account key (most reliable)
            connection_string = f"DefaultEndpointsProtocol=https;AccountName={storage_account_name};AccountKey={storage_account_key};EndpointSuffix=core.windows.net"
            table_service_client = TableServiceClient.from_connection_string(connection_string)
        else:
            # Fallback to SAS token (may have permission issues)
            try:
                # Try using SAS token directly
                from azure.core.credentials import AzureSasCredential
                clean_sas = sas_token.lstrip('?')
                credential = AzureSasCredential(clean_sas)
                table_service_client = TableServiceClient(endpoint=account_url, credential=credential)
            except Exception as e:
                logger.warning(f"SAS token authentication failed: {e}")
                # Last resort: try with full URL
                clean_sas = sas_token if sas_token.startswith('?') else f'?{sas_token}'
                endpoint_with_sas = f"{account_url}{clean_sas}"
                table_service_client = TableServiceClient(endpoint=endpoint_with_sas)
        
        return table_service_client
    
    def create_circuits_table_client(self) -> TableClient:
        """Create table client for circuits table"""
        account_url = f"https://{storage_account_name}.table.core.windows.net"
        # Use table name from config
        table_name = self.azure_config.get('table_name', CIRCUITS_TABLE_NAME)
        
        # Try different authentication methods
        if storage_account_key:
            # Use account key (most reliable)
            connection_string = f"DefaultEndpointsProtocol=https;AccountName={storage_account_name};AccountKey={storage_account_key};EndpointSuffix=core.windows.net"
            table_client = TableClient.from_connection_string(connection_string, table_name=table_name)
        else:
            # Fallback to SAS token
            try:
                from azure.core.credentials import AzureSasCredential
                clean_sas = sas_token.lstrip('?')
                credential = AzureSasCredential(clean_sas)
                table_client = TableClient(endpoint=account_url, table_name=table_name, credential=credential)
            except Exception as e:
                logger.warning(f"SAS token authentication failed: {e}")
                # Last resort: try with full URL
                clean_sas = sas_token if sas_token.startswith('?') else f'?{sas_token}'
                endpoint_with_sas = f"{account_url}{clean_sas}"
                table_client = TableClient(endpoint=endpoint_with_sas, table_name=table_name)
        
        # Create table if it doesn't exist
        try:
            table_client.create_table()
            logger.info(f"Created table: {table_name}")
        except Exception as e:
            if "TableAlreadyExists" in str(e) or "already exists" in str(e).lower():
                logger.debug(f"Table {table_name} already exists")
            else:
                logger.warning(f"Error creating table: {e}")
        
        return table_client
    
    # Removed get_conn method - no longer needed
    
    def get_container_client(self) -> ContainerClient:
        """Get blob container client"""
        return self.container_client
    
    def get_table_service_client(self) -> TableServiceClient:
        """Get table service client"""
        return self.table_service_client
    
    def get_circuits_table_client(self) -> TableClient:
        """Get circuits table client"""
        return self.circuits_table_client