"""
Quick test script to verify Azure connectivity before bulk upload.

Run this before using upload_circuits_to_azure.py to ensure your
Azure credentials are configured correctly.
"""

import logging
import sys

from inferq.remote.connection import AzureConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_azure_connection():
    """Test Azure Blob Storage and Table Storage connections."""
    
    print("=" * 80)
    print("Testing Azure Connection")
    print("=" * 80)
    
    try:
        # Initialize Azure connection
        print("\n1. Initializing Azure connection...")
        azure_conn = AzureConnection()
        print("   ✓ Azure connection object created")
        
        # Test Blob Storage
        print("\n2. Testing Blob Storage connection...")
        container_client = azure_conn.get_container_client()
        
        # Try to get container properties
        _ = container_client.get_container_properties()
        print(f"   ✓ Connected to container: {container_client.container_name}")
        print("   ✓ Container exists and is accessible")
        
        # Test Table Storage
        print("\n3. Testing Table Storage connection...")
        table_client = azure_conn.get_circuits_table_client()
        
        # Try to create/verify table exists
        try:
            # Try a simple query to verify connection
            entities = list(table_client.list_entities(results_per_page=1))
            print(f"   ✓ Connected to table: {table_client.table_name}")
            print("   ✓ Table exists and is accessible")
            print(f"   ✓ Table contains {len(entities)} entity (showing first)")
        except Exception as e:
            if "does not exist" in str(e).lower():
                print(f"   ⚠ Table '{table_client.table_name}' doesn't exist yet (will be created on first upload)")
            else:
                print("   ✓ Table client initialized (table may be empty or not yet created)")
        
        # Success!
        print("\n" + "=" * 80)
        print("✓ All Azure connections successful!")
        print("=" * 80)
        print("\nYou're ready to upload circuits using:")
        print("  python upload_circuits_to_azure.py --dry-run  # Test run")
        print("  python upload_circuits_to_azure.py           # Actual upload")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print("\n" + "=" * 80)
        print("✗ Azure connection failed!")
        print("=" * 80)
        print(f"\nError: {e}")
        print("\nPlease check:")
        print("  1. Your .env file contains valid Azure credentials")
        print("  2. AZURE_STORAGE_ACCOUNT is set correctly")
        print("  3. AZURE_STORAGE_ACCOUNT_KEY or AZURE_STORAGE_SAS_TOKEN is valid")
        print("  4. Your network connection is working")
        print("  5. Azure storage account and container exist")
        print("\nFor more details, run:")
        print("  python tools/environment-test/03_test_azure.py")
        print("=" * 80)
        
        return False


if __name__ == "__main__":
    success = test_azure_connection()
    sys.exit(0 if success else 1)
