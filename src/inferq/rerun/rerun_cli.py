#!/usr/bin/env python3
"""
Rerun Pipeline CLI

Single driver for the three rerun pipelines. ``--mode`` selects which one runs:

* ``simulations`` — rerun quantum simulations on existing circuits;
* ``sql`` — extract SQL features without running simulations;
* ``dynamic`` — recompute entropy and sparsity from saved statevector data.

Each pipeline keeps its own flags, prompts, log file and checkpoint defaults;
``--mode`` must therefore come before ``--help`` to see a pipeline's flags. The
``rerun_simulations``, ``rerun_sql_features`` and ``rerun_dynamic_features``
modules call ``main()`` with their mode fixed, so their historical flag sets —
including ``--mode {auto,all,rdbms}`` for simulations — are unchanged. On this
driver that simulation selector is spelled ``--sim-mode``, leaving ``--mode``
for the pipeline choice.
"""

import argparse
import logging
import multiprocessing
import os
import sys

from inferq import paths
from inferq.config import PipelineConfig
from inferq.remote import get_connection

from .checkpoint_manager import CheckpointManager
from .circuit_processor import (
    INFINI_QUANTUM_AVAILABLE,
    DynamicFeatureProcessor,
    SimulationProcessor,
    SQLFeatureProcessor,
)
from .folder_processor import FolderProcessor
from .orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

MODES = ("simulations", "sql", "dynamic")

SIMULATION_MODES = ["auto", "all", "rdbms"]

_DESCRIPTIONS = {
    "simulations": "Rerun simulations in parallel and update the cloud metadata store.",
    "sql": "Extract SQL features from circuits in parallel and update the cloud metadata store.",
    "dynamic": (
        "Rerun dynamic feature extraction (entropy, sparsity) from saved "
        "statevector simulations."
    ),
}

_LOG_FILES = {
    "simulations": "rerun_simulations.log",
    "sql": "rerun_sql_features.log",
    "dynamic": "rerun_dynamic_features.log",
}

_CHECKPOINT_DEFAULTS = {
    "simulations": None,
    "sql": "checkpoints_sql_features",
    "dynamic": None,
}


def configure_logging(mode: str) -> None:
    """Send pipeline logs to stderr and to the mode's own log file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(paths.log_file(_LOG_FILES[mode])),
        ],
    )
    logging.getLogger("qiskit.passmanager.base_tasks").setLevel(logging.WARNING)
    logging.getLogger("qiskit.compiler.transpiler").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Worker entry points
#
# These run in a spawned process, so they must stay importable at module level
# and rebuild every component they need from plain arguments.
# ---------------------------------------------------------------------------

def process_simulation_folder(args):
    """
    Wrapper function for processing a folder with simulations.
    This runs in a worker process.

    Args:
        args: Tuple of (folder_path, processed_hashes, mode, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth)

    Returns:
        List of results
    """
    folder_path, processed_hashes, mode, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth = args
    try:
        # Initialize components in worker process
        from inferq.simulation.simulate import QuantumSimulator
        sim_config = PipelineConfig.SIMULATION
        simulator = QuantumSimulator(
            timeout_seconds=sim_config.get("timeout_seconds", 60),
            infiniquantum_config=sim_config.get("infiniquantum")
        )

        metadata_store = get_connection().metadata

        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = SimulationProcessor(
            simulator,
            min_qubits=min_qubits,
            max_qubits=max_qubits,
            min_depth=min_depth,
            max_depth=max_depth
        )

        folder_processor = FolderProcessor(
            circuit_processor,
            metadata_store,
            checkpoint_manager
        )
        folder_processor.mode = mode  # Add mode for simulation

        return folder_processor.process_folder(folder_path, processed_hashes)

    except Exception as e:
        logger.error(f"Failed to process folder {folder_path}: {e}")
        return []


def process_sql_folder(args):
    """
    Wrapper function for processing a folder with SQL feature extraction.
    This runs in a worker process.

    Args:
        args: Tuple of (folder_path, processed_hashes, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth)

    Returns:
        List of results
    """
    folder_path, processed_hashes, checkpoints_dir, min_qubits, max_qubits, min_depth, max_depth = args
    try:
        # Initialize components in worker process
        metadata_store = get_connection().metadata

        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = SQLFeatureProcessor(
            min_qubits=min_qubits,
            max_qubits=max_qubits,
            min_depth=min_depth,
            max_depth=max_depth
        )

        folder_processor = FolderProcessor(
            circuit_processor,
            metadata_store,
            checkpoint_manager
        )

        return folder_processor.process_folder(folder_path, processed_hashes)

    except Exception as e:
        logger.error(f"Failed to process folder {folder_path}: {e}")
        return []


def process_dynamic_folder(args):
    """
    Wrapper function for processing a folder with dynamic feature extraction.
    This runs in a worker process.

    Args:
        args: Tuple of (folder_path, processed_hashes, checkpoints_dir, max_qubits, max_depth)

    Returns:
        List of results
    """
    folder_path, processed_hashes, checkpoints_dir, max_qubits, max_depth = args
    try:
        # Initialize components in worker process
        from inferq.simulation.simulate import QuantumSimulator
        sim_config = PipelineConfig.SIMULATION
        simulator = QuantumSimulator(
            timeout_seconds=sim_config.get("timeout_seconds", 60),
            infiniquantum_config=sim_config.get("infiniquantum")
        )

        metadata_store = get_connection().metadata

        checkpoint_manager = CheckpointManager(checkpoints_dir)
        circuit_processor = DynamicFeatureProcessor(simulator, max_qubits, max_depth)

        folder_processor = FolderProcessor(
            circuit_processor,
            metadata_store,
            checkpoint_manager
        )

        return folder_processor.process_folder(folder_path, processed_hashes)

    except Exception as e:
        logger.error(f"Failed to process folder {folder_path}: {e}")
        return []


_WORKERS = {
    "simulations": process_simulation_folder,
    "sql": process_sql_folder,
    "dynamic": process_dynamic_folder,
}


# ---------------------------------------------------------------------------
# Interactive prompts
#
# Every flag may be left off the command line, in which case its value is read
# from stdin. A closed stdin always falls back to the flag's own default.
# ---------------------------------------------------------------------------

def prompt_circuits_dir(value, default_dir: str) -> str:
    """Return the circuits directory, prompting when the flag was omitted."""
    if value is not None:
        return value
    try:
        user_input = input(
            f"Enter circuits directory [default: {default_dir}]: "
        ).strip()
    except EOFError:
        return default_dir
    return user_input if user_input else default_dir


def prompt_optional_int(value, prompt: str, invalid_message: str):
    """Return an optional integer, prompting when the flag was omitted.

    Args:
        value: Value already supplied on the command line, or None.
        prompt: Text shown when stdin has to be read.
        invalid_message: Printed when the answer is not an integer.

    Returns:
        The integer, or None for "no value" — an empty answer, a closed stdin,
        or an unparseable answer.
    """
    if value is not None:
        return value
    try:
        user_input = input(prompt).strip()
    except EOFError:
        return None
    if not user_input:
        return None
    try:
        return int(user_input)
    except ValueError:
        print(invalid_message)
        return None


def prompt_workers(value):
    """Return the worker count, prompting when the flag was omitted.

    Any failure to read an answer — a closed stdin, an unparseable count, or an
    interrupt at the prompt — yields None, leaving the orchestrator to pick its
    own default.
    """
    if value is not None:
        return value
    try:
        default_workers = max(1, multiprocessing.cpu_count() - 1)
        user_input = input(
            f"Enter number of workers [default: {default_workers}]: "
        ).strip()
        return int(user_input) if user_input else default_workers
    except BaseException:
        return None


def prompt_simulation_mode(value) -> str:
    """Return the simulation mode, prompting when the flag was omitted."""
    if value is not None:
        return value
    try:
        user_input = input(
            "Enter simulation mode (auto/all/rdbms) [default: auto]: "
        ).strip().lower()
        return user_input if user_input in SIMULATION_MODES else "auto"
    except EOFError:
        return "auto"


def prompt_size_limits(args) -> tuple:
    """Return the (min_qubits, max_qubits, min_depth, max_depth) filters."""
    min_qubits = prompt_optional_int(
        args.min_qubits,
        "Enter minimum qubit count (or press Enter for no limit): ",
        "Invalid number. No minimum qubit limit will be applied.",
    )
    max_qubits = prompt_optional_int(
        args.max_qubits,
        "Enter maximum qubit count (or press Enter for no limit): ",
        "Invalid number. No maximum qubit limit will be applied.",
    )
    min_depth = prompt_optional_int(
        args.min_depth,
        "Enter minimum circuit depth (or press Enter for no limit): ",
        "Invalid number. No minimum depth limit will be applied.",
    )
    max_depth = prompt_optional_int(
        args.max_depth,
        "Enter maximum circuit depth (or press Enter for no limit): ",
        "Invalid number. No maximum depth limit will be applied.",
    )
    return min_qubits, max_qubits, min_depth, max_depth


def print_size_limits(min_qubits, max_qubits, min_depth, max_depth) -> None:
    """Echo the circuit size filters back to the operator."""
    print(f"Min Qubits: {min_qubits if min_qubits is not None else 'No limit'}")
    print(f"Max Qubits: {max_qubits if max_qubits is not None else 'No limit'}")
    print(f"Min Depth: {min_depth if min_depth is not None else 'No limit'}")
    print(f"Max Depth: {max_depth if max_depth is not None else 'No limit'}")


def connect_metadata_store():
    """Return the circuit metadata store, or None when the connection fails."""
    try:
        conn = get_connection()
        logger.info("Connected to the %s metadata store", conn.provider)
        return conn.metadata
    except Exception as e:
        logger.error(f"Failed to connect to cloud storage: {e}")
        return None


def build_orchestrator(circuits_dir: str, checkpoints_dir: str, metadata_store):
    """Build the orchestrator that fans folders out across worker processes."""
    checkpoint_manager = CheckpointManager(checkpoints_dir)
    return PipelineOrchestrator(circuits_dir, checkpoint_manager, metadata_store)


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def run_simulations(args) -> None:
    """Rerun quantum simulations across the circuit store."""
    config = PipelineConfig()

    circuits_dir = prompt_circuits_dir(args.circuits_dir, str(config.circuits_dir))
    limit = prompt_optional_int(
        args.limit,
        "Enter number of circuits to process (or press Enter for all): ",
        "Invalid number. Defaulting to all.",
    )
    mode = prompt_simulation_mode(args.sim_mode)

    checkpoints_dir = args.checkpoints_dir
    if checkpoints_dir is None:
        checkpoints_dir = "checkpoints_rdbms" if mode == "rdbms" else "checkpoints"

    workers = prompt_workers(args.workers)
    min_qubits, max_qubits, min_depth, max_depth = prompt_size_limits(args)
    verbose = args.verbose

    # Display configuration
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Mode: {mode}")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    print_size_limits(min_qubits, max_qubits, min_depth, max_depth)

    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return

    metadata_store = connect_metadata_store()
    if metadata_store is None:
        return

    orchestrator = build_orchestrator(circuits_dir, checkpoints_dir, metadata_store)

    # Run pipeline with mode and checkpoints_dir passed through
    total_updated = orchestrator.run_parallel(
        process_simulation_folder,
        mode=mode,
        checkpoints_dir=checkpoints_dir,
        min_qubits=min_qubits,
        max_qubits=max_qubits,
        min_depth=min_depth,
        max_depth=max_depth,
        num_workers=workers,
        limit=limit,
        verbose=verbose
    )

    logger.info(f"Rerun complete. Total circuits updated: {total_updated}")


def run_sql_features(args) -> None:
    """Extract SQL features from the circuit store without simulating."""
    config = PipelineConfig()

    circuits_dir = prompt_circuits_dir(args.circuits_dir, str(config.circuits_dir))
    limit = prompt_optional_int(
        args.limit,
        "Enter number of circuits to process (or press Enter for all): ",
        "Invalid number. Defaulting to all.",
    )
    workers = prompt_workers(args.workers)
    min_qubits, max_qubits, min_depth, max_depth = prompt_size_limits(args)

    checkpoints_dir = args.checkpoints_dir
    verbose = args.verbose

    # Display configuration
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    print_size_limits(min_qubits, max_qubits, min_depth, max_depth)

    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return

    # Check if InfiniQuantumSim is available
    if not INFINI_QUANTUM_AVAILABLE:
        logger.error("InfiniQuantumSim is required but not installed. Please install it first.")
        return

    metadata_store = connect_metadata_store()
    if metadata_store is None:
        return

    orchestrator = build_orchestrator(circuits_dir, checkpoints_dir, metadata_store)

    # Run pipeline with checkpoints_dir passed through
    total_updated = orchestrator.run_parallel(
        process_sql_folder,
        checkpoints_dir=checkpoints_dir,
        min_qubits=min_qubits,
        max_qubits=max_qubits,
        min_depth=min_depth,
        max_depth=max_depth,
        num_workers=workers,
        limit=limit,
        verbose=verbose
    )

    logger.info(f"SQL feature extraction complete. Total circuits updated: {total_updated}")


def run_dynamic_features(args) -> None:
    """Recompute entropy and sparsity from saved statevector simulations."""
    import signal

    # Set up signal handler for clean Ctrl+C exit
    def signal_handler(sig, frame):
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    config = PipelineConfig()

    circuits_dir = prompt_circuits_dir(args.circuits_dir, str(config.circuits_dir))
    limit = prompt_optional_int(
        args.limit,
        "Enter number of circuits to process (or press Enter for all): ",
        "Invalid number. Defaulting to all.",
    )

    checkpoints_dir = args.checkpoints_dir
    if checkpoints_dir is None:
        checkpoints_dir = "checkpoints_dynamic_features"

    workers = prompt_workers(args.workers)
    verbose = args.verbose

    max_qubits = prompt_optional_int(
        args.max_qubits,
        "Enter maximum qubit count (or press Enter for no limit): ",
        "Invalid number. No qubit limit will be applied.",
    )
    max_depth = prompt_optional_int(
        args.max_depth,
        "Enter maximum circuit depth (or press Enter for no limit): ",
        "Invalid number. No depth limit will be applied.",
    )

    # Display configuration
    print("\n" + "="*60)
    print("DYNAMIC FEATURES EXTRACTION CONFIGURATION")
    print("="*60)
    print(f"Circuits directory: {circuits_dir}")
    print(f"Limit: {limit if limit is not None else 'All'}")
    print("Features: Shannon Entropy, Von Neumann Entropy, Sparsity")
    print("Source: statevector_saved simulation data")
    print(f"Workers: {workers}")
    print(f"Checkpoints Directory: {checkpoints_dir}")
    print(f"Max Qubits: {max_qubits if max_qubits is not None else 'No limit'}")
    print(f"Max Depth: {max_depth if max_depth is not None else 'No limit'}")
    print(f"Verbose: {verbose}")
    print("="*60 + "\n")

    # Confirmation prompt
    if not args.skip_confirmation:
        try:
            confirm = input("Proceed with dynamic feature extraction? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Aborted.")
                return
        except EOFError:
            print("No input received. Proceeding...")

    # Validate circuits directory
    if not os.path.exists(circuits_dir):
        logger.error(f"Circuits directory not found: {circuits_dir}")
        return

    metadata_store = connect_metadata_store()
    if metadata_store is None:
        return

    orchestrator = build_orchestrator(circuits_dir, checkpoints_dir, metadata_store)

    # Run pipeline with dynamic feature extraction parameters
    try:
        total_updated = orchestrator.run_parallel(
            process_dynamic_folder,
            checkpoints_dir=checkpoints_dir,
            max_qubits=max_qubits,
            max_depth=max_depth,
            num_workers=workers,
            limit=limit,
            verbose=verbose
        )

        logger.info(f"Dynamic feature extraction complete. Total circuits processed: {total_updated}")
        print(f"\n{'='*60}")
        print(f"COMPLETED: {total_updated} circuits processed (updated/skipped)")
        print(f"{'='*60}\n")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(0)


_PIPELINES = {
    "simulations": run_simulations,
    "sql": run_sql_features,
    "dynamic": run_dynamic_features,
}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_parser(mode: str, selectable: bool) -> argparse.ArgumentParser:
    """Build the argument parser for one pipeline.

    Args:
        mode: Pipeline whose flags the parser should accept.
        selectable: True when the caller reaches this driver directly, in which
            case ``--mode`` names the pipeline and the simulation mode moves to
            ``--sim-mode``. False for the fixed-mode entry points, whose flag
            sets must not change.
    """
    parser = argparse.ArgumentParser(description=_DESCRIPTIONS[mode])
    if selectable:
        parser.add_argument(
            "--mode", type=str, choices=list(MODES), required=True,
            help="Rerun pipeline to drive."
        )
    parser.add_argument(
        "--circuits-dir", type=str, default=None,
        help="Directory containing circuits."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of circuits to process."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose output."
    )
    if mode == "simulations":
        parser.add_argument(
            "--sim-mode" if selectable else "--mode", dest="sim_mode",
            type=str, choices=SIMULATION_MODES, default=None,
            help="Simulation mode: 'auto', 'all', or 'rdbms'."
        )
    parser.add_argument(
        "--checkpoints-dir", type=str, default=_CHECKPOINT_DEFAULTS[mode],
        help="Directory to store processed circuit hashes per folder."
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Number of worker processes."
    )
    if mode == "dynamic":
        parser.add_argument(
            "--skip-confirmation", action="store_true",
            help="Skip confirmation prompt before starting."
        )
        parser.add_argument(
            "--max-qubits", type=int, default=None,
            help="Maximum qubit count to process (circuits with more qubits will be skipped)."
        )
        parser.add_argument(
            "--max-depth", type=int, default=None,
            help="Maximum circuit depth to process (circuits with greater depth will be skipped)."
        )
    else:
        parser.add_argument(
            "--min-qubits", type=int, default=None,
            help="Minimum number of qubits."
        )
        parser.add_argument(
            "--max-qubits", type=int, default=None,
            help="Maximum number of qubits."
        )
        parser.add_argument(
            "--min-depth", type=int, default=None,
            help="Minimum circuit depth."
        )
        parser.add_argument(
            "--max-depth", type=int, default=None,
            help="Maximum circuit depth."
        )
    return parser


def pipeline_from_argv(argv) -> str:
    """Read the ``--mode`` pipeline selector without consuming other flags."""
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--mode", type=str, choices=list(MODES))
    known, _ = selector.parse_known_args(argv)
    if known.mode is None:
        raise SystemExit(
            "--mode is required; choose one of "
            f"{', '.join(MODES)} (put it before --help to see that "
            "pipeline's flags)"
        )
    return known.mode


def main(mode: str = None, argv=None) -> None:
    """Main entry point.

    Args:
        mode: Pipeline to run. The fixed-mode entry points pass their own; when
            None, ``--mode`` on the command line selects it.
        argv: Argument list to parse, defaulting to ``sys.argv[1:]``.
    """
    selectable = mode is None
    if selectable:
        mode = pipeline_from_argv(argv)
    args = build_parser(mode, selectable).parse_args(argv)
    configure_logging(mode)
    _PIPELINES[mode](args)


if __name__ == "__main__":
    main()
