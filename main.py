#!/usr/bin/env python3
"""Canonical InferQ pipeline entry point.

The default mode runs the production multiprocessing pipeline. The legacy
single-circuit path is kept as `python main.py single` because environment
tests import `run_extraction_pipeline` directly.
"""

from __future__ import annotations

import argparse
import cProfile
import logging
import pstats
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from config import (
    config,
    get_azure_config,
    get_circuit_config,
    get_simulation_config,
    get_storage_config,
)

if TYPE_CHECKING:
    from generators.circuit_merger import CircuitMerger
    from simulators.simulate import QuantumSimulator
    from utils.azure_connection import AzureConnection


logger = logging.getLogger(__name__)


def configure_logging(*, log_file: str | None = None) -> None:
    """Configure concise process-wide logging once."""
    logging_config = config.LOGGING
    level = getattr(logging, logging_config["level"].upper(), logging.INFO)
    formatter = logging.Formatter(logging_config["format"])

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    noisy_loggers = [
        "qiskit",
        "qiskit.passmanager",
        "qiskit.compiler",
        "qiskit.transpiler",
        "qiskit_aer",
        "azure.core",
        "azure.storage",
        "azure.data.tables",
        "azure.storage.blob",
        "azure.core.pipeline.policies.http_logging_policy",
        "rustworkx",
        "rx",
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    np.set_printoptions(suppress=True, threshold=0)


def run_extraction_pipeline(
    circuitMerger: CircuitMerger,
    quantumSimulator: QuantumSimulator,
    azure_conn: AzureConnection | None = None,
    circuit=None,
) -> None:
    """Run one generate/extract/simulate/store pipeline iteration."""
    from feature_extractors.extractors import extract_features
    from utils.save_utils import (
        save_circuit_locally,
        save_circuit_metadata_to_table,
        upload_circuit_blob,
    )

    circuit_config = get_circuit_config()
    storage_config = get_storage_config()

    logger.info("STEP 1: Circuit Generation")
    logger.info("-" * 30)
    if circuit is None:
        try:
            circuit = circuitMerger.generate_hierarchical_circuit(
                stopping_probability=circuit_config["stopping_probability"],
                max_generators=circuit_config["max_generators"],
            )
            logger.info(
                "Generated circuit: %s qubits, depth %s, size %s",
                circuit.num_qubits,
                circuit.depth(),
                circuit.size(),
            )
        except Exception as exc:
            logger.error("Circuit generation failed: %s", exc)
            raise
    else:
        logger.info(
            "Using provided circuit: %s qubits, depth %s, size %s",
            circuit.num_qubits,
            circuit.depth(),
            circuit.size(),
        )

    logger.info("STEP 2: Feature Extraction")
    logger.info("-" * 30)
    try:
        extracted_features = extract_features(circuit=circuit)
        logger.info("Feature extraction completed: %s features", len(extracted_features))
    except Exception as exc:
        logger.error("Feature extraction failed: %s", exc)
        raise

    logger.info("STEP 3: Quantum Simulation")
    logger.info("-" * 30)
    try:
        simulation_results = quantumSimulator.simulate_all_methods(circuit)
        successful_sims = sum(
            1 for result in simulation_results.values() if result.get("success", False)
        )
        logger.info(
            "Simulation completed: %s/%s methods successful",
            successful_sims,
            len(simulation_results),
        )
    except Exception as exc:
        logger.error("Simulation failed: %s", exc)
        raise

    logger.info("STEP 4: Processing Simulation Data")
    logger.info("-" * 30)
    sql_query, sql_query_mode = None, None
    try:
        from simulators import (
            process_simulation_data_for_features,
            sql_artifact_from_results,
        )

        combined_features = process_simulation_data_for_features(
            simulation_results,
            extracted_features,
        )
        sql_query, sql_query_mode = sql_artifact_from_results(simulation_results)
    except Exception as exc:
        logger.error("Simulation data processing failed: %s", exc)
        combined_features = extracted_features

    logger.info("STEP 5: Local Storage")
    logger.info("-" * 30)
    try:
        storage_path = Path(storage_config["local_circuits_dir"])
        storage_path.mkdir(parents=True, exist_ok=True)
        qpy_hash, features, written = save_circuit_locally(
            circuit,
            combined_features,
            storage_path,
            sql_query=sql_query,
            sql_query_mode=sql_query_mode,
        )
        if written:
            logger.info("Circuit saved locally with hash: %s", qpy_hash)
            logger.info(
                "Serialization method: %s",
                features.get("serialization_method", "unknown"),
            )
        else:
            logger.info("Circuit %s already exists locally", qpy_hash)
    except Exception as exc:
        logger.error("Local storage failed: %s", exc)
        raise

    if written and azure_conn:
        logger.info("STEP 6: Cloud Storage")
        logger.info("-" * 30)
        try:
            container_client = azure_conn.get_container_client()
            serialization_method = features.get("serialization_method", "qpy")
            blob_path = upload_circuit_blob(
                container_client,
                circuit,
                qpy_hash,
                serialization_method,
            )
            features["blob_path"] = (
                blob_path.split("circuits/")[1] if "circuits/" in blob_path else blob_path
            )

            table_client = azure_conn.get_circuits_table_client()
            if save_circuit_metadata_to_table(table_client, features):
                logger.info("Circuit metadata saved to Azure Table Storage")
            else:
                logger.error("Failed to save metadata to Azure Table Storage")
        except Exception as exc:
            logger.error("Cloud storage failed: %s", exc)
            logger.info("Circuit is still available locally")
    elif written:
        logger.info("Azure connection not provided; skipping cloud storage")
    elif azure_conn:
        logger.info("Circuit already exists; skipping cloud storage")

    logger.info("Pipeline completed successfully")


def run_single_pipeline() -> None:
    """Run the legacy single-circuit pipeline."""
    from generators.circuit_merger import CircuitMerger
    from generators.lib.generator import BaseParams
    from simulators.simulate import QuantumSimulator
    from utils.azure_connection import AzureConnection

    circuit_config = get_circuit_config()
    simulation_config = get_simulation_config()
    azure_config = get_azure_config()

    seed = circuit_config["seed"]
    logger.info("Starting single-circuit InferQ pipeline")
    logger.info("Using random seed: %s", seed)

    azure_conn = None
    if azure_config["enabled"]:
        try:
            azure_conn = AzureConnection()
            logger.warning("Azure connection established for remote storage")
        except Exception as exc:
            logger.warning("Azure connection failed: %s", exc)
            logger.warning("Remote storage disabled; local-only mode")
    else:
        logger.warning("Azure disabled in configuration; local-only mode")

    base_params = BaseParams(
        max_qubits=circuit_config["max_qubits"],
        min_qubits=circuit_config["min_qubits"],
        max_depth=circuit_config["max_depth"],
        min_depth=circuit_config["min_depth"],
        seed=seed,
        measure=circuit_config["measure"],
    )
    circuit_merger = CircuitMerger(base_params=base_params)
    quantum_simulator = QuantumSimulator(
        seed=simulation_config["seed"],
        shots=simulation_config["shots"],
        timeout_seconds=simulation_config["timeout_seconds"],
        infiniquantum_config=simulation_config.get("infiniquantum"),
    )
    run_extraction_pipeline(circuit_merger, quantum_simulator, azure_conn)


def run_interactive_pipeline(generate_only: bool = False) -> None:
    """Run an interactive circuit-composition session."""
    from generators.circuit_merger import CircuitMerger
    from generators.interactive_composer import (
        generate_interactive_circuit,
        prompt_yes_no,
    )
    from generators.lib.generator import BaseParams
    from simulators.simulate import QuantumSimulator
    from utils.azure_connection import AzureConnection

    circuit_config = get_circuit_config()
    simulation_config = get_simulation_config()
    azure_config = get_azure_config()

    base_params = BaseParams(
        max_qubits=circuit_config["max_qubits"],
        min_qubits=circuit_config["min_qubits"],
        max_depth=circuit_config["max_depth"],
        min_depth=circuit_config["min_depth"],
        seed=circuit_config["seed"],
        measure=circuit_config["measure"],
    )
    circuit_merger = CircuitMerger(base_params=base_params)
    circuit = generate_interactive_circuit(
        circuit_merger,
        stopping_probability=circuit_config["stopping_probability"],
        max_generators=circuit_config["max_generators"],
    )

    logger.info(
        "Interactive circuit ready: %s qubits, depth %s, size %s",
        circuit.num_qubits,
        circuit.depth(),
        circuit.size(),
    )
    print(
        f"\nGenerated circuit: {circuit.num_qubits} qubits, "
        f"depth {circuit.depth()}, size {circuit.size()}"
    )

    if generate_only:
        return

    if not prompt_yes_no("Run feature extraction, simulation, and storage now?", default=True):
        return

    azure_conn = None
    if azure_config["enabled"]:
        try:
            azure_conn = AzureConnection()
            logger.warning("Azure connection established for remote storage")
        except Exception as exc:
            logger.warning("Azure connection failed: %s", exc)
            logger.warning("Remote storage disabled; local-only mode")
    else:
        logger.warning("Azure disabled in configuration; local-only mode")

    quantum_simulator = QuantumSimulator(
        seed=simulation_config["seed"],
        shots=simulation_config["shots"],
        timeout_seconds=simulation_config["timeout_seconds"],
        infiniquantum_config=simulation_config.get("infiniquantum"),
    )
    run_extraction_pipeline(circuit_merger, quantum_simulator, azure_conn, circuit=circuit)


def run_parallel_from_args(args: argparse.Namespace) -> dict:
    """Run the production parallel pipeline from parsed CLI args."""
    from pipeline.manager import run_parallel_pipeline

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            return run_parallel_pipeline(
                num_workers=args.workers,
                max_iterations=args.iterations,
                batch_size=args.batch_size,
                azure_upload_interval=args.azure_interval,
                batch_timeout_seconds=args.batch_timeout,
            )
        finally:
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats("cumulative")
            stats.print_stats(20)

    return run_parallel_pipeline(
        num_workers=args.workers,
        max_iterations=args.iterations,
        batch_size=args.batch_size,
        azure_upload_interval=args.azure_interval,
        batch_timeout_seconds=args.batch_timeout,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="InferQ circuit generation pipeline")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["parallel", "single", "interactive"],
        default="parallel",
        help="Pipeline mode. Defaults to parallel.",
    )
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers")
    parser.add_argument("--iterations", type=int, default=None, help="Maximum batch iterations")
    parser.add_argument("--batch-size", type=int, default=None, help="Circuits per batch")
    parser.add_argument(
        "--azure-interval",
        type=int,
        default=None,
        help="Upload to Azure after this many buffered circuits",
    )
    parser.add_argument(
        "--batch-timeout",
        type=int,
        default=None,
        help="Timeout for each parallel batch in seconds",
    )
    parser.add_argument("--profile", action="store_true", help="Enable cProfile output")
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="In interactive mode, stop after building the circuit",
    )
    parser.add_argument("--log-file", default="pipeline.log", help="Log file path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(log_file=args.log_file)

    if args.mode == "single":
        run_single_pipeline()
    elif args.mode == "interactive":
        run_interactive_pipeline(generate_only=args.generate_only)
    else:
        run_parallel_from_args(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
