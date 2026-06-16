#!/usr/bin/env python3
"""
Test script to verify Azure Table Storage connection.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from utils.azure_connection import AzureConnection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_table_connection():
    """Test the Azure Table Storage connection."""
    
    print("Testing Azure Table Storage Connection")
    print("=" * 50)
    
    try:
        # Test connection
        azure_conn = AzureConnection()
        print("✓ AzureConnection created successfully")
        
        # Test table service client
        table_service = azure_conn.get_table_service_client()
        print("✓ Table service client created successfully")
        
        # Test circuits table client
        table_client = azure_conn.get_circuits_table_client()
        print("✓ Circuits table client created successfully")
        
        # Try to list tables (this will test authentication)
        try:
            tables = list(table_service.list_tables())
            print(f"✓ Successfully listed {len(tables)} tables")
            for table in tables:
                print(f"  - {table.name}")
        except Exception as e:
            print(f"⚠️  Could not list tables: {e}")
        
        # Try to query the circuits table
        try:
            entities = list(table_client.list_entities(select=["RowKey"]))
            print(f"✓ Successfully queried circuits table: {len(entities)} entities found")
        except Exception as e:
            print(f"⚠️  Could not query circuits table: {e}")
        
        print("\n✅ Connection test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Connection test failed: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check if AZURE_STORAGE_ACCOUNT_KEY is set in .env")
        print("2. Verify your SAS token has table permissions (sr=a or sr=t)")
        print("3. Make sure your SAS token hasn't expired")
        return False

def show_env_info():
    """Show environment configuration (without sensitive data)."""
    
    print("\nEnvironment Configuration:")
    print("-" * 30)
    
    from dotenv import load_dotenv
    load_dotenv()
    
    account = os.environ.get("AZURE_STORAGE_ACCOUNT", "Not set")
    account_key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY", "Not set")
    sas_token = os.environ.get("AZURE_STORAGE_SAS_TOKEN", "Not set")
    
    print(f"Storage Account: {account}")
    print(f"Account Key: {'Set' if account_key != 'Not set' else 'Not set'}")
    print(f"SAS Token: {'Set' if sas_token != 'Not set' else 'Not set'}")
    
    if sas_token != "Not set":
        # Parse SAS token to show permissions
        if "sp=" in sas_token:
            permissions = sas_token.split("sp=")[1].split("&")[0]
            print(f"SAS Permissions: {permissions}")
        
        if "sr=" in sas_token:
            resource = sas_token.split("sr=")[1].split("&")[0]
            resource_types = {
                'a': 'Account',
                'c': 'Container', 
                't': 'Table',
                'b': 'Blob',
                'o': 'Object'
            }
            print(f"SAS Resource Type: {resource_types.get(resource, resource)}")

if __name__ == "__main__":
    show_env_info()
    test_table_connection()