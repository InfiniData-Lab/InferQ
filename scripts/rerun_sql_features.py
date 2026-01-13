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
from qiskit import transpile

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.azure_connection import AzureConnection
from utils.table_storage import update_circuit_metadata_in_table
from feature_extractors.sql_analyzer import SQLFeatureExtractor
from config import PipelineConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rerun_sql_features.log"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)

MEMORY_THRESHOLD_PERCENT = 90
MEMORY_CHECK_INTERVAL = 5

# Check if InfiniQuantumSim is available
try:
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit, Gate as IQSGate
    from InfiniQuantumSim.utils import INDICES
    INFINI_QUANTUM_AVAILABLE = True
except ImportError:
    INFINI_QUANTUM_AVAILABLE = False
    logger.warning("InfiniQuantumSim not available. Script will not work without it.")


def extract_sql_features_from_circuit(qc, circuit_hash):
    """
    Extract SQL features from a quantum circuit using InfiniQuantumSim.
    
    Args:
        qc: Qiskit QuantumCircuit
        circuit_hash: Hash identifier for the circuit
        
    Returns:
        dict with success flag, updates dict, and error message if any
    """
    try:
        if not INFINI_QUANTUM_AVAILABLE:
            return {
                "hash": circuit_hash,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": "InfiniQuantumSim not installed"
            }
        
        start_time = time.time()
        
        # Transpile to ensure we only have 1 and 2 qubit gates
        transpiled_qc = transpile(qc, basis_gates=['u', 'cx', 'id', 'rz', 'sx', 'x'], optimization_level=2)
        
        num_qubits = transpiled_qc.num_qubits
        
        # Check if circuit is too large for InfiniQuantumSim
        estimated_indices = num_qubits + 3 * len(transpiled_qc.data)
        if estimated_indices >= len(INDICES):
            logger.warning(f"Skipping {circuit_hash}: Circuit too large (indices limit): {estimated_indices} > {len(INDICES)}")
            return {
                "hash": circuit_hash,
                "success": False,
                "skipped": True,
                "updates": {},
                "error": f"Circuit too large for InfiniQuantumSim (indices limit)"
            }
        
        # Create IQS circuit
        iqs_qc = IQSQuantumCircuit(num_qubits=num_qubits)
        
        # Add gates to IQS circuit
        for instruction in transpiled_qc.data:
            op = instruction.operation
            qubits = [transpiled_qc.find_bit(q).index for q in instruction.qubits]
            
            if op.name == 'barrier':
                continue
            if op.name == 'measure':
                continue
                
            matrix = op.to_matrix()
            
            # Reshape matrix for IQS Gate
            if len(qubits) == 1:
                tensor = matrix
            elif len(qubits) == 2:
                tensor = matrix.reshape(2, 2, 2, 2)
            else:
                raise ValueError(f"Unsupported operation {op.name} on {len(qubits)} qubits")
            
            # Create unique name for parameterized gates
            if len(op.params) > 0:
                gate_name = f"{op.name}_{id(op)}"
            else:
                gate_name = op.name
            
            gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
            iqs_qc.add_gate(gate)
        
        # Generate SQL query
        sql_query = iqs_qc.to_query()
        
        # Extract SQL features
        sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(sql_query)
        
        # Prepare updates dict
        updates = {}
        for feat_name, count in sql_features.items():
            updates[f"infinidata_quantum_sql_{feat_name}"] = count
        updates["infinidata_quantum_sql_num_joins"] = len(join_edges)
        
        execution_time = time.time() - start_time
        logger.debug(f"Extracted SQL features for {circuit_hash} in {execution_time:.3f}s")
        
        return {
            "hash": circuit_hash,
            "success": True,
            "skipped": False,
            "updates": updates,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Failed to extract SQL features for {circuit_hash}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            "hash": circuit_hash,
            "success": False,
            "skipped": False,
            "updates": {},
            "error": str(e)
        }


def process_circuit_file(file_path):
    """
    Helper function to process a single circuit file.
    """
    try:
        # Load circuit
        with open(file_path, "rb") as f:
            circuits = qiskit.qpy.load(f)
            qc = circuits[0] if isinstance(circuits, list) else circuits

        # Extract hash from filename
        filename = os.path.basename(file_path)
        circuit_hash = os.path.splitext(filename)[0]

        logger.info(f"Extracting SQL features for circuit {circuit_hash}")
        
        result = extract_sql_features_from_circuit(qc, circuit_hash)
        result["file_path"] = file_path
        
        return result

    except Exception as e:
        logger.error(f"Error processing file {file_path}: {e}")
        return {
            "hash": None,
            "success": False,
            "skipped": False,
            "updates": {},
            "error": str(e),
            "file_path": file_path,
        }


def process_folder(folder_path, processed_hashes, checkpoints_dir):
    """
    Worker function to process all circuits in a folder.
    Updates Azure Table and writes checkpoints immediately upon success.
    """
    logger.info(f"Processing folder: {folder_path}")
    results = []
    
    try:
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
                    time.sleep(MEMORY_CHECK_INTERVAL)

                circuit_hash = os.path.splitext(filename)[0]

                # Skip if already processed
                if circuit_hash in processed_hashes:
                    continue

                file_path = os.path.join(folder_path, filename)
                result = process_circuit_file(file_path)

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
                    # If skipped (e.g. too large), write to checkpoint so we don't retry
                    logger.info(f"Skipping {circuit_hash}: {result.get('error')}")
                    checkpoint_f.write(f"{circuit_hash}\n")
                    checkpoint_f.flush()

                results.append(result)

    except Exception as e:
        logger.error(f"Error processing folder {folder_path}: {e}")

    return results


def rerun_sql_features_parallel(
    circuits_dir,
    limit=None,
    verbose=False,
    checkpoints_dir="checkpoints_sql_features",
    num_workers=None,
):
    """
    Extract SQL features from circuits in parallel and update Azure Table.
    """
    if not INFINI_QUANTUM_AVAILABLE:
        logger.error("InfiniQuantumSim is required but not installed. Please install it first.")
        return
    
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
                    process_folder, folder_path, folder_processed, checkpoints_dir
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

    logger.info(f"SQL feature extraction complete. Total circuits updated: {total_updated}")


if __name__ == "__main__":
    config = PipelineConfig()

    parser = argparse.ArgumentParser(
        description="Extract SQL features from circuits in parallel and update Azure Table."
    )
    parser.add_argument(
        "--circuits-dir", type=str, default=None, help="Directory containing circuits."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of circuits to process."
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output.")
    parser.add_argument(
        "--checkpoints-dir",
        type=str,
        default="checkpoints_sql_features",
        help="Directory to store processed circuit hashes per folder.",
    )
    parser.add_argument(
        "--workers", type=int, default=None, help="Number of worker processes."
    )

    args = parser.parse_args()

    circuits_dir = args.circuits_dir
    limit = args.limit
    verbose = args.verbose
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
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")

    rerun_sql_features_parallel(
        circuits_dir, limit, verbose, checkpoints_dir, workers
    )
