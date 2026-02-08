#!/usr/bin/env python3
"""
Rerun InfiniQuantum Simulations from Parquet File

CLI tool to rerun infiniquantum simulations on circuits specified in a parquet file.
"""

import os
import sys
import argparse
import logging
import pandas as pd
from tqdm import tqdm
import multiprocessing

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.azure_connection import AzureConnection
from simulators.lib.infiniquantum import _execute_infiniquantum_simulation
import qiskit.qpy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_infiniquantum.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)


def load_circuit_from_disk(circuit_hash, circuits_base_dir):
    """
    Load a circuit from disk using its hash.

    Args:
        circuit_hash: The hash of the circuit (RowKey)
        circuits_base_dir: Base directory where circuits are stored

    Returns:
        QuantumCircuit object
    """
    from pathlib import Path

    circuits_base_dir = Path(circuits_base_dir)
    # Circuits are organized in subdirectories based on first 2 chars of hash
    subdir = circuit_hash[:2]
    circuit_path = circuits_base_dir / subdir / f"{circuit_hash}.qpy"

    if not circuit_path.exists():
        raise FileNotFoundError(f"Circuit file not found: {circuit_path}")

    with open(circuit_path, 'rb') as f:
        circuits = qiskit.qpy.load(f)
        qc = circuits[0] if isinstance(circuits, list) else circuits

    return qc


def process_circuit(circuit_hash, circuits_dir, azure_conn, timeout, n_runs):
    """
    Process a single circuit: load from disk, run infiniquantum simulation, update results.

    Args:
        circuit_hash: Hash of the circuit to process (RowKey)
        circuits_dir: Directory containing circuit files
        azure_conn: Azure connection instance
        timeout: Timeout in seconds for simulation
        n_runs: Number of runs to average for benchmarking

    Returns:
        tuple: (circuit_hash, success_bool, error_message_or_none)
    """
    try:
        # Get circuit entity from Azure Table
        table_client = azure_conn.get_circuits_table_client()
        try:
            entity = table_client.get_entity(
                partition_key="circuits",
                row_key=circuit_hash
            )
        except Exception as e:
            logger.error(f"Failed to fetch entity for hash {circuit_hash}: {e}")
            return (circuit_hash, False, f"Failed to fetch entity: {e}")

        # Load circuit from local disk
        try:
            circuit = load_circuit_from_disk(circuit_hash, circuits_dir)
        except Exception as e:
            logger.error(f"Failed to load circuit {circuit_hash} from disk: {e}")
            return (circuit_hash, False, f"Failed to load circuit: {e}")

        # Check which RDBMS methods are already present
        existing_methods = []
        all_rdbms_methods = ["umbra", "duckdb", "sqlite", "psql", "ducksql", "np-mps", "np-one-shot"]
        for method in all_rdbms_methods:
            # Normalize method name for entity key (replace - with _)
            entity_method = method.replace("-", "_")
            if entity.get(f"rdbms_{entity_method}_time_s") is not None:
                existing_methods.append(method)

        # If all methods already exist, skip simulation entirely
        if len(existing_methods) == len(all_rdbms_methods):
            logger.info(f"⊘ Skipping {circuit_hash} - all RDBMS methods already present")
            return (circuit_hash, True, "No updates needed")

        # Log which methods we're skipping
        if existing_methods:
            logger.info(f"Circuit {circuit_hash} - skipping existing methods: {', '.join(sorted(existing_methods))}")

        # Run infiniquantum simulation, omitting methods that already exist
        try:
            sim_result = _execute_infiniquantum_simulation(
                circuit,
                oom=existing_methods,
                n_runs=n_runs,
                timeout=timeout
            )

            if sim_result.get("success"):
                updates_made = []

                # Process benchmark results (umbra, duckdb, etc.)
                # Since we passed oom, these are only the methods we need to add
                if "benchmark_results" in sim_result:
                    for bench_method, bench_data in sim_result["benchmark_results"].items():
                        if isinstance(bench_data, dict):
                            # Normalize method name for entity key (replace - with _)
                            entity_method = bench_method.replace("-", "_")
                            memory_key = f"rdbms_{entity_method}_memory_mb"
                            time_key = f"rdbms_{entity_method}_time_s"

                            if "time_avg_s" in bench_data:
                                entity[time_key] = bench_data["time_avg_s"]
                                updates_made.append(f"{bench_method}_time")

                            if "memory_avg_mb" in bench_data:
                                entity[memory_key] = bench_data["memory_avg_mb"]
                                updates_made.append(f"{bench_method}_memory")

                # Extract SQL features (only if not already present)
                if "sql_query" in sim_result and entity.get("infinidata_quantum_sql_num_joins") is None:
                    from feature_extractors.sql_analyzer import SQLFeatureExtractor
                    try:
                        sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(sim_result["sql_query"])
                        for feat_name, count in sql_features.items():
                            sql_key = f"infinidata_quantum_sql_{feat_name}"
                            if entity.get(sql_key) is None:
                                entity[sql_key] = count
                                updates_made.append(f"sql_{feat_name}")

                        if entity.get("infinidata_quantum_sql_num_joins") is None:
                            entity["infinidata_quantum_sql_num_joins"] = len(join_edges)
                            updates_made.append("sql_num_joins")
                    except Exception as e:
                        logger.error(f"Failed to extract SQL features for {circuit_hash}: {e}")

                # Only update if we made changes
                if updates_made:
                    table_client.update_entity(
                        entity=entity,
                        mode="merge"
                    )
                    logger.info(f"✓ Updated {circuit_hash} - Added: {', '.join(updates_made)}")
                    return (circuit_hash, True, None)
                else:
                    logger.info(f"⊘ No updates for {circuit_hash} - simulation ran but no new data")
                    return (circuit_hash, True, "No updates needed")
            else:
                logger.warning(f"✗ Simulation failed for {circuit_hash}: {sim_result.get('error')}")
                return (circuit_hash, False, sim_result.get("error"))

        except Exception as e:
            logger.error(f"Failed to simulate circuit {circuit_hash}: {e}")
            return (circuit_hash, False, f"Simulation exception: {e}")

    except Exception as e:
        logger.error(f"Unexpected error processing {circuit_hash}: {e}")
        return (circuit_hash, False, f"Unexpected error: {e}")


def process_circuit_wrapper(args):
    """Wrapper for multiprocessing pool."""
    circuit_hash, circuits_dir, timeout, n_runs = args

    # Initialize components in worker process
    azure_conn = AzureConnection()

    return process_circuit(circuit_hash, circuits_dir, azure_conn, timeout, n_runs)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Rerun infiniquantum simulations from parquet file."
    )
    parser.add_argument(
        "--parquet-file", type=str,
        default="analysis/training_data/rdbms_training_data.parquet",
        help="Path to parquet file containing circuit hashes (RowKey column)."
    )
    parser.add_argument(
        "--circuits-dir", type=str, default=None,
        help="Directory containing circuit QPY files."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of circuits to process."
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Number of worker processes."
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip circuits that already have infiniquantum results."
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Timeout in seconds for each simulation."
    )
    parser.add_argument(
        "--n-runs", type=int, default=5,
        help="Number of runs to average for benchmarking."
    )

    args = parser.parse_args()

    # Get circuits directory
    circuits_dir = args.circuits_dir
    if circuits_dir is None:
        from config import PipelineConfig
        config = PipelineConfig()
        circuits_dir = str(config.circuits_dir)

    # Determine number of workers
    workers = args.workers
    if workers is None:
        workers = max(1, multiprocessing.cpu_count() - 1)

    timeout = args.timeout
    n_runs = args.n_runs

    print(f"Parquet file: {args.parquet_file}")
    print(f"Circuits directory: {circuits_dir}")
    print(f"Workers: {workers}")
    print(f"Timeout: {timeout}s")
    print(f"N runs: {n_runs}")
    print(f"Limit: {args.limit if args.limit else 'All'}")
    print(f"Skip existing: {args.skip_existing}")

    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return

    # Load parquet file
    try:
        df = pd.read_parquet(args.parquet_file)
        logger.info(f"Loaded {len(df)} rows from parquet file")
    except Exception as e:
        logger.error(f"Failed to load parquet file: {e}")
        return

    # Extract circuit hashes (RowKey)
    if 'RowKey' not in df.columns:
        logger.error("Parquet file does not contain 'RowKey' column")
        logger.info(f"Available columns: {df.columns.tolist()}")
        return

    circuit_hashes = df['RowKey'].unique().tolist()
    logger.info(f"Found {len(circuit_hashes)} unique circuit hashes (RowKey)")

    # Apply limit if specified
    if args.limit:
        circuit_hashes = circuit_hashes[:args.limit]
        logger.info(f"Limited to {len(circuit_hashes)} circuits")

    # Filter out circuits that already have infiniquantum results
    if args.skip_existing:
        logger.info("Filtering circuits that already have infiniquantum results...")
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client

        circuits_to_process = []
        for circuit_hash in tqdm(circuit_hashes, desc="Checking existing results"):
            try:
                entity = table_client.get_entity(
                    partition_key="circuits",
                    row_key=circuit_hash
                )
                # Check if any RDBMS method has already succeeded
                has_rdbms_results = any(
                    entity.get(f"rdbms_{method}_time_s") is not None
                    for method in ["umbra", "duckdb", "sqlite", "psql", "ducksql", "np_mps", "np_one_shot"]
                )
                if not has_rdbms_results:
                    circuits_to_process.append(circuit_hash)
            except Exception:
                # Circuit not found in table, add it
                circuits_to_process.append(circuit_hash)

        circuit_hashes = circuits_to_process
        logger.info("Filtered to %d circuits needing infiniquantum simulation", len(circuit_hashes))

    if not circuit_hashes:
        logger.info("No circuits to process")
        return

    # Process circuits
    logger.info(f"Starting infiniquantum simulation on {len(circuit_hashes)} circuits...")

    if workers == 1:
        # Single-threaded processing
        azure_conn = AzureConnection()

        results = []
        for circuit_hash in tqdm(circuit_hashes, desc="Processing circuits"):
            result = process_circuit(circuit_hash, circuits_dir, azure_conn, timeout, n_runs)
            results.append(result)
    else:
        # Multi-processing
        with multiprocessing.Pool(processes=workers) as pool:
            args_list = [(circuit_hash, circuits_dir, timeout, n_runs) for circuit_hash in circuit_hashes]
            results = list(tqdm(
                pool.imap(process_circuit_wrapper, args_list),
                total=len(circuit_hashes),
                desc="Processing circuits"
            ))

    # Summarize results
    successful = sum(1 for _, success, _ in results if success)
    failed = len(results) - successful
    no_updates_needed = sum(1 for _, success, error in results if success and error == "No updates needed")
    actually_updated = successful - no_updates_needed

    logger.info("\nProcessing complete!")
    logger.info("Total circuits processed: %d", len(results))
    logger.info("Successfully updated: %d", actually_updated)
    logger.info("Already complete (no updates needed): %d", no_updates_needed)
    logger.info("Failed: %d", failed)

    if failed > 0:
        logger.info("\nFailed circuits:")
        for circuit_hash, success, error in results:
            if not success:
                logger.info("  %s: %s", circuit_hash, error)


if __name__ == "__main__":
    main()
