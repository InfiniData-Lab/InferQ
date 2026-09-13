#!/usr/bin/env python3
"""End-to-end smoke test for an InferQ checkout.

Answers one question: is this environment set up to run the real pipeline? It
drives the production parallel pipeline -- the same code path as
``inferq run parallel`` -- over a handful of circuits, then checks that
every artifact the pipeline is supposed to leave behind actually landed on
disk:

    circuits/<hash>/circuit.qpy   the serialized circuit
    circuits/<hash>/meta.json     features, simulation metrics, provenance
    circuits/<hash>/circuit.sql   the InfiniQuantumSim lowering of the circuit

Before running anything it probes each SQL engine the simulation path can use
and reports which are reachable. Engines that are configured take part in the
run; engines that are not are named, along with the environment variables that
would configure them, and excluded so the run does not block on a connection
that will never open. A missing engine is reported, never fatal -- the point of
the report is to tell you what this machine can and cannot do.

Azure upload is forced off unless ``--azure`` is passed, so a smoke test never
writes throwaway circuits into shared storage by accident.

Usage:
    inferq smoke                 # 3 circuits, local only
    inferq smoke --circuits 5
    inferq smoke --query-mode split
    inferq smoke --azure         # include the upload step
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def heading(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def line(status: str, text: str, detail: str = "") -> None:
    print(f"  [{status}] {text}" + (f" -- {detail}" if detail else ""))


# --------------------------------------------------------------------------
# SQL engine probes
# --------------------------------------------------------------------------

#: Every backend the InfiniQuantumSim path can time, in report order. The two
#: array stores upstream also ships (SciDB, TileDB) are omitted unconditionally
#: by ``inferq.simulation.infiniquantum`` and so are not probed here.
@dataclass(frozen=True)
class EngineStatus:
    """One SQL engine the simulation path can benchmark against."""

    name: str  # the name InfiniQuantumSim knows it by
    label: str
    available: bool
    detail: str
    env_hint: str = ""


def _probe_sqlite() -> EngineStatus:
    import sqlite3

    try:
        con = sqlite3.connect(":memory:")
        con.execute("SELECT 1").fetchone()
        con.close()
        return EngineStatus("sqlite", "SQLite", True, "in-process, no configuration needed")
    except Exception as exc:  # pragma: no cover - stdlib sqlite is always present
        return EngineStatus("sqlite", "SQLite", False, str(exc))


def _probe_duckdb() -> EngineStatus:
    try:
        import duckdb

        con = duckdb.connect()
        con.execute("SELECT 1").fetchall()
        con.close()
        return EngineStatus(
            "ducksql", "DuckDB", True, f"in-process, version {duckdb.__version__}"
        )
    except Exception as exc:
        return EngineStatus(
            "ducksql",
            "DuckDB",
            False,
            str(exc),
            env_hint="install the duckdb package (it is a base dependency)",
        )


def _probe_postgres_like(
    name: str,
    label: str,
    env_prefix: str,
    default_port: str,
    connect_timeout: int,
) -> EngineStatus:
    """Probe a PostgreSQL-wire server using the env vars InfiniQuantumSim reads."""
    settings = {
        "user": os.getenv(f"{env_prefix}_USER", "postgres"),
        "password": os.getenv(f"{env_prefix}_PASSWORD", "password"),
        "database": os.getenv(f"{env_prefix}_DB", "postgres"),
        "host": os.getenv(f"{env_prefix}_HOST", "localhost"),
        "port": os.getenv(f"{env_prefix}_PORT", default_port),
    }
    env_hint = (
        f"set {env_prefix}_HOST / {env_prefix}_PORT / {env_prefix}_USER / "
        f"{env_prefix}_PASSWORD / {env_prefix}_DB and start the server"
    )
    try:
        import psycopg2
    except Exception as exc:
        return EngineStatus(name, label, False, f"psycopg2 unavailable: {exc}", env_hint)

    try:
        con = psycopg2.connect(connect_timeout=connect_timeout, **settings)
        con.close()
    except Exception as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return EngineStatus(name, label, False, reason, env_hint)

    return EngineStatus(
        name,
        label,
        True,
        f"{settings['user']}@{settings['host']}:{settings['port']}/{settings['database']}",
    )


def probe_engines(connect_timeout: int) -> list[EngineStatus]:
    """Report which SQL engines this machine can actually benchmark against."""
    return [
        _probe_sqlite(),
        _probe_duckdb(),
        _probe_postgres_like("psql", "PostgreSQL", "POSTGRES", "5432", connect_timeout),
        _probe_postgres_like("umbra", "Umbra", "UMBRA", "5484", connect_timeout),
    ]


def omit_methods_for(engines: list[EngineStatus]) -> list[str]:
    """Build the InfiniQuantumSim omit list from the probe results.

    The numpy baselines (``np-one-shot``, ``np-mps``) and the query-construction
    timing (``eqc``) need no server, so they always run and give the SQL numbers
    something to be compared against.
    """
    return [engine.name for engine in engines if not engine.available]


# --------------------------------------------------------------------------
# Environment report
# --------------------------------------------------------------------------


def report_environment() -> bool:
    """Print interpreter and package versions. Returns False if a hard dep is missing."""
    heading("Environment")
    line(PASS, f"Python {sys.version.split()[0]}", sys.executable)

    ok = True
    for package in ("qiskit", "qiskit_aer", "numpy", "pandas", "duckdb", "opt_einsum"):
        try:
            module = __import__(package)
            line(PASS, package, getattr(module, "__version__", "unknown"))
        except Exception as exc:
            line(FAIL, package, str(exc))
            ok = False

    from inferq.simulation.infiniquantum import INFINI_QUANTUM_AVAILABLE

    if INFINI_QUANTUM_AVAILABLE:
        import InfiniQuantumSim

        line(PASS, "InfiniQuantumSim", str(Path(InfiniQuantumSim.__file__).parent))
    else:
        line(
            SKIP,
            "InfiniQuantumSim",
            "not installed -- no SQL lowering, no circuit.sql artifact "
            "(install with: uv sync --extra sql)",
        )

    return ok


def report_azure(enabled: bool) -> None:
    heading("Azure storage")
    if not enabled:
        line(
            SKIP,
            "blob and table upload",
            "disabled for this run so smoke circuits stay local (pass --azure to include it)",
        )
        return

    try:
        from inferq.remote.connection import AzureConnection

        AzureConnection()
        line(PASS, "blob and table upload", "credentials resolved")
    except Exception as exc:
        line(
            FAIL,
            "blob and table upload",
            f"{exc} -- set AZURE_STORAGE_ACCOUNT / AZURE_CONTAINER_SAS_URL "
            "(see .env.example)",
        )


def report_engines(engines: list[EngineStatus]) -> None:
    heading("SQL engines")
    for engine in engines:
        if engine.available:
            line(PASS, engine.label, engine.detail)
        else:
            detail = f"not configured: {engine.detail}"
            if engine.env_hint:
                detail += f" -- {engine.env_hint}"
            line(SKIP, engine.label, detail)


# --------------------------------------------------------------------------
# Pipeline run
# --------------------------------------------------------------------------

#: Generation limits for a smoke run. The production defaults draw wide, deep
#: circuits that routinely exceed the pipeline's own gate-count ceiling and then
#: take minutes each to contract; these keep every circuit small enough that the
#: whole run is a couple of minutes while still exercising every stage.
SMOKE_CIRCUIT_LIMITS = {
    "MIN_QUBITS": "3",
    "MAX_DEPTH": "30",
    "MAX_GENERATORS": "2",
    "MAX_EVAL_QUBITS": "3",
    "STOPPING_PROB": "0.4",
    # The generator's ceiling is set below the simulator's (1000 gates by
    # default) so a circuit that clears generation is always one the simulator
    # will accept. Left at the production default the two disagree, and a run
    # can spend its attempts on circuits every simulator then refuses.
    # InfiniQuantumSim names every tensor index with a single character and has
    # roughly 600 of them, so a circuit whose transpiled form runs past ~200
    # gates cannot be lowered to SQL at all. Generated circuits are capped well
    # below the pipeline's own ceiling so most of them fit that budget and the
    # run actually exercises the SQL path.
    "MAX_CIRCUIT_SIZE": "60",
}


def existing_circuit_dirs(circuits_dir: Path) -> set[Path]:
    """Circuit directories already on disk, so the run's own output can be isolated."""
    if not circuits_dir.is_dir():
        return set()
    return {path for path in circuits_dir.iterdir() if (path / "meta.json").exists()}


def read_meta(circuit_dir: Path) -> dict:
    """Read a circuit's metadata, treating an unreadable file as empty."""
    try:
        return json.loads((circuit_dir / "meta.json").read_text())
    except Exception:
        return {}


def is_degenerate(circuit_dir: Path) -> bool:
    """True for a stored circuit with no qubits.

    When every generator a composition drew declines its parameters, the merger
    returns an empty circuit and the pipeline stores it like any other. It
    exercises nothing, so a smoke run neither counts it nor holds it against the
    environment.
    """
    return not read_meta(circuit_dir).get("circuit_qubits")


def run_pipeline(
    args: argparse.Namespace, circuits_dir: Path, already_present: set[Path]
) -> tuple[dict, list[Path]]:
    """Run the production parallel pipeline until enough circuits land on disk.

    Generation is stochastic: a batch can produce a circuit that exceeds the
    gate-count limit, duplicates one already stored, or comes back empty because
    every generator it drew declined the parameters. Those are ordinary outcomes,
    not environment faults, so the run retries with a fresh seed instead of
    reporting a failure. Each attempt is a real one-batch pipeline run.
    """
    from inferq.pipeline.manager import run_parallel_pipeline

    heading(f"Pipeline run (target {args.circuits} circuits, {args.workers} worker(s))")
    totals = {"total_processed": 0, "successful": 0, "failed": 0, "timed_out": 0}
    started = time.time()
    new_dirs: list[Path] = []

    for attempt in range(1, args.attempts + 1):
        # Each attempt draws from a different part of the seed space, so a batch
        # that produced nothing usable is not simply repeated.
        os.environ["SEED"] = str(int(os.environ["SEED"]) + attempt * 1000)

        stats = run_parallel_pipeline(
            num_workers=args.workers,
            max_iterations=1,
            batch_size=args.circuits,
            azure_upload_interval=args.circuits + 1,
            batch_timeout_seconds=args.batch_timeout,
        )
        if "error" in stats:
            totals["error"] = stats["error"]
            break

        for key in totals:
            totals[key] += stats.get(key, 0)
        written = sorted(existing_circuit_dirs(circuits_dir) - already_present)
        new_dirs = [path for path in written if not is_degenerate(path)]
        empty = len(written) - len(new_dirs)

        line(
            PASS if new_dirs else SKIP,
            f"attempt {attempt}",
            f"{stats.get('successful', 0)} succeeded, {stats.get('failed', 0)} failed, "
            f"{len(new_dirs)}/{args.circuits} circuits on disk"
            + (f", {empty} empty circuit(s) ignored" if empty else ""),
        )
        if len(new_dirs) >= args.circuits:
            break

    totals["wall_seconds"] = time.time() - started
    return totals, new_dirs


# --------------------------------------------------------------------------
# Artifact verification
# --------------------------------------------------------------------------

#: A circuit is serialized by exactly one of these, chosen by size and content.
SERIALIZED_CIRCUIT_FILES = ("circuit.qpy", "circuit.pkl", "circuit.qasm", "circuit_info.txt")


def verify_circuit_dir(circuit_dir: Path, expect_sql: bool) -> list[tuple[str, str, str]]:
    """Check one circuit directory. Returns (status, artifact, detail) rows.

    ``expect_sql`` says whether InfiniQuantumSim is installed. Even then a
    particular circuit may not have been lowered -- it can exceed the index
    budget the SQL lowering works within -- so a missing query is only a failure
    when the metadata shows the simulation did run.
    """
    rows: list[tuple[str, str, str]] = []

    serialized = [name for name in SERIALIZED_CIRCUIT_FILES if (circuit_dir / name).exists()]
    if serialized:
        name = serialized[0]
        rows.append((PASS, name, f"{(circuit_dir / name).stat().st_size} bytes"))
    else:
        rows.append((FAIL, "circuit.qpy", "no serialized circuit written"))

    if not (circuit_dir / "meta.json").exists():
        rows.append((FAIL, "meta.json", "missing"))
        return rows

    meta = read_meta(circuit_dir)
    if not meta:
        rows.append((FAIL, "meta.json", "unreadable"))
        return rows

    if meta.get("qpy_sha256") != circuit_dir.name:
        rows.append(
            (FAIL, "meta.json", f"hash {meta.get('qpy_sha256')} does not match directory name")
        )
    else:
        simulated = sorted(
            key[: -len("_execution_time")]
            for key, value in meta.items()
            if key.endswith("_execution_time") and value is not None
        )
        rows.append(
            (
                PASS,
                "meta.json",
                f"{len(meta)} fields, {meta.get('circuit_qubits')} qubits, "
                f"simulated by: {', '.join(simulated) if simulated else 'nothing'}",
            )
        )

    sql_path = circuit_dir / "circuit.sql"
    if sql_path.exists():
        rows.append(
            (
                PASS,
                "circuit.sql",
                f"{sql_path.stat().st_size} bytes, {meta.get('sql_query_mode')} mode",
            )
        )
    elif not expect_sql:
        rows.append((SKIP, "circuit.sql", "InfiniQuantumSim not installed"))
    elif meta.get("infiniquantum_execution_time") is None:
        rows.append(
            (
                SKIP,
                "circuit.sql",
                "InfiniQuantumSim did not simulate this circuit -- most often it "
                "transpiles past the SQL lowering's index budget",
            )
        )
    else:
        rows.append(
            (FAIL, "circuit.sql", "InfiniQuantumSim simulated the circuit but no query was written")
        )

    return rows


def report_artifacts(new_dirs: list[Path], expect_sql: bool) -> bool:
    heading("Artifacts")
    if not new_dirs:
        line(FAIL, "circuits", "the run produced no new circuit directories")
        return False

    ok = True
    lowered = 0
    for circuit_dir in sorted(new_dirs):
        print(f"  {circuit_dir.name[:16]}...  ({circuit_dir})")
        for status, artifact, detail in verify_circuit_dir(circuit_dir, expect_sql):
            line(status, artifact, detail)
            ok = ok and status != FAIL
        lowered += (circuit_dir / "circuit.sql").exists()

    # One SQL artifact is enough to prove the lowering works end to end; none at
    # all, with the package installed, means the SQL path never ran.
    if expect_sql and not lowered:
        line(
            FAIL,
            "circuit.sql",
            "no circuit in this run was lowered to SQL -- rerun with a smaller "
            "--max-qubits, or more --attempts, to draw circuits the lowering accepts",
        )
        ok = False

    return ok


def report_sql_backends(
    new_dirs: list[Path], engines: list[EngineStatus], iqs_available: bool
) -> None:
    """Show which engines actually produced a timing, per configured engine."""
    configured = [engine for engine in engines if engine.available]
    if not configured or not new_dirs:
        return

    heading("SQL benchmark results")
    if not iqs_available:
        line(
            SKIP,
            "all engines",
            "nothing to benchmark: InfiniQuantumSim lowers the circuits to SQL and it "
            "is not installed",
        )
        return

    for engine in configured:
        timings = []
        for circuit_dir in new_dirs:
            meta = read_meta(circuit_dir)
            value = meta.get(f"infinidata_quantum_{engine.name.replace('-', '_')}_time_avg_s")
            if value is not None:
                timings.append(value)
        if timings:
            mean = sum(timings) / len(timings)
            line(PASS, engine.label, f"{len(timings)}/{len(new_dirs)} circuits, mean {mean:.4f}s")
        else:
            line(
                SKIP,
                engine.label,
                "configured, but no timing recorded -- the circuit may have been too "
                "large, or the query timed out",
            )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the InferQ pipeline end to end and verify its artifacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--circuits", type=int, default=3, help="Circuits to generate (default: 3)"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel worker processes (default: 1)"
    )
    parser.add_argument(
        "--max-qubits",
        type=int,
        default=5,
        help=(
            "Cap on generated circuit width. Kept low so circuits stay inside the SQL "
            "lowering's index budget and the run stays quick (default: 5)"
        ),
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=5,
        help="Batches to run before giving up on reaching the circuit target (default: 5)",
    )
    parser.add_argument(
        "--query-mode",
        choices=["monolithic", "monolithic_materialized", "split"],
        default="monolithic",
        help="SQL lowering written to circuit.sql (default: monolithic)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Generation seed. Defaults to a random one so repeat runs make fresh circuits.",
    )
    parser.add_argument(
        "--batch-timeout",
        type=int,
        default=600,
        help="Seconds before a worker task is abandoned (default: 600)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=3,
        help="Seconds to wait when probing a database server (default: 3)",
    )
    parser.add_argument(
        "--azure",
        action="store_true",
        help="Include the Azure upload step. Off by default so smoke circuits stay local.",
    )
    return parser.parse_args(argv)


def apply_environment(args: argparse.Namespace, engines: list[EngineStatus]) -> None:
    """Pin the pipeline's configuration for this run.

    Everything the pipeline reads comes from ``config.py``, which resolves each
    setting from the environment first. Worker processes inherit this
    environment, so setting it here configures them too.
    """
    seed = args.seed if args.seed is not None else random.randrange(1, 10**6)
    os.environ.update(
        {
            "SEED": str(seed),
            "WORKERS": str(args.workers),
            "BATCH_SIZE": str(args.circuits),
            "ITERATIONS": "1",
            "IQ_QUERY_MODE": args.query_mode,
            "IQ_OMIT_METHODS": ",".join(omit_methods_for(engines)),
            "AZURE_ENABLED": "True" if args.azure else "False",
            **SMOKE_CIRCUIT_LIMITS,
            "MAX_QUBITS": str(args.max_qubits),
        }
    )
    omitted = omit_methods_for(engines)
    print(f"  seed {seed}, max {args.max_qubits} qubits, {args.query_mode} query mode")
    print(f"  omitted backends: {', '.join(omitted) if omitted else 'none'}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("InferQ smoke test")
    print("=" * 60)

    environment_ok = report_environment()

    engines = probe_engines(args.connect_timeout)
    report_engines(engines)

    heading("Run configuration")
    apply_environment(args, engines)
    report_azure(args.azure)

    import logging

    from inferq.cli.run import configure_logging
    from inferq.config import get_storage_config

    configure_logging(log_file=None)
    logging.getLogger().setLevel(logging.WARNING)

    circuits_dir = Path(get_storage_config()["local_circuits_dir"])
    before = existing_circuit_dirs(circuits_dir)

    stats, new_dirs = run_pipeline(args, circuits_dir, before)

    heading("Pipeline result")
    if "error" in stats:
        line(FAIL, "pipeline", stats["error"])
    line(
        PASS if new_dirs else FAIL,
        "circuits processed",
        f"{stats.get('successful', 0)} succeeded, {stats.get('failed', 0)} failed, "
        f"{stats.get('timed_out', 0)} timed out in {stats['wall_seconds']:.1f}s",
    )
    if len(new_dirs) < stats.get("successful", 0):
        line(
            SKIP,
            "duplicates",
            f"{stats.get('successful', 0) - len(new_dirs)} circuit(s) already existed and "
            "were not rewritten",
        )

    from inferq.simulation.infiniquantum import INFINI_QUANTUM_AVAILABLE

    artifacts_ok = report_artifacts(new_dirs, expect_sql=INFINI_QUANTUM_AVAILABLE)
    report_sql_backends(new_dirs, engines, INFINI_QUANTUM_AVAILABLE)

    heading("Summary")
    unconfigured = [engine.label for engine in engines if not engine.available]
    line(
        PASS if environment_ok else FAIL,
        "environment",
        "all required packages importable" if environment_ok else "missing required packages",
    )
    line(
        PASS if artifacts_ok else FAIL,
        "artifacts",
        f"{len(new_dirs)} circuit(s) written under {circuits_dir}",
    )
    if unconfigured:
        line(SKIP, "engines not configured", ", ".join(unconfigured))

    passed = environment_ok and artifacts_ok
    print()
    print("SMOKE TEST PASSED" if passed else "SMOKE TEST FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
