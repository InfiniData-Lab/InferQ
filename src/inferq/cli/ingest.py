#!/usr/bin/env python3
"""Ingest benchmark-suite circuits into InferQ's storage + metadata.

Standalone script. Reuses — but does NOT modify — the existing pipeline
primitives:

    extract_features                 (inferq.features.extractors)
    QuantumSimulator.simulate_all    (inferq.simulation.simulate)
    process_simulation_data_for...   (inferq.simulation.processor)
    save_circuit_locally             (inferq.storage.local_storage)

For each loaded `BenchmarkCircuit` we:
  1. Skip if it exceeds `max_circuit_size` (mirrors pipeline/worker.py).
  2. Skip if a circuit with the same QPY hash already exists locally.
  3. Run `extract_features` and stuff `source` and `benchmark_name` into
     the resulting dict.
  4. Run `simulate_all_methods` and merge simulation metrics in.
  5. Persist to `circuits/<hash>/{circuit.qpy, meta.json}` via
     `save_circuit_locally` — which already spreads `**features` into
     `meta.json`, so the `source` and `benchmark_name` fields land in
     metadata for free, and `inferq.transfer.consolidate_metadata` will
     surface them in the parquet shards on its next run.

Run examples:
    # Dry-run: enumerate first 5 circuits per suite, no simulation, no writes
    uv run inferq ingest --dry-run --limit 5

    # Real ingest: small + medium qubit range, all 3 suites
    uv run inferq ingest --max-qubits 16

    # Just one suite, capped to 50 circuits
    uv run inferq ingest --suites mqt --limit 50
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# pattern used by experiments/ooc/select_circuits.py).
from inferq.config import (
    get_circuit_config,
    get_simulation_config,
    get_storage_config,
)
from inferq.datasets import (
    BenchmarkCircuit,
    BenchmarkLoader,
    MQTBenchLoader,
    QASMBenchLoader,
    SupermarqLoader,
)
from inferq.features.extractors import extract_features
from inferq.simulation import process_simulation_data_for_features
from inferq.simulation.simulate import QuantumSimulator
from inferq.storage.duplicates import initialize_duplicate_detection, is_circuit_duplicate
from inferq.storage.hashing import compute_circuit_hash_simple
from inferq.storage.local import save_circuit_locally

LOG_FMT = "%(asctime)s - INGEST - %(levelname)s - %(message)s"
logger = logging.getLogger("ingest_benchmarks")

SUITE_REGISTRY: dict[str, type[BenchmarkLoader]] = {
    "mqt": MQTBenchLoader,
    "supermarq": SupermarqLoader,
    "qasmbench": QASMBenchLoader,
}


@dataclass
class IngestStats:
    """Per-run counters surfaced at the end so the user sees where time went."""

    seen: int = 0
    skipped_too_large: int = 0
    skipped_duplicate: int = 0
    sim_failed: int = 0
    saved: int = 0
    elapsed_seconds: float = 0.0

    def report(self) -> str:
        return (
            f"seen={self.seen}, saved={self.saved}, "
            f"skipped_duplicate={self.skipped_duplicate}, "
            f"skipped_too_large={self.skipped_too_large}, "
            f"sim_failed={self.sim_failed}, elapsed={self.elapsed_seconds:.1f}s"
        )


def load_local_hashes(storage_path: Path) -> set[str]:
    """Load hashes already present in the target storage directory.

    The local saver writes circuits under `<storage>/<hash>/`, so directory
    names are enough. If metadata exists, include its `qpy_sha256` too in case
    the layout was changed by an older run.
    """
    import json

    hashes: set[str] = set()
    if not storage_path.exists():
        return hashes
    for child in storage_path.iterdir():
        if not child.is_dir():
            continue
        if len(child.name) == 64:
            hashes.add(child.name)
        meta_path = child / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                h = meta.get("qpy_sha256")
                if isinstance(h, str) and h:
                    hashes.add(h)
            except Exception:
                pass
    return hashes


def _process_one(
    bc: BenchmarkCircuit,
    simulator: QuantumSimulator,
    storage_path: Path,
    max_circuit_size: int,
    dry_run: bool,
    dedupe_scope: str,
    known_hashes: set[str],
    stats: IngestStats,
) -> None:
    """Run a single circuit through the existing pipeline primitives."""
    qc = bc.circuit
    tag = f"{bc.source}/{bc.benchmark_name}"
    logger.info(
        f"→ {tag}: qubits={qc.num_qubits}, depth={qc.depth()}, size={qc.size()}"
    )

    if qc.size() > max_circuit_size:
        logger.info(f"  skip (size {qc.size()} > max_circuit_size {max_circuit_size})")
        stats.skipped_too_large += 1
        return

    if dedupe_scope == "azure":
        is_dup, circuit_hash = is_circuit_duplicate(qc)
    else:
        circuit_hash = compute_circuit_hash_simple(qc)
        is_dup = circuit_hash in known_hashes

    if is_dup:
        logger.info(f"  skip duplicate (hash={circuit_hash[:8]}…)")
        stats.skipped_duplicate += 1
        return
    known_hashes.add(circuit_hash)

    if dry_run:
        logger.info(f"  [dry-run] would save hash={circuit_hash[:8]}…")
        return

    # ---- feature extraction ----
    try:
        features = extract_features(circuit=qc)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        logger.warning(f"  feature extraction failed: {type(e).__name__}: {e}")
        stats.sim_failed += 1
        return
    # Tag with source/benchmark_name BEFORE save so they land in meta.json.
    # save_circuit_locally does `**features` into the meta dict, so any extra
    # key here is persisted automatically and surfaces in
    # inferq.transfer.consolidate_metadata's next parquet build.
    features["source"] = bc.source
    features["benchmark_name"] = bc.benchmark_name

    # ---- simulation ----
    # We catch BaseException (not just Exception) because Qiskit 2.0.1's
    # `elide_permutations` Rust pass panics on a handful of structurally-valid
    # circuits (e.g. mqt/ae_n2). The panic surfaces as `pyo3_runtime.PanicException`,
    # which extends BaseException directly. Without this we'd abort the whole
    # ingest run on the first bad circuit. KeyboardInterrupt/SystemExit are
    # re-raised so Ctrl-C still works.
    try:
        sim_results = simulator.simulate_all_methods(qc)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        logger.warning(f"  simulation failed: {type(e).__name__}: {e}")
        stats.sim_failed += 1
        return

    combined_features = process_simulation_data_for_features(sim_results, features)
    # process_simulation_data_for_features may shallow-copy and drop fields
    # depending on its implementation — re-tag to be safe.
    combined_features["source"] = bc.source
    combined_features["benchmark_name"] = bc.benchmark_name

    # ---- save ----
    saved_hash, _, written = save_circuit_locally(
        qc, combined_features, storage_path, expected_hash=circuit_hash
    )
    if written:
        logger.info(f"  saved hash={saved_hash[:8]}…")
        stats.saved += 1
    else:
        # Race with another process that wrote the same hash between our
        # duplicate check and save. Treat as duplicate, not as an error.
        logger.info(f"  already on disk (race): hash={saved_hash[:8]}…")
        stats.skipped_duplicate += 1


def run(
    suites: list[str],
    min_qubits: int,
    max_qubits: int,
    max_circuit_size: int,
    limit_per_suite: int | None,
    dry_run: bool,
    dedupe_scope: str,
    storage_path: Path,
    simulator: QuantumSimulator,
) -> dict[str, IngestStats]:
    """Top-level ingestion loop.

    Index every loader once, then process circuits in (num_qubits, source,
    benchmark_name) order — so the corpus grows monotonically by qubit count
    and interrupting partway leaves a clean prefix (every circuit ≤ k qubits
    is done). The index pass is deliberately upfront so QASMBench's 132 QASM
    files are parsed exactly once instead of re-parsed for each qubit step.
    """
    storage_path.mkdir(parents=True, exist_ok=True)
    known_hashes = load_local_hashes(storage_path) if dedupe_scope == "local" else set()
    if dedupe_scope == "local":
        logger.info(f"loaded {len(known_hashes)} existing local hashes from {storage_path}")
    if dedupe_scope == "azure" and not dry_run:
        # Loads the prior-circuit hash cache so duplicate detection works
        # against the historical 200k corpus, not just this session's writes.
        initialize_duplicate_detection()

    # ---- Phase 1: index ----
    # Walk every loader once and materialize its yields. Memory cost is bounded
    # (<500 small circuits across the three suites within max_qubits=30) and
    # the upfront pass dominates QASMBench parse time.
    per_suite_stats: dict[str, IngestStats] = {s: IngestStats() for s in suites}
    suite_start_times: dict[str, float] = {s: time.time() for s in suites}
    indexed: list[BenchmarkCircuit] = []
    index_t0 = time.time()
    for suite_name in suites:
        loader_cls = SUITE_REGISTRY.get(suite_name)
        if loader_cls is None:
            logger.error(f"unknown suite '{suite_name}' — skipping")
            continue
        loader = loader_cls()
        n_before = len(indexed)
        for bc in loader.iter_circuits(min_qubits=min_qubits, max_qubits=max_qubits):
            indexed.append(bc)
        logger.info(
            f"indexed {len(indexed) - n_before:4d} circuits from {suite_name}"
        )

    # Stable sort: qubit count primary, suite name secondary, benchmark name tertiary.
    indexed.sort(key=lambda b: (b.num_qubits, b.source, b.benchmark_name))
    logger.info(
        f"index complete: {len(indexed)} circuits in {time.time() - index_t0:.1f}s, "
        f"qubit range [{indexed[0].num_qubits if indexed else '-'}, "
        f"{indexed[-1].num_qubits if indexed else '-'}]"
    )

    # ---- Phase 2: process in qubit-ascending order ----
    current_n: int | None = None
    for bc in indexed:
        stats = per_suite_stats[bc.source]
        if limit_per_suite is not None and stats.seen >= limit_per_suite:
            continue  # this suite is exhausted; keep walking for other suites

        if bc.num_qubits != current_n:
            logger.info("=" * 72)
            logger.info(f"Qubit count = {bc.num_qubits}")
            logger.info("=" * 72)
            current_n = bc.num_qubits

        stats.seen += 1
        try:
            _process_one(
                bc=bc,
                simulator=simulator,
                storage_path=storage_path,
                max_circuit_size=max_circuit_size,
                dry_run=dry_run,
                dedupe_scope=dedupe_scope,
                known_hashes=known_hashes,
                stats=stats,
            )
        except Exception as e:
            logger.exception(
                f"unhandled error on {bc.source}/{bc.benchmark_name}: {e}"
            )
        if limit_per_suite is not None and stats.seen >= limit_per_suite:
            logger.info(f"[{bc.source}] hit per-suite limit ({limit_per_suite})")

    for suite_name in per_suite_stats:
        per_suite_stats[suite_name].elapsed_seconds = (
            time.time() - suite_start_times[suite_name]
        )
        logger.info(f"[{suite_name}] {per_suite_stats[suite_name].report()}")

    return per_suite_stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suites",
        default="mqt,supermarq,qasmbench",
        help="Comma-separated suite names. Default: all three.",
    )
    parser.add_argument(
        "--min-qubits",
        type=int,
        default=None,
        help="Override CIRCUIT_GENERATION.min_qubits from config.",
    )
    parser.add_argument(
        "--max-qubits",
        type=int,
        default=None,
        help="Override CIRCUIT_GENERATION.max_qubits from config.",
    )
    parser.add_argument(
        "--max-circuit-size",
        type=int,
        default=None,
        help="Override CIRCUIT_GENERATION.max_circuit_size (gate count).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many circuits SEEN per suite (for smoke tests).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate and hash circuits but do not extract features, "
        "simulate, or write to disk.",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="Override storage_config.local_circuits_dir (mainly for tests).",
    )
    parser.add_argument(
        "--dedupe-scope",
        choices=["session", "local", "azure"],
        default="session",
        help="Duplicate detection scope. 'session' only checks circuits generated "
        "in this run; 'local' also checks --storage-dir; 'azure' uses the global "
        "Azure/cache duplicate detector.",
    )
    parser.add_argument(
        "--iq-omit-methods",
        default=None,
        help="Comma-separated InfiniQuantumSim methods to skip. Use this to run "
        "only selected RDBMS backends, e.g. "
        "'psql,umbra,eqc,np-one-shot,np-mps' for SQLite+DuckDB only.",
    )
    parser.add_argument(
        "--iq-runs",
        type=int,
        default=None,
        help="Override InfiniQuantumSim benchmark repetitions.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format=LOG_FMT)
    # Quiet down third-party chatter — qiskit transpiler logs are very loud.
    for noisy in ("qiskit", "qiskit.passmanager", "qiskit.transpiler", "qiskit_aer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    circuit_cfg = get_circuit_config()
    sim_cfg = get_simulation_config()
    storage_cfg = get_storage_config()
    infiniquantum_cfg = dict(sim_cfg.get("infiniquantum") or {})
    if args.iq_omit_methods is not None:
        infiniquantum_cfg["omit_methods"] = [
            x.strip() for x in args.iq_omit_methods.split(",") if x.strip()
        ]
    if args.iq_runs is not None:
        infiniquantum_cfg["n_runs"] = args.iq_runs

    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    min_qubits = args.min_qubits if args.min_qubits is not None else circuit_cfg["min_qubits"]
    max_qubits = args.max_qubits if args.max_qubits is not None else circuit_cfg["max_qubits"]
    max_size = (
        args.max_circuit_size
        if args.max_circuit_size is not None
        else circuit_cfg["max_circuit_size"]
    )
    storage_path = (
        args.storage_dir
        if args.storage_dir is not None
        else Path(storage_cfg["local_circuits_dir"])
    )

    logger.info(
        f"Config: suites={suites}, qubits=[{min_qubits},{max_qubits}], "
        f"max_circuit_size={max_size}, dry_run={args.dry_run}, "
        f"storage={storage_path}, dedupe_scope={args.dedupe_scope}"
    )

    if args.dry_run:
        # No simulator construction — saves a few seconds on smoke tests.
        simulator = None  # type: ignore[assignment]
    else:
        simulator = QuantumSimulator(
            seed=sim_cfg["seed"],
            shots=sim_cfg["shots"],
            timeout_seconds=sim_cfg["timeout_seconds"],
            infiniquantum_config=infiniquantum_cfg,
        )

    stats = run(
        suites=suites,
        min_qubits=min_qubits,
        max_qubits=max_qubits,
        max_circuit_size=max_size,
        limit_per_suite=args.limit,
        dry_run=args.dry_run,
        dedupe_scope=args.dedupe_scope,
        storage_path=storage_path,
        simulator=simulator,  # type: ignore[arg-type]
    )

    logger.info("=" * 72)
    logger.info("Per-suite summary:")
    grand_saved = 0
    for suite, st in stats.items():
        logger.info(f"  {suite}: {st.report()}")
        grand_saved += st.saved
    logger.info(f"Grand total: {grand_saved} new circuits written to {storage_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
