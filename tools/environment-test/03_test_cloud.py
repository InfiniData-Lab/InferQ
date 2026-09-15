#!/usr/bin/env python3
"""
Test 3: Cloud Connectivity Verification

Tests whichever cloud provider the environment selects (Azure Blob + Table, or
S3 + DynamoDB). Everything below goes through the provider-neutral interfaces in
``inferq.remote``, so this test does not need to know which cloud it is talking
to -- only that the configured one answers.
"""

import json
import os
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not available, environment variables must be set manually")
    load_dotenv = None

#: Packages each provider needs, so a missing SDK is reported as such rather
#: than as a connection failure.
PROVIDER_PACKAGES = {
    "azure": [
        ("azure.storage.blob", "Azure Blob Storage"),
        ("azure.data.tables", "Azure Table Storage"),
        ("azure.core", "Azure Core Libraries"),
    ],
    "aws": [
        ("boto3", "AWS SDK"),
        ("botocore", "AWS SDK core"),
    ],
}

#: Variables each provider reads. The first entry of a tuple is the preferred
#: spelling; any one of them satisfies the requirement.
PROVIDER_VARIABLES = {
    "azure": [
        ("AZURE_STORAGE_ACCOUNT", "AZURE_STORAGE_ACCOUNT_NAME"),
        ("AZURE_STORAGE_ACCOUNT_KEY", "AZURE_STORAGE_SAS_TOKEN",
         "AZURE_STORAGE_CONNECTION_STRING", "AZURE_CONTAINER_SAS_URL"),
    ],
    "aws": [
        ("AWS_REGION", "AWS_DEFAULT_REGION"),
        ("AWS_S3_BUCKET", "CLOUD_BUCKET"),
        ("AWS_DYNAMODB_TABLE", "CLOUD_TABLE"),
    ],
}


def detect_provider():
    """Name the configured provider, or None when inferq is not importable."""
    print("🧭 Detecting the configured cloud provider...")
    try:
        from inferq.remote import resolve_provider
    except ImportError as e:
        print(f"   ❌ Cannot import inferq.remote: {e}")
        print("   Make sure you're running from the project root directory")
        return None

    try:
        provider = resolve_provider()
    except Exception as e:
        print(f"   ❌ No usable provider configured: {e}")
        return None

    print(f"   ✅ Provider: {provider}")
    return provider


def test_packages(provider):
    """Check that the selected provider's SDK is installed."""
    print(f"\n📦 Testing {provider} package imports...")

    all_good = True
    for package, description in PROVIDER_PACKAGES.get(provider, []):
        try:
            __import__(package)
            print(f"   ✅ {package:20} - {description}")
        except ImportError as e:
            print(f"   ❌ {package:20} - {description} (Error: {e})")
            all_good = False

    return all_good


def test_environment_variables(provider):
    """Check that the selected provider's required variables are set.

    AWS deliberately tolerates missing keys: the default credential chain (an
    instance profile, SSO, or a shared profile) is the preferred way to
    authenticate, so only the names of the bucket, table and region are
    genuinely required.
    """
    print(f"\n🔑 Testing {provider} environment variables...")

    all_set = True
    for names in PROVIDER_VARIABLES.get(provider, []):
        found = next((name for name in names if os.getenv(name)), None)
        if found:
            print(f"   ✅ {found} is set")
        else:
            print(f"   ⚠️  None of {' / '.join(names)} is set")
            all_set = False

    if provider == "aws" and not os.getenv("AWS_ACCESS_KEY_ID"):
        print("   ℹ️  No explicit keys; the default credential chain will be used")

    bucket = os.getenv("CLOUD_BUCKET") or os.getenv("AZURE_CONTAINER") \
        or os.getenv("AWS_S3_BUCKET") or "circuits"
    table = os.getenv("CLOUD_TABLE") or os.getenv("AZURE_TABLE") \
        or os.getenv("AWS_DYNAMODB_TABLE") or "circuits"
    print(f"   Bucket/container name: {bucket}")
    print(f"   Table name: {table}")

    return all_set


def test_connection():
    """Build a connection and reach both stores."""
    print("\n🌐 Testing the cloud connection...")

    from inferq.remote import get_connection

    try:
        conn = get_connection()
        print(f"   ✅ {conn.provider} connection object created")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        return None, False, False

    try:
        conn.metadata.ping()
        print(f"   ✅ Metadata store accessible ({conn.metadata.name})")
        metadata_ok = True
    except Exception as e:
        print(f"   ⚠️  Metadata store access issue: {e}")
        metadata_ok = False

    try:
        conn.objects.ping()
        print(f"   ✅ Object store accessible ({conn.objects.name})")
        objects_ok = True
    except Exception as e:
        print(f"   ⚠️  Object store access issue: {e}")
        objects_ok = False

    return conn, metadata_ok, objects_ok


def test_write_permissions(conn):
    """Round-trip one throwaway record and one throwaway object."""
    print("\n✍️  Testing write permissions...")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        key = f"test_{stamp}"
        conn.metadata.put_record(
            "test",
            key,
            {"TestData": "Environment test", "WrittenAt": datetime.now().isoformat()},
        )
        print("   ✅ Metadata write test successful")
        try:
            conn.metadata.delete_record("test", key)
            print("   ✅ Metadata cleanup successful")
        except Exception:
            print("   ⚠️  Metadata cleanup failed (record may remain)")
        metadata_write_ok = True
    except Exception as e:
        print(f"   ❌ Metadata write test failed: {e}")
        metadata_write_ok = False

    try:
        object_key = f"test/environment_test_{stamp}.json"
        payload = json.dumps(
            {"test": "environment_verification", "timestamp": datetime.now().isoformat()}
        ).encode()
        conn.objects.put_object(object_key, payload, content_type="application/json")
        print("   ✅ Object write test successful")
        try:
            conn.objects.delete_object(object_key)
            print("   ✅ Object cleanup successful")
        except Exception:
            print("   ⚠️  Object cleanup failed (object may remain)")
        object_write_ok = True
    except Exception as e:
        print(f"   ❌ Object write test failed: {e}")
        object_write_ok = False

    return metadata_write_ok and object_write_ok


def main():
    """Run every cloud connectivity test against the configured provider."""
    print("=" * 60)
    print("☁️  CLOUD CONNECTIVITY TEST")
    print("=" * 60)

    provider = detect_provider()
    if provider is None:
        return 1

    imports_ok = test_packages(provider)
    env_vars_ok = test_environment_variables(provider)

    if not imports_ok:
        print(f"\n❌ {provider} packages not available - skipping connection tests")
        print(f"   Install them with: uv sync --extra {provider}")
        return 1

    if not env_vars_ok:
        print(f"\n⚠️  {provider} credentials not configured")
        print("   See .env.example for the variables this provider reads")
        print("   Pipeline will run in LOCAL-ONLY mode")
        connection_ok = False
        write_ok = False
    else:
        conn, metadata_ok, objects_ok = test_connection()
        connection_ok = bool(conn) and metadata_ok and objects_ok
        write_ok = test_write_permissions(conn) if connection_ok else False

    # Summary
    print("\n" + "=" * 60)
    print("📊 CLOUD TEST SUMMARY")
    print("=" * 60)

    tests = [
        ("Package Imports", imports_ok),
        ("Environment Variables", env_vars_ok),
        ("Connection", connection_ok),
        ("Write Permissions", write_ok),
    ]

    passed = 0
    for test_name, result in tests:
        if result:
            status = "✅ PASS"
            passed += 1
        elif test_name in ("Environment Variables", "Connection", "Write Permissions") \
                and not env_vars_ok:
            status = "⚠️  SKIP"
        else:
            status = "❌ FAIL"

        print(f"{status:8} {test_name}")

    print(f"\nPassed: {passed}/{len(tests)} tests")

    if connection_ok and write_ok:
        print(f"🎉 {provider} storage is fully functional!")
        return 0
    if env_vars_ok:
        print(f"⚠️  {provider} configured but has connection issues")
        return 1
    print(f"ℹ️  {provider} not configured - will run in local-only mode")
    return 0


if __name__ == "__main__":
    exit(main())
