"""
Quick test script to verify cloud connectivity before a bulk upload.

Run this before ``inferq upload`` to check that the configured provider's
credentials work and that both stores are reachable. Provider-neutral: it
exercises whatever backend the environment selects.
"""

import logging
import sys

from inferq.config import get_cloud_config
from inferq.remote import get_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_cloud_connection():
    """Test the configured object store and metadata store connections."""

    cloud_config = get_cloud_config()
    provider = cloud_config["provider"]

    print("=" * 80)
    print(f"Testing cloud connection (provider: {provider})")
    print("=" * 80)

    try:
        print("\n1. Initializing cloud connection...")
        conn = get_connection(config=cloud_config)
        print(f"   ✓ Connection object created for {conn.provider}")

        print("\n2. Testing object storage...")
        conn.objects.ping()
        print(f"   ✓ Connected to bucket/container: {conn.objects.name}")

        print("\n3. Testing metadata storage...")
        conn.metadata.ping()
        print(f"   ✓ Connected to table: {conn.metadata.name}")

        print("\n" + "=" * 80)
        print(f"✓ All {conn.provider} connections successful!")
        print("=" * 80)
        print("\nYou're ready to upload circuits using:")
        print("  uv run inferq upload --dry-run  # Test run")
        print("  uv run inferq upload            # Actual upload")
        print("=" * 80)

        return True

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ Cloud connection failed (provider: {provider})!")
        print("=" * 80)
        print(f"\nError: {e}")
        print("\nPlease check:")
        print("  1. Your .env file contains valid credentials for this provider")
        print("  2. INFERQ_CLOUD_PROVIDER selects the provider you meant")
        if provider == "aws":
            print("  3. AWS_REGION, AWS_S3_BUCKET and AWS_DYNAMODB_TABLE are set")
            print("  4. The default credential chain resolves (IAM role, SSO, or keys)")
            print("  5. The bucket and table exist and are reachable")
        else:
            print("  3. the provider's credentials are set (see .env.example)")
            print("  4. the configured bucket/container and table exist")
            print("  5. The storage account and container exist")
        print("  6. Your network connection is working")
        print("=" * 80)

        return False


if __name__ == "__main__":
    success = test_cloud_connection()
    sys.exit(0 if success else 1)
