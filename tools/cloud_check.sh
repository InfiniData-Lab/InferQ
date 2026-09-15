#!/bin/bash
# Cloud connection checker
# Validates connectivity to whichever cloud provider is configured

# Source system info for colored output
source "$(dirname "$0")/system_info.sh"

# Check the cloud connection
check_cloud_connection() {
    print_status "Checking cloud connection..."

    python3 -c "
try:
    from inferq.remote import get_connection
    conn = get_connection()
    print(f'✓ {conn.provider} connection successful')

    # Test the metadata store
    try:
        conn.metadata.ping()
        print(f'✓ Metadata store accessible ({conn.metadata.name})')
    except Exception as e:
        print(f'⚠️  Metadata store issue: {e}')

    # Test the object store
    try:
        conn.objects.ping()
        print(f'✓ Object store accessible ({conn.objects.name})')
    except Exception as e:
        print(f'⚠️  Object store issue: {e}')

except ImportError as e:
    print(f'⚠️  Cloud SDK not installed: {e}')
    print('⚠️  Pipeline will run in LOCAL ONLY mode')
except Exception as e:
    print(f'⚠️  Cloud connection failed: {e}')
    print('⚠️  Pipeline will run in LOCAL ONLY mode')
" 2>/dev/null || print_warning "Could not check the cloud connection"

    echo ""
}

# Validate the environment variables the configured provider needs
check_cloud_env() {
    local provider
    provider=$(python3 -c "
from inferq.remote import resolve_provider
print(resolve_provider())
" 2>/dev/null)

    local missing_vars=()

    case "$provider" in
        aws)
            if [ -z "$AWS_REGION" ] && [ -z "$AWS_DEFAULT_REGION" ]; then
                missing_vars+=("AWS_REGION or AWS_DEFAULT_REGION")
            fi
            if [ -z "$AWS_S3_BUCKET" ]; then
                missing_vars+=("AWS_S3_BUCKET")
            fi
            if [ -z "$AWS_DYNAMODB_TABLE" ]; then
                missing_vars+=("AWS_DYNAMODB_TABLE")
            fi
            ;;
        azure|"")
            if [ -z "$AZURE_STORAGE_CONNECTION_STRING" ] && [ -z "$AZURE_STORAGE_ACCOUNT_NAME" ]; then
                missing_vars+=("AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME")
            fi
            ;;
    esac

    if [ ${#missing_vars[@]} -gt 0 ]; then
        print_warning "Missing ${provider:-cloud} environment variables:"
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
    check_cloud_env
    check_cloud_connection
fi
