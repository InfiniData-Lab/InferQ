#!/usr/bin/env python3
"""
Rerun circuits with umbra backend and update Azure Table Storage

This script reads circuits from the rdbms_training_data.parquet file,
runs them with the umbra backend, and updates Azure Table Storage.
"""

import os
import sys
import argparse
import logging
import pandas as pd
from pathlib import Path
from tqdm import tqdm
import pickle

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from qiskit import QuantumCircuit
from simulators.simulate import QuantumSimulator
from simulators.lib.infiniquantum import _execute_infiniquantum_simulation
from utils.azure_connection import AzureConnection
from utils.table_storage import update_circuit_metadata_in_table

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_umbra_to_azure.log"),
    ],
)
logger = logging.getLogger(__name__)

def load_circuit_from_hash(circuit_hash: str, circuits_base_dir: Path) -> QuantumCircuit:
    """
    Load a circuit from disk using its hash.

    Args:
        circuit_hash: The hash of the circuit (RowKey)
        circuits_base_dir: Base directory where circuits are stored

    Returns:
        QuantumCircuit object
    """
    # Circuits are organized in subdirectories based on first 2 chars of hash
    subdir = circuit_hash[:2]
    circuit_path = circuits_base_dir / subdir / f"{circuit_hash}.qpy"

    if not circuit_path.exists():
        raise FileNotFoundError(f"Circuit file not found: {circuit_path}")

    import qiskit.qpy
    with open(circuit_path, 'rb') as f:
        circuits = qiskit.qpy.load(f)
        qc = circuits[0] if isinstance(circuits, list) else circuits

    return qc

def run_umbra_simulation(circuit: QuantumCircuit, timeout: int, n_runs: int = 5) -> dict:
    """
    Run simulation with umbra backend only.

    Args:
        circuit: The quantum circuit to simulate
        timeout: Timeout in seconds
        n_runs: Number of runs to average

    Returns:
        Dictionary with simulation results
    """
    try:
        # Run InfiniQuantumSim with only umbra (omit all other backends)
        # Keep only umbra by omitting all other backends
        # Note: Backend names use hyphens, not underscores
        result = _execute_infiniquantum_simulation(
            circuit,
            oom=["psql", "sqlite", "ducksql", "eqc", "np-mps", "np-one-shot"],  # Omit everything except umbra
            n_runs=n_runs,
            timeout=timeout
        )
        return result
    except Exception as e:
        logger.error(f"Error running umbra simulation: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "method": "infiniquantum"
        }

def process_circuit(circuit_hash: str, circuits_dir: Path, azure_client,
                   timeout: int, n_runs: int) -> dict:
    """
    Process a single circuit: load, simulate with umbra, and update Azure.

    Args:
        circuit_hash: The circuit hash (RowKey)
        circuits_dir: Directory containing circuits
        azure_client: Azure Table Storage client
        timeout: Timeout in seconds
        n_runs: Number of runs to average

    Returns:
        Dictionary with processing results
    """
    try:
        # Load circuit
        circuit = load_circuit_from_hash(circuit_hash, circuits_dir)
        logger.debug(f"Loaded circuit {circuit_hash}: {circuit.num_qubits} qubits, depth {circuit.depth()}")

        # Run umbra simulation
        result = run_umbra_simulation(circuit, timeout, n_runs)

        # Prepare updates for Azure
        updates = {}
        success = False

        if result.get('success') and 'benchmark_results' in result:
            benchmark = result['benchmark_results']

            # Check if umbra results are available
            if 'umbra' in benchmark:
                umbra_stats = benchmark['umbra']
                updates['rdbms_umbra_memory_mb'] = umbra_stats.get('memory_avg_mb')
                updates['rdbms_umbra_time_s'] = umbra_stats.get('time_avg_s')
                success = True
                logger.info(f"✓ {circuit_hash}: umbra time={umbra_stats.get('time_avg_s'):.4f}s, mem={umbra_stats.get('memory_avg_mb'):.2f}MB")
            else:
                logger.warning(f"✗ {circuit_hash}: umbra not in benchmark results. Available: {list(benchmark.keys())}")
                updates['rdbms_umbra_error'] = f"umbra not in results. Got: {list(benchmark.keys())}"
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.warning(f"✗ {circuit_hash}: {error_msg}")
            updates['rdbms_umbra_error'] = error_msg

        # Update Azure if we have updates
        table_updated = False
        if updates:
            try:
                table_updated = update_circuit_metadata_in_table(
                    azure_client,
                    circuit_hash,
                    updates
                )
                if table_updated:
                    logger.debug(f"Azure updated for {circuit_hash}")
                else:
                    logger.warning(f"Failed to update Azure for {circuit_hash}")
            except Exception as e:
                logger.error(f"Azure update error for {circuit_hash}: {e}")

        return {
            'circuit_hash': circuit_hash,
            'success': success,
            'table_updated': table_updated,
            'updates': updates,
            'error': result.get('error') if not success else None
        }

    except FileNotFoundError as e:
        logger.error(f"Circuit {circuit_hash} not found: {e}")
        return {
            'circuit_hash': circuit_hash,
            'success': False,
            'table_updated': False,
            'updates': {},
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"Error processing circuit {circuit_hash}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            'circuit_hash': circuit_hash,
            'success': False,
            'table_updated': False,
            'updates': {},
            'error': str(e)
        }

def main():
    parser = argparse.ArgumentParser(
        description="Rerun circuits with umbra backend and update Azure Table Storage"
    )
    parser.add_argument(
        "--parquet-file",
        type=str,
        default="analysis/training_data/rdbms_training_data.parquet",
        help="Path to the parquet file containing circuit data"
    )
    parser.add_argument(
        "--circuits-dir",
        type=str,
        default=None,
        help="Directory containing circuit files (default: auto-detect)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=162,
        help="Number of circuits to process (default: 162)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout per circuit in seconds (default: 30)"
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start index for processing circuits (default: 0)"
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=5,
        help="Number of runs to average (default: 5)"
    )

    args = parser.parse_args()

    # Determine circuits directory
    if args.circuits_dir:
        circuits_dir = Path(args.circuits_dir)
    else:
        # Try common locations
        possible_dirs = [
            Path("data/downloaded_circuits_from_metadata"),
            Path("downloaded_circuits_public"),
            Path("circuits"),
        ]
        circuits_dir = None
        for pdir in possible_dirs:
            if pdir.exists():
                circuits_dir = pdir
                logger.info(f"Found circuits directory: {circuits_dir}")
                break

        if circuits_dir is None:
            logger.error("Could not find circuits directory. Please specify with --circuits-dir")
            return

    # Connect to Azure
    logger.info("Connecting to Azure Table Storage...")
    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        logger.info("✓ Connected to Azure Table Storage")
    except Exception as e:
        logger.error(f"Failed to connect to Azure: {e}")
        return

    # Load parquet file
    logger.info(f"Loading parquet file: {args.parquet_file}")
    df = pd.read_parquet(args.parquet_file)
    logger.info(f"Loaded {len(df)} circuits from parquet file")

    # Select subset
    subset = df.iloc[args.start_index:args.start_index + args.limit]
    logger.info(f"Processing {len(subset)} circuits (indices {args.start_index} to {args.start_index + len(subset) - 1})")

    # Process circuits
    logger.info("=" * 60)
    logger.info(f"Starting umbra simulations with timeout={args.timeout}s, n_runs={args.n_runs}")
    logger.info("=" * 60)

    results = []
    for _, row in tqdm(subset.iterrows(), total=len(subset), desc="Processing circuits"):
        circuit_hash = row['RowKey']
        result = process_circuit(
            circuit_hash,
            circuits_dir,
            table_client,
            args.timeout,
            args.n_runs
        )
        results.append(result)

    # Print summary
    total = len(results)
    successful = sum(1 for r in results if r['success'])
    failed = total - successful
    table_updated_count = sum(1 for r in results if r['table_updated'])

    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total circuits processed: {total}")
    logger.info(f"Successful simulations: {successful} ({successful/total*100:.1f}%)")
    logger.info(f"Failed simulations: {failed} ({failed/total*100:.1f}%)")
    logger.info(f"Azure Table updated: {table_updated_count} ({table_updated_count/total*100:.1f}%)")
    logger.info("=" * 60)

    # Print failed circuits
    if failed > 0:
        logger.info("\nFailed circuits:")
        for r in results:
            if not r['success']:
                logger.info(f"  - {r['circuit_hash']}: {r['error']}")

if __name__ == "__main__":
    main()
