#!/bin/bash
# Azure Environment Setup Helper
# This script helps set up Azure environment variables for testing

echo "🔧 Azure Environment Setup Helper"
echo "================================="

# Debug information
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "Script directory: $SCRIPT_DIR"
echo "Project root: $PROJECT_ROOT"
echo "Looking for .env file at: $PROJECT_ROOT/.env"
echo ""

# Set up paths (already defined above)
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    echo "✅ Found .env file in project root"
    echo "Loading environment variables from .env file..."
    
    # Source the .env file (convert to bash format)
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        if [[ $key =~ ^[[:space:]]*# ]] || [[ -z $key ]]; then
            continue
        fi
        
        # Remove quotes from value
        value=$(echo "$value" | sed 's/^["\x27]//;s/["\x27]$//')
        
        # Export the variable
        export "$key"="$value"
        echo "  ✅ $key"
    done < "$ENV_FILE"
    
    echo ""
    echo "Environment variables loaded! You can now run:"
    echo "  python3 03_test_azure.py"
    echo "  ./run_all_tests.sh"
    
else
    echo "⚠️  No .env file found in project root"
    echo ""
    echo "Please create a .env file with your Azure credentials:"
    echo ""
    echo "AZURE_STORAGE_ACCOUNT=your_account_name"
    echo "AZURE_STORAGE_ACCOUNT_KEY=your_account_key"
    echo "AZURE_STORAGE_SAS_TOKEN=your_sas_token"
    echo "AZURE_CONTAINER_SAS_URL=your_container_url"
    echo ""
    echo "Or set them manually:"
    echo "  export AZURE_STORAGE_ACCOUNT=your_account_name"
    echo "  export AZURE_STORAGE_ACCOUNT_KEY=your_account_key"
fi

# Verify key variables are set
echo ""
echo "🔍 Verifying Azure Configuration:"

if [ -n "$AZURE_STORAGE_ACCOUNT" ]; then
    echo "  ✅ AZURE_STORAGE_ACCOUNT: $AZURE_STORAGE_ACCOUNT"
else
    echo "  ❌ AZURE_STORAGE_ACCOUNT: Not set"
fi

if [ -n "$AZURE_STORAGE_ACCOUNT_KEY" ]; then
    echo "  ✅ AZURE_STORAGE_ACCOUNT_KEY: Set (${#AZURE_STORAGE_ACCOUNT_KEY} characters)"
else
    echo "  ❌ AZURE_STORAGE_ACCOUNT_KEY: Not set"
fi

if [ -n "$AZURE_STORAGE_SAS_TOKEN" ]; then
    echo "  ✅ AZURE_STORAGE_SAS_TOKEN: Set (${#AZURE_STORAGE_SAS_TOKEN} characters)"
else
    echo "  ❌ AZURE_STORAGE_SAS_TOKEN: Not set"
fi

if [ -n "$AZURE_CONTAINER_SAS_URL" ]; then
    echo "  ✅ AZURE_CONTAINER_SAS_URL: Set"
else
    echo "  ❌ AZURE_CONTAINER_SAS_URL: Not set"
fi

echo ""
echo "💡 Note: You need either:"
echo "   1. AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCOUNT_KEY, or"
echo "   2. AZURE_STORAGE_SAS_TOKEN + AZURE_CONTAINER_SAS_URL"