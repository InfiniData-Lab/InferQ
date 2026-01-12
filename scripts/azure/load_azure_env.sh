#!/bin/bash
# Simple Azure Environment Loader
# Run this from the project root: source ./load_azure_env.sh

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔧 Loading Azure Environment Variables${NC}"

# Check if .env file exists in current directory
if [ -f ".env" ]; then
    echo "✅ Found .env file"
    
    # Load environment variables
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        if [[ $key =~ ^[[:space:]]*# ]] || [[ -z $key ]]; then
            continue
        fi
        
        # Remove quotes from value
        value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
        
        # Export the variable
        export "$key"="$value"
        
        # Only show Azure-related variables
        if [[ $key == AZURE_* ]]; then
            echo "  ✅ $key"
        fi
    done < ".env"
    
    echo ""
    echo -e "${GREEN}Azure environment variables loaded!${NC}"
    echo ""
    echo "You can now run:"
    echo "  python3 test-env-scripts/03_test_azure.py"
    echo "  ./test-env-scripts/run_all_tests.sh"
    
else
    echo -e "${RED}❌ .env file not found in current directory${NC}"
    echo ""
    echo "Make sure you're in the project root directory and have a .env file with:"
    echo "  AZURE_STORAGE_ACCOUNT=your_account"
    echo "  AZURE_STORAGE_ACCOUNT_KEY=your_key"
    echo "  AZURE_STORAGE_SAS_TOKEN=your_token"
    echo "  AZURE_CONTAINER_SAS_URL=your_url"
fi