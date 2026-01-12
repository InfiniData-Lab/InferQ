import os
import sys

import argparse
import logging
import multiprocessing
import psutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import qiskit.qpy

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.azure_connection import AzureConnection
from utils.table_storage import update_circuit_metadata_in_table
from utils.checkpoint_writer import AsyncCheckpointWriter
from simulators.simulate import QuantumSimulator, SimulationMethod
from config import PipelineConfig
from feature_extractors.sql_analyzer import SQLFeatureExtractor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_simulations_parallel.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)

MEMORY_THRESHOLD_PERCENT = 90
MEMORY_CHECK_INTERVAL = 5


def process_circuit_file(file_path, mode, simulator):
    """
    Helper function to process a single circuit using an existing simulator instance.
    """
    try:
        # Load circuit
        with open(file_path, "rb") as f:
            circuits = qiskit.qpy.load(f)
            qc = circuits[0] if isinstance(circuits, list) else circuits

        # Extract hash from filename
        filename = os.path.basename(file_path)
        circuit_hash = os.path.splitext(filename)[0]

        updates = {}
        success_flag = False
        skipped_flag = False
        error_msg = None
        logger.info(f"Simulating circuit {circuit_hash} in mode {mode}")
        if mode == "auto":
            result = simulator.simulate_auto(qc)
            if result["success"]:
                success_flag = True
                data = result.get("data", {})
                actual_method = data.get("actual_method", result["method"])
                updates = {
                    "automatic_method": actual_method,
                    "automatic_execution_time": result["execution_time"],
                    "automatic_memory_usage": result.get("memory_usage"),
                    "automatic_transpiled_depth": result.get(
                        "transpiled_circuit_depth"
                    ),
                    "automatic_transpiled_size": result.get("transpiled_circuit_size"),
                    "automatic_transpiled_qubits": result.get("transpiled_num_qubits"),
                }
            elif result.get("skipped"):
                skipped_flag = True
                error_msg = result.get("error")
            else:
                error_msg = result.get("error")

        elif mode == "all":
            results = simulator.simulate_all_methods(qc)
            if any(r.get("success", False) for r in results.values()):
                success_flag = True
                for method_name, result in results.items():
                    if result.get("success", False):
                        prefix = method_name
                        updates[f"{prefix}_execution_time"] = result.get(
                            "execution_time"
                        )
                        updates[f"{prefix}_memory_usage"] = result.get("memory_usage")
                        updates[f"{prefix}_transpiled_depth"] = result.get(
                            "transpiled_circuit_depth"
                        )
                        updates[f"{prefix}_transpiled_size"] = result.get(
                            "transpiled_circuit_size"
                        )
                        updates[f"{prefix}_gate_counts"] = result.get(
                            "transpiled_gate_counts"
                        )

                        data = result.get("data", {})
                        if "entropy" in data:
                            updates[f"{prefix}_entropy"] = data["entropy"]
                        # if "sparsity" in data:
                        #     updates[f"{prefix}_sparsity"] = data["sparsity"]
                        if result.get("method") == "automatic":
                            updates["automatic_method"] = data["actual_method"]
                        
                        # Handle InfiniQuantumSim benchmark results and SQL analysis if present in 'all' mode
                        if method_name == "infiniquantum":
                            if "benchmark_results" in result:
                                for bench_method, bench_data in result["benchmark_results"].items():
                                    if isinstance(bench_data, dict):
                                        if "memory_avg_mb" in bench_data:
                                            updates[f"rdbms_{bench_method}_memory_mb"] = bench_data["memory_avg_mb"]
                                        if "time_avg_s" in bench_data:
                                            updates[f"rdbms_{bench_method}_time_s"] = bench_data["time_avg_s"]
                            
                            # Extract SQL Features
                            if "sql_query" in result:
                                try:
                                    sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(result["sql_query"])
                                    for feat_name, count in sql_features.items():
                                        updates[f"infinidata_quantum_sql_{feat_name}"] = count
                                    updates[f"infinidata_quantum_sql_num_joins"] = len(join_edges)
                                except Exception as e:
                                    logger.error(f"Failed to extract SQL features: {e}")

            elif any(r.get("skipped", False) for r in results.values()):
                skipped_flag = True
                error_msg = "Simulations skipped"
            else:
                error_msg = "All simulations failed"

        elif mode == "rdbms":
            # Run only InfiniQuantumSim
            # Configuration is handled by the simulator instance via PipelineConfig
            result = simulator._run_simulation(
                qc, 
                SimulationMethod.INFINI_QUANTUM
            )
            
            if result.get("success", False):
                success_flag = True
                updates["rdbms_execution_time"] = result.get("execution_time")
                
                if "benchmark_results" in result:
                    for bench_method, bench_data in result["benchmark_results"].items():
                        if isinstance(bench_data, dict):
                            if "memory_avg_mb" in bench_data:
                                updates[f"rdbms_{bench_method}_memory_mb"] = bench_data["memory_avg_mb"]
                            if "time_avg_s" in bench_data:
                                updates[f"rdbms_{bench_method}_time_s"] = bench_data["time_avg_s"]
                
                # Extract SQL Features for rdbms mode
                if "sql_query" in result:
                    try:
                        sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(result["sql_query"])
                        for feat_name, count in sql_features.items():
                            updates[f"infinidata_quantum_sql_{feat_name}"] = count
                        updates[f"infinidata_quantum_sql_num_joins"] = len(join_edges)
                    except Exception as e:
                        logger.error(f"Failed to extract SQL features: {e}")
            elif result.get("skipped"):
                skipped_flag = True
                error_msg = result.get("error")
            else:
                error_msg = result.get("error")

        return {
            "hash": circuit_hash,
            "success": success_flag,
            "skipped": skipped_flag,
            "updates": updates,
            "error": error_msg,
            "file_path": file_path,
        }

    except Exception as e:
        return {
            "hash": None,
            "success": False,
            "updates": {},
            "error": str(e),
            "file_path": file_path,
        }


def process_folder(folder_path, mode, processed_hashes, checkpoints_dir):
    """
    Worker function to process all circuits in a folder.
    Updates Azure Table and writes checkpoints immediately upon success.
    """
    logger.info(f"Processing folder: {folder_path}")
    results = []
    try:
        # Initialize Simulator once per folder/worker
        sim_config = PipelineConfig.SIMULATION
        simulator = QuantumSimulator(
            timeout_seconds=sim_config.get("timeout_seconds", 60),
            infiniquantum_config=sim_config.get("infiniquantum")
        )

        # Initialize Azure Connection once per folder/worker
        try:
            azure_conn = AzureConnection()
            table_client = azure_conn.circuits_table_client
        except Exception as e:
            logger.error(f"Failed to connect to Azure in worker: {e}")
            return []

        # Prepare checkpoint file
        folder_name = os.path.basename(folder_path)
        checkpoint_path = os.path.join(checkpoints_dir, f"{folder_name}.txt")

        # List files in the folder
        try:
            files = [f for f in os.listdir(folder_path) if f.endswith(".qpy")]
        except FileNotFoundError:
            return []

        # Open checkpoint file for appending
        with open(checkpoint_path, "a") as checkpoint_f:
            for filename in files:
                # Memory Hold-off
                while psutil.virtual_memory().percent > MEMORY_THRESHOLD_PERCENT:
                    # Sleep to let memory clear up
                    time.sleep(MEMORY_CHECK_INTERVAL)

                circuit_hash = os.path.splitext(filename)[0]

                # Skip if already processed
                if circuit_hash in processed_hashes:
                    continue

                file_path = os.path.join(folder_path, filename)
                result = process_circuit_file(file_path, mode, simulator)

                # If successful, update table and write checkpoint immediately
                if result["success"]:
                    try:
                        table_success = update_circuit_metadata_in_table(
                            table_client, circuit_hash, result["updates"]
                        )
                        result["table_updated"] = table_success
                        if table_success:
                            checkpoint_f.write(f"{circuit_hash}\n")
                            checkpoint_f.flush()
                    except Exception as e:
                        logger.error(f"Azure update error for {circuit_hash}: {e}")
                        result["table_updated"] = False
                        result["error"] = f"Azure update failed: {e}"
                elif result.get("skipped"):
                    # If skipped (e.g. timeout or too complex), write to checkpoint so we don't retry
                    logger.info(f"Skipping {circuit_hash}: {result.get('error')}")
                    checkpoint_f.write(f"{circuit_hash}\n")
                    checkpoint_f.flush()

                results.append(result)

    except Exception as e:
        logger.error(f"Error processing folder {folder_path}: {e}")

    return results


def rerun_simulations_parallel(
    circuits_dir,
    limit=None,
    verbose=False,
    mode="auto",
    checkpoints_dir="checkpoints",
    num_workers=None,
):
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return

    # Initialize Azure connection (Main Process)
    try:
        azure_conn = AzureConnection()
        table_client = azure_conn.circuits_table_client
        logger.info("Connected to Azure Table Storage.")
    except Exception as e:
        logger.error(f"Failed to connect to Azure: {e}")
        return

    # Load checkpoints from directory
    processed_hashes = set()
    if checkpoints_dir:
        if not os.path.exists(checkpoints_dir):
            try:
                os.makedirs(checkpoints_dir)
                logger.info(f"Created checkpoints directory: {checkpoints_dir}")
            except Exception as e:
                logger.error(f"Failed to create checkpoints directory: {e}")
                return
        else:
            # Load existing checkpoints
            try:
                for filename in os.listdir(checkpoints_dir):
                    if filename.endswith(".txt"):
                        filepath = os.path.join(checkpoints_dir, filename)
                        with open(filepath, "r") as f:
                            file_hashes = set(
                                line.strip() for line in f if line.strip()
                            )
                            processed_hashes.update(file_hashes)
                logger.info(
                    f"Loaded checkpoints. {len(processed_hashes)} circuits already processed."
                )
            except Exception as e:
                logger.error(f"Failed to load checkpoints: {e}")

    # Bucket processed hashes by folder prefix (first 2 chars)
    processed_buckets = {}
    if processed_hashes:
        logger.info("Bucketing processed hashes...")
        for h in processed_hashes:
            prefix = h[:2]
            if prefix not in processed_buckets:
                processed_buckets[prefix] = set()
            processed_buckets[prefix].add(h)

    # Identify folders to process
    try:
        subdirs = [
            d
            for d in os.listdir(circuits_dir)
            if os.path.isdir(os.path.join(circuits_dir, d))
        ]
        subdirs.sort()
    except Exception as e:
        logger.error(f"Error listing directories in {circuits_dir}: {e}")
        return

    if not subdirs:
        logger.warning(f"No subdirectories found in {circuits_dir}")
        return

    logger.info(f"Found {len(subdirs)} folders to process.")

    # Determine workers
    if num_workers is None:
        num_workers = max(1, multiprocessing.cpu_count() - 1)

    logger.info(f"Starting parallel execution with {num_workers} workers.")

    total_updated = 0

    try:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit tasks per folder
            future_to_folder = {}
            for folder_name in subdirs:
                folder_path = os.path.join(circuits_dir, folder_name)
                # Get relevant processed hashes for this folder
                folder_processed = processed_buckets.get(folder_name, set())

                future = executor.submit(
                    process_folder, folder_path, mode, folder_processed, checkpoints_dir
                )
                future_to_folder[future] = folder_name

            # Process results as folders complete
            for future in tqdm(
                as_completed(future_to_folder),
                total=len(subdirs),
                desc="Processing Folders",
            ):
                folder_name = future_to_folder[future]
                try:
                    folder_results = future.result()
                    if verbose:
                        logger.info(
                            f"Folder {folder_name} returned {len(folder_results)} results."
                        )

                    # Process results for this folder (just for stats now)
                    for result in folder_results:
                        if limit and total_updated >= limit:
                            break

                        if result.get("table_updated", False):
                            total_updated += 1
                            if verbose:
                                logger.info(f"Success {result['hash']}")
                        elif result.get("error") and verbose:
                            logger.warning(
                                f"Failed {result['hash']}: {result['error']}"
                            )

                    if limit and total_updated >= limit:
                        logger.info(f"Limit of {limit} reached. Stopping.")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                except Exception as e:
                    logger.error(f"Error processing folder {folder_name}: {e}")

    except KeyboardInterrupt:
        logger.info("Interrupted by user. Stopping...")
        executor.shutdown(wait=False, cancel_futures=True)

    logger.info(f"Rerun complete. Total circuits updated: {total_updated}")


if __name__ == "__main__":
    config = PipelineConfig()

    parser = argparse.ArgumentParser(
        description="Rerun simulations in parallel (folder-based) and update Azure Table."
    )
    parser.add_argument(
        "--circuits-dir", type=str, default=None, help="Directory containing circuits."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of circuits to process."
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "all", "rdbms"],
        default=None,
        help="Simulation mode: 'auto', 'all', or 'rdbms'.",
    )
    parser.add_argument(
        "--checkpoints-dir",
        type=str,
        default=None,
        help="Directory to store processed circuit hashes per folder.",
    )
    parser.add_argument(
        "--workers", type=int, default=None, help="Number of worker processes."
    )

    args = parser.parse_args()

    circuits_dir = args.circuits_dir
    limit = args.limit
    verbose = args.verbose
    mode = args.mode
    checkpoints_dir = args.checkpoints_dir
    workers = args.workers

    # Interactive prompts if arguments are not provided
    if circuits_dir is None:
        default_dir = str(config.circuits_dir)
        try:
            user_input = input(
                f"Enter circuits directory [default: {default_dir}]: "
            ).strip()
            circuits_dir = user_input if user_input else default_dir
        except EOFError:
            circuits_dir = default_dir

    if limit is None:
        try:
            user_input = input(
                "Enter number of circuits to process (or press Enter for all): "
            ).strip()
            if user_input:
                try:
                    limit = int(user_input)
                except ValueError:
                    print("Invalid number. Defaulting to all.")
                    limit = None
            else:
                limit = None
        except EOFError:
            limit = None

    if mode is None:
        try:
            user_input = (
                input("Enter simulation mode (auto/all/rdbms) [default: auto]: ")
                .strip()
                .lower()
            )
            if user_input in ["auto", "all", "rdbms"]:
                mode = user_input
            else:
                mode = "auto"
        except EOFError:
            mode = "auto"

    if checkpoints_dir is None:
        if mode == "rdbms":
            checkpoints_dir = "checkpoints_rdbms"
        else:
            checkpoints_dir = "checkpoints"

    if workers is None:
        try:
            default_workers = max(1, multiprocessing.cpu_count() - 1)
            user_input = input(
                f"Enter number of workers [default: {default_workers}]: "
            ).strip()
            if user_input:
                workers = int(user_input)
            else:
                workers = default_workers
        except:
            workers = None

    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Mode: {mode}")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")

    rerun_simulations_parallel(
        circuits_dir, limit, verbose, mode, checkpoints_dir, workers
    )
