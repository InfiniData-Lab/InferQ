"""
List and verify circuits in cloud storage.

This script helps you:
- View circuits recorded in the cloud metadata store
- Check how many circuits are uploaded
- Verify specific circuits exist
- Compare local vs remote storage

Whichever provider is configured (Azure Table, DynamoDB, ...) is used; nothing
here is provider-specific.
"""

import logging
from pathlib import Path

from inferq.config import get_storage_config
from inferq.remote import get_circuit_metadata, get_connection, list_circuits

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def list_remote_circuits(limit=100):
    """List circuits recorded in the cloud metadata store."""
    print("=" * 80)
    print("Circuits in the cloud metadata store")
    print("=" * 80)

    try:
        conn = get_connection()
        circuits = list_circuits(conn.metadata, limit=limit)

        if not circuits:
            print("\nNo circuits found in the cloud metadata store.")
            print("Have you uploaded any circuits yet?")
            return

        print(f"\nFound {len(circuits)} circuits (showing up to {limit}):\n")

        # Print table header
        print(f"{'Hash (first 16)':<20} {'Qubits':<8} {'Depth':<8} {'Size':<8} {'Uploaded'}")
        print("-" * 80)

        # Print circuits
        for circuit in circuits:
            hash_short = circuit['qpy_sha256'][:16] if circuit.get('qpy_sha256') else 'N/A'
            qubits = circuit.get('num_qubits', 'N/A')
            depth = circuit.get('circuit_depth', 'N/A')
            size = circuit.get('circuit_size', 'N/A')

            # Format timestamp nicely
            timestamp = circuit.get('timestamp')
            if hasattr(timestamp, 'strftime'):
                timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M')
            else:
                timestamp_str = str(timestamp) if timestamp else 'N/A'

            print(f"{hash_short:<20} {qubits:<8} {depth:<8} {size:<8} {timestamp_str}")

        print("=" * 80)

    except Exception as e:
        print(f"\n✗ Error listing circuits: {e}")
        logger.error(f"Failed to list circuits: {e}")


def count_local_circuits():
    """Count circuits in the local storage directory."""
    storage_config = get_storage_config()
    circuits_dir = Path(storage_config['local_circuits_dir'])

    if not circuits_dir.exists():
        return 0

    count = 0
    for item in circuits_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            qpy_file = item / "circuit.qpy"
            meta_file = item / "meta.json"
            if qpy_file.exists() and meta_file.exists():
                count += 1

    return count


def compare_storage():
    """Compare local and remote storage."""
    print("=" * 80)
    print("Storage Comparison")
    print("=" * 80)

    # Count local circuits
    local_count = count_local_circuits()
    print(f"\nLocal circuits: {local_count}")

    # Count remote circuits
    try:
        conn = get_connection()

        # Get all circuits (may be slow for large catalogues)
        remote_circuits = list_circuits(conn.metadata, limit=10000)
        remote_count = len(remote_circuits)

        print(f"Remote circuits ({conn.provider}): {remote_count}")

        # Compare
        if local_count > remote_count:
            diff = local_count - remote_count
            print(f"\n⚠ You have {diff} more circuits locally than in the cloud")
            print("  Consider running: uv run inferq upload")
        elif remote_count > local_count:
            diff = remote_count - local_count
            print(f"\n✓ The cloud has {diff} more circuits than local storage")
        else:
            print("\n✓ Local and remote storage are in sync")

        print("=" * 80)

    except Exception as e:
        print(f"\n✗ Error accessing cloud storage: {e}")
        logger.error(f"Failed to count remote circuits: {e}")


def check_circuit_exists(circuit_hash: str):
    """Check whether a specific circuit exists in the cloud metadata store."""
    print("=" * 80)
    print(f"Checking circuit: {circuit_hash}")
    print("=" * 80)

    try:
        conn = get_connection()
        metadata = get_circuit_metadata(conn.metadata, circuit_hash)

        if metadata:
            print("\n✓ Circuit found in the cloud metadata store")
            print("\nMetadata:")
            for key, value in sorted(metadata.items()):
                print(f"  {key}: {value}")
        else:
            print("\n✗ Circuit not found in the cloud metadata store")

        print("=" * 80)

    except Exception as e:
        print(f"\n✗ Error checking circuit: {e}")
        logger.error(f"Failed to check circuit: {e}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="List and verify circuits in cloud storage"
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List circuits in the cloud metadata store'
    )
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare local and remote storage'
    )
    parser.add_argument(
        '--check',
        type=str,
        metavar='HASH',
        help='Check if a specific circuit exists remotely (provide circuit hash)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of circuits to list (default: 100)'
    )

    args = parser.parse_args()

    # If no arguments provided, enter interactive mode
    if not any([args.list, args.compare, args.check]):
        print("\nChange default action to interactive mode:")
        print("1. List circuits in the cloud metadata store")
        print("2. Compare local vs remote storage")
        print("3. Check for specific circuit hash")

        try:
            choice = input("\nSelect an operation (1-3) [default: 1]: ").strip()

            if choice == '2':
                compare_storage()
            elif choice == '3':
                circuit_hash = input("Enter circuit hash: ").strip()
                if circuit_hash:
                    check_circuit_exists(circuit_hash)
                else:
                    print("No hash provided.")
            else:
                # Default to 1 (List)
                limit_str = input(f"Enter limit [default: {args.limit}]: ").strip()
                limit = int(limit_str) if limit_str.isdigit() else args.limit
                list_remote_circuits(limit=limit)

        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
        return

    if args.list:
        list_remote_circuits(limit=args.limit)

    if args.compare:
        compare_storage()

    if args.check:
        check_circuit_exists(args.check)


if __name__ == "__main__":
    main()
