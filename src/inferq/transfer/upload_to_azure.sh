#!/bin/bash
# Upload circuits to Azure Blob Storage and Table Storage
# This is a convenience wrapper around upload_circuits_to_azure.py

set -e  # Exit on error

# Get directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/../.."
UPLOAD_SCRIPT="$SCRIPT_DIR/upload_circuits_to_azure.py"
TEST_SCRIPT="$SCRIPT_DIR/test_azure_upload_connection.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Circuit Upload to Azure${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if .env file exists
# Look for .env in project root first, then current directory
if [ -f "$PROJECT_ROOT/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/.env"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
    echo -e "${YELLOW}Using .env from current directory${NC}"
else
    echo -e "${RED}✗ Error: .env file not found${NC}"
    echo "Please create a .env file with your Azure credentials."
    echo "See .env.example or UPLOAD_CIRCUITS_README.md for details."
    exit 1
fi

# Source the .env file to load Azure credentials
echo -e "${BLUE}Loading Azure credentials from $ENV_FILE...${NC}"
source "$ENV_FILE"
echo -e "${GREEN}✓ Credentials loaded${NC}"
echo ""

# Test Azure connection first
echo -e "${BLUE}Testing Azure connection...${NC}"
if python "$TEST_SCRIPT"; then
    echo -e "${GREEN}✓ Azure connection successful${NC}"
    echo ""
else
    echo -e "${RED}✗ Azure connection failed${NC}"
    echo "Please fix the connection issues before proceeding."
    exit 1
fi

# Ask user what they want to do
echo -e "${YELLOW}What would you like to do?${NC}"
echo "  1) Dry run (test without uploading)"
echo "  2) Upload new circuits only (skip existing)"
echo "  3) Upload all circuits (force overwrite)"
echo "  4) Upload and delete local folders after success (save disk space)"
echo "  5) Exit"
echo ""
read -p "Enter your choice (1-5): " choice

case $choice in
    1)
        echo ""
        echo -e "${BLUE}Running dry run...${NC}"
        python "$UPLOAD_SCRIPT" --dry-run --verbose
        ;;
    2)
        echo ""
        echo -e "${BLUE}Uploading new circuits only...${NC}"
        python "$UPLOAD_SCRIPT" --verbose
        ;;
    3)
        echo ""
        echo -e "${YELLOW}⚠ WARNING: This will overwrite existing circuits in Azure${NC}"
        read -p "Are you sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            echo ""
            echo -e "${BLUE}Uploading all circuits (force mode)...${NC}"
            python "$UPLOAD_SCRIPT" --force --verbose
        else
            echo -e "${YELLOW}Upload cancelled${NC}"
            exit 0
        fi
        ;;
    4)
        echo ""
        echo -e "${RED}⚠️  WARNING: This will DELETE local circuit folders after successful upload!${NC}"
        echo -e "${RED}⚠️  Make sure you have backups or can regenerate these circuits!${NC}"
        echo ""
        read -p "Are you absolutely sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            echo ""
            echo -e "${BLUE}Uploading circuits and deleting local folders...${NC}"
            python "$UPLOAD_SCRIPT" --delete-after-upload --verbose
        else
            echo -e "${YELLOW}Upload cancelled${NC}"
            exit 0
        fi
        ;;
    5)
        echo -e "${BLUE}Exiting...${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Upload Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Check upload_circuits_to_azure.log for detailed logs."
