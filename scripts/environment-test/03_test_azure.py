#!/usr/bin/env python3
"""
Test 3: Azure Connectivity Verification
Tests Azure services connection and authentication
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not available, environment variables must be set manually")
    load_dotenv = None

def test_azure_imports():
    """Test if Azure packages can be imported"""
    print("📦 Testing Azure Package Imports...")
    
    azure_packages = [
        ('azure.storage.blob', 'Azure Blob Storage'),
        ('azure.data.tables', 'Azure Table Storage'),
        ('azure.identity', 'Azure Identity/Authentication'),
        ('azure.core', 'Azure Core Libraries')
    ]
    
    all_good = True
    for package, description in azure_packages:
        try:
            __import__(package)
            print(f"   ✅ {package:20} - {description}")
        except ImportError as e:
            print(f"   ❌ {package:20} - {description} (Error: {e})")
            all_good = False
    
    return all_good

def test_azure_environment_variables():
    """Test Azure environment variables"""
    print("\n🔑 Testing Azure Environment Variables...")
    
    # Check for Azure storage account and key (your actual configuration)
    account_name = os.getenv('AZURE_STORAGE_ACCOUNT')
    account_key = os.getenv('AZURE_STORAGE_ACCOUNT_KEY')
    
    if account_name and account_key:
        print("   ✅ AZURE_STORAGE_ACCOUNT and AZURE_STORAGE_ACCOUNT_KEY are set")
        print(f"   Account: {account_name}")
        print(f"   Key length: {len(account_key)} characters")
        has_account_creds = True
    else:
        print("   ⚠️  AZURE_STORAGE_ACCOUNT or AZURE_STORAGE_ACCOUNT_KEY not set")
        has_account_creds = False
    
    # Check for SAS token and container URL
    sas_token = os.getenv('AZURE_STORAGE_SAS_TOKEN')
    container_url = os.getenv('AZURE_CONTAINER_SAS_URL')
    
    if sas_token and container_url:
        print("   ✅ AZURE_STORAGE_SAS_TOKEN and AZURE_CONTAINER_SAS_URL are set")
        print(f"   SAS token length: {len(sas_token)} characters")
        print(f"   Container URL: {container_url.split('?')[0]}...")  # Hide SAS part
        has_sas_creds = True
    else:
        print("   ⚠️  SAS token or container URL not set")
        has_sas_creds = False
    
    # Check for legacy connection string (fallback)
    connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
    if connection_string:
        print("   ✅ AZURE_STORAGE_CONNECTION_STRING is also set (fallback)")
        has_connection_string = True
    else:
        print("   ⚠️  AZURE_STORAGE_CONNECTION_STRING not set (optional)")
        has_connection_string = False
    
    # Check for container and table names
    container_name = os.getenv('AZURE_CONTAINER', 'circuits')
    table_name = os.getenv('AZURE_TABLE', 'circuits')
    
    print(f"   Container name: {container_name}")
    print(f"   Table name: {table_name}")
    
    # Return true if we have either account key or SAS credentials
    return has_account_creds or has_sas_creds

def test_azure_connection():
    """Test actual Azure connection"""
    print("\n🌐 Testing Azure Connection...")
    
    try:
        # Load environment variables from .env file
        if load_dotenv:
            load_dotenv()
            print("   ✅ Loaded environment variables from .env file")
        else:
            print("   ⚠️  dotenv not available, using system environment variables")
        
        # Import Azure utilities from the project
        sys.path.insert(0, str(Path.cwd()))
        from utils.azure_connection import AzureConnection
        
        print("   ✅ Azure connection module imported")
        
        # Try to create connection
        try:
            azure_conn = AzureConnection()
            print("   ✅ Azure connection object created")
            
            # Test table storage
            try:
                table_client = azure_conn.get_circuits_table_client()
                print("   ✅ Table Storage client created")
                
                # Try to get table properties (lightweight operation)
                try:
                    properties = table_client.get_table_access_policy()
                    print("   ✅ Table Storage accessible")
                    table_ok = True
                except Exception as e:
                    print(f"   ⚠️  Table Storage access issue: {e}")
                    table_ok = False
                    
            except Exception as e:
                print(f"   ❌ Table Storage client failed: {e}")
                table_ok = False
            
            # Test blob storage
            try:
                container_client = azure_conn.get_container_client()
                print("   ✅ Blob Storage client created")
                
                # Try to get container properties
                try:
                    properties = container_client.get_container_properties()
                    print("   ✅ Blob Storage accessible")
                    blob_ok = True
                except Exception as e:
                    print(f"   ⚠️  Blob Storage access issue: {e}")
                    blob_ok = False
                    
            except Exception as e:
                print(f"   ❌ Blob Storage client failed: {e}")
                blob_ok = False
            
            return table_ok and blob_ok
            
        except Exception as e:
            print(f"   ❌ Azure connection failed: {e}")
            return False
            
    except ImportError as e:
        print(f"   ❌ Cannot import Azure utilities: {e}")
        print("   Make sure you're running from the project root directory")
        return False

def test_azure_write_permissions():
    """Test Azure write permissions with a small test"""
    print("\n✍️  Testing Azure Write Permissions...")
    
    try:
        sys.path.insert(0, str(Path.cwd()))
        from utils.azure_connection import AzureConnection
        import json
        from datetime import datetime
        
        azure_conn = AzureConnection()
        
        # Test table write
        try:
            table_client = azure_conn.get_circuits_table_client()
            
            # Create a test entity
            test_entity = {
                'PartitionKey': 'test',
                'RowKey': f'test_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                'TestData': 'Environment test',
                'Timestamp': datetime.now().isoformat()
            }
            
            # Try to insert (will be cleaned up)
            table_client.create_entity(test_entity)
            print("   ✅ Table Storage write test successful")
            
            # Clean up test entity
            try:
                table_client.delete_entity(test_entity['PartitionKey'], test_entity['RowKey'])
                print("   ✅ Table Storage cleanup successful")
            except:
                print("   ⚠️  Table Storage cleanup failed (entity may remain)")
            
            table_write_ok = True
            
        except Exception as e:
            print(f"   ❌ Table Storage write test failed: {e}")
            table_write_ok = False
        
        # Test blob write
        try:
            container_client = azure_conn.get_container_client()
            
            # Create test blob
            test_blob_name = f"test/environment_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            test_data = json.dumps({'test': 'environment_verification', 'timestamp': datetime.now().isoformat()})
            
            blob_client = container_client.get_blob_client(test_blob_name)
            blob_client.upload_blob(test_data, overwrite=True)
            print("   ✅ Blob Storage write test successful")
            
            # Clean up test blob
            try:
                blob_client.delete_blob()
                print("   ✅ Blob Storage cleanup successful")
            except:
                print("   ⚠️  Blob Storage cleanup failed (blob may remain)")
            
            blob_write_ok = True
            
        except Exception as e:
            print(f"   ❌ Blob Storage write test failed: {e}")
            blob_write_ok = False
        
        return table_write_ok and blob_write_ok
        
    except Exception as e:
        print(f"   ❌ Azure write test setup failed: {e}")
        return False

def main():
    """Run all Azure tests"""
    print("=" * 60)
    print("☁️  AZURE CONNECTIVITY TEST")
    print("=" * 60)
    
    # Run tests
    imports_ok = test_azure_imports()
    env_vars_ok = test_azure_environment_variables()
    
    if not imports_ok:
        print("\n❌ Azure packages not available - skipping connection tests")
        print("   Install Azure packages or run in local-only mode")
        return 1
    
    if not env_vars_ok:
        print("\n⚠️  Azure credentials not configured")
        print("   Set AZURE_STORAGE_CONNECTION_STRING or individual credentials")
        print("   Pipeline will run in LOCAL-ONLY mode")
        connection_ok = False
        write_ok = False
    else:
        connection_ok = test_azure_connection()
        if connection_ok:
            write_ok = test_azure_write_permissions()
        else:
            write_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 AZURE TEST SUMMARY")
    print("=" * 60)
    
    tests = [
        ("Package Imports", imports_ok),
        ("Environment Variables", env_vars_ok),
        ("Connection", connection_ok),
        ("Write Permissions", write_ok)
    ]
    
    passed = 0
    for test_name, result in tests:
        if result:
            status = "✅ PASS"
            passed += 1
        elif test_name in ["Environment Variables", "Connection", "Write Permissions"] and not env_vars_ok:
            status = "⚠️  SKIP"
        else:
            status = "❌ FAIL"
        
        print(f"{status:8} {test_name}")
    
    print(f"\nPassed: {passed}/{len(tests)} tests")
    
    if imports_ok:
        if connection_ok and write_ok:
            print("🎉 Azure services are fully functional!")
            return 0
        elif env_vars_ok:
            print("⚠️  Azure configured but has connection issues")
            return 1
        else:
            print("ℹ️  Azure not configured - will run in local-only mode")
            return 0
    else:
        print("❌ Azure packages missing")
        return 1

if __name__ == "__main__":
    exit(main())