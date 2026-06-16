#!/bin/bash
# Azure Connection Checker
# Validates Azure services connectivity

# Source system info for colored output
source "$(dirname "$0")/system_info.sh"

# Check Azure connection
check_azure_connection() {
    print_status "Checking Azure connection..."
    
    python3 -c "
try:
    from utils.azure_connection import AzureConnection
    conn = AzureConnection()
    print('✓ Azure connection successful')
    
    # Test table storage
    try:
        table_client = conn.get_circuits_table_client()
        print('✓ Table Storage accessible')
    except Exception as e:
        print(f'⚠️  Table Storage issue: {e}')
    
    # Test blob storage
    try:
        container_client = conn.get_container_client()
        print('✓ Blob Storage accessible')
    except Exception as e:
        print(f'⚠️  Blob Storage issue: {e}')
        
except ImportError as e:
    print(f'⚠️  Azure libraries not installed: {e}')
    print('⚠️  Pipeline will run in LOCAL ONLY mode')
except Exception as e:
    print(f'⚠️  Azure connection failed: {e}')
    print('⚠️  Pipeline will run in LOCAL ONLY mode')
" 2>/dev/null || print_warning "Could not check Azure connection"
    
    echo ""
}

# Validate Azure environment variables
check_azure_env() {
    local missing_vars=()
    
    if [ -z "$AZURE_STORAGE_CONNECTION_STRING" ] && [ -z "$AZURE_STORAGE_ACCOUNT_NAME" ]; then
        missing_vars+=("AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME")
    fi
    
    if [ ${#missing_vars[@]} -gt 0 ]; then
        print_warning "Missing Azure environment variables:"
        for var in "${missing_vars[@]}"; do
            echo "  - $var"
        done
        print_warning "Pipeline will run in LOCAL ONLY mode"
        echo ""
        return 1
    fi
    
    return 0
}

# Main function when script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    check_azure_env
    check_azure_connection
fi