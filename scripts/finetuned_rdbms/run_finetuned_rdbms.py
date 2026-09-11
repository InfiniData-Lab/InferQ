#!/usr/bin/env python3
"""Benchmark fine-tuned RDBMS engines on existing InferQ circuits.

This script is intentionally separate from scripts/ooc. It does not use memory
caps, Docker orchestration, OOC manifests, or OOC CSV schemas. It reads existing
InferQ .qpy circuits, generates the InfiniQuantumSim SQL contraction query, and
runs it on tuned DuckDB, SQLite, and PostgreSQL connections.

Examples
--------
  python scripts/finetuned_rdbms/run_finetuned_rdbms.py --limit 10 --profile balanced

  python scripts/finetuned_rdbms/run_finetuned_rdbms.py \
      --circuits-dir circuits --engines duckdb,sqlite,postgres \
      --min-qubits 4 --max-qubits 18 --n-runs 3 --resume
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import tracemalloc
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable


_INFERQ_CHECKOUT = Path(__file__).resolve().parents[2]
if str(_INFERQ_CHECKOUT) not in sys.path:
    sys.path.insert(0, str(_INFERQ_CHECKOUT))

from scripts.lib import drain_cursor, repo_root  # noqa: E402

REPO_ROOT = repo_root()
INFERQ_ROOT = REPO_ROOT / "InferQ"
IQS_ROOT = REPO_ROOT / "Infinidata-rdbms-simulator"
for p in (INFERQ_ROOT, IQS_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


CSV_FIELDS = [
    "circuit_hash",
    "qpy_path",
    "num_qubits",
    "num_gates",
    "query_gen_time_s",
    "query_bytes",
    "total_ctes",
    "tensor_ctes",
    "contraction_ctes",
    "engine",
    "profile",
    "run_idx",
    "status",
    "wall_time_s",
    "rows_consumed",
    "tracemalloc_peak_bytes",
    "tuning",
    "error_msg",
]

ENGINES = ("duckdb", "sqlite", "postgres")
PROFILES = ("balanced", "fast", "spill_safe")
CTE_HEAD = re.compile(r"\s*(\w+)(\s*\([^)]*\))?\s+AS\s*\(", re.IGNORECASE)


@dataclass(frozen=True)
class CteDef:
    name: str
    columns: str
    body: str


@dataclass(frozen=True)
class QueryShape:
    total_ctes: int
    tensor_ctes: int
    contraction_ctes: int


def load_qpy(path: Path):
    from qiskit.qpy import load

    with path.open("rb") as f:
        circuits = load(f)
    if not circuits:
        raise RuntimeError(f"no circuit found in {path}")
    return circuits[0]


def build_iqs_query(qc) -> tuple[str, int, int]:
    import opt_einsum as oe
    from qiskit import transpile
    from InfiniQuantumSim.sql_commands import sql_einsum_query
    from InfiniQuantumSim.TLtensor import Gate as IQSGate
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit
    from InfiniQuantumSim.utils import INDICES

    transpiled = transpile(
        qc,
        basis_gates=["u", "cx", "id", "rz", "sx", "x"],
        optimization_level=2,
    )
    num_qubits = transpiled.num_qubits
    estimated = num_qubits + 3 * len(transpiled.data)
    if estimated >= len(INDICES):
        raise RuntimeError(f"circuit exceeds IQS index budget: {estimated} >= {len(INDICES)}")

    iqs = IQSQuantumCircuit(num_qubits=num_qubits)
    for instr in transpiled.data:
        op = instr.operation
        if op.name in ("barrier", "measure"):
            continue
        qubits = [transpiled.find_bit(q).index for q in instr.qubits]
        matrix = op.to_matrix()
        if len(qubits) == 1:
            tensor = matrix
        elif len(qubits) == 2:
            tensor = matrix.reshape(2, 2, 2, 2)
        else:
            raise RuntimeError(f"unsupported {op.name} on {len(qubits)} qubits")
        gate_name = f"{op.name}_{id(op)}" if op.params else op.name
        iqs.add_gate(IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=len(qubits) == 2))

    einstein, index_sizes, parameters = iqs.convert_to_einsum()
    opt_rg = oe.RandomGreedy(max_repeats=256, parallel=False)
    views = oe.helpers.build_views(einstein, index_sizes)
    _, path_info = oe.contract_path(einstein, *views, optimize=opt_rg)
    query = sql_einsum_query(
        einstein,
        parameters,
        iqs.tensor_uniques,
        path_info=path_info,
        complex=True,
    )
    return query, num_qubits, len(iqs.gates)


def build_iqs_query_with_timeout(qc, timeout_s: int) -> tuple[str, int, int, float]:
    start = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(build_iqs_query, qc)
    try:
        query, num_qubits, num_gates = fut.result(timeout=timeout_s)
    except FutureTimeout as e:
        fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"query generation timed out after {timeout_s}s") from e
    pool.shutdown(wait=True)
    return query, num_qubits, num_gates, time.perf_counter() - start


def parse_iqs_ctes(query: str) -> tuple[list[CteDef], str]:
    s = query.lstrip()
    if not s.upper().startswith("WITH "):
        return [], s
    s = s[5:]

    ctes: list[CteDef] = []
    pos = 0
    while True:
        m = CTE_HEAD.match(s, pos)
        if not m:
            break
        name = m.group(1)
        columns = (m.group(2) or "").strip()
        body_start = m.end()
        depth = 1
        i = body_start
        while i < len(s) and depth > 0:
            c = s[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        if depth != 0:
            break
        ctes.append(CteDef(name=name, columns=columns, body=s[body_start:i - 1]))
        pos = i
        while pos < len(s) and s[pos] in " \t\n,":
            pos += 1
    return ctes, s[pos:].strip()


def query_shape(query: str) -> QueryShape:
    ctes, _ = parse_iqs_ctes(query)
    contraction_ctes = sum(1 for cte in ctes if cte.name.startswith("K"))
    total_ctes = len(ctes)
    return QueryShape(
        total_ctes=total_ctes,
        tensor_ctes=total_ctes - contraction_ctes,
        contraction_ctes=contraction_ctes,
    )


def tuning_for(profile: str, engine: str, tmp_root: Path) -> dict[str, Any]:
    cpu = os.cpu_count() or 1
    if engine == "duckdb":
        if profile == "fast":
            return {
                "threads": min(8, max(1, cpu)),
                "memory_limit": os.getenv("INFERQ_DUCKDB_MEMORY_LIMIT", "8GB"),
                "temp_directory": str(tmp_root / "duckdb"),
                "preserve_insertion_order": False,
                "max_temp_directory_size": os.getenv("INFERQ_DUCKDB_MAX_TEMP", "256GB"),
            }
        if profile == "spill_safe":
            return {
                "threads": 1,
                "memory_limit": "1GB",
                "temp_directory": str(tmp_root / "duckdb"),
                "preserve_insertion_order": False,
                "max_temp_directory_size": os.getenv("INFERQ_DUCKDB_MAX_TEMP", "256GB"),
            }
        return {
            "threads": min(4, max(1, cpu)),
            "memory_limit": os.getenv("INFERQ_DUCKDB_MEMORY_LIMIT", "4GB"),
            "temp_directory": str(tmp_root / "duckdb"),
            "preserve_insertion_order": False,
            "max_temp_directory_size": os.getenv("INFERQ_DUCKDB_MAX_TEMP", "256GB"),
        }

    if engine == "sqlite":
        if profile == "fast":
            cache_mb = 2048
            temp_store = "MEMORY"
            mmap_mb = 1024
            threads = min(8, max(1, cpu))
        elif profile == "spill_safe":
            cache_mb = 256
            temp_store = "FILE"
            mmap_mb = 0
            threads = 1
        else:
            cache_mb = 1024
            temp_store = "MEMORY"
            mmap_mb = 512
            threads = min(4, max(1, cpu))
        return {
            "cache_mb": cache_mb,
            "temp_store": temp_store,
            "mmap_mb": mmap_mb,
            "threads": threads,
            "db_path": str(tmp_root / "sqlite" / "bench.db"),
        }

    if engine == "postgres":
        if profile == "fast":
            work_mem = "512MB"
            temp_buffers = "256MB"
            parallel = min(8, cpu)
            effective_cache_size = "16GB"
            hash_mem_multiplier = "2.0"
        elif profile == "spill_safe":
            work_mem = "64MB"
            temp_buffers = "64MB"
            parallel = 1
            effective_cache_size = "2GB"
            hash_mem_multiplier = "1.0"
        else:
            work_mem = "256MB"
            temp_buffers = "128MB"
            parallel = min(4, cpu)
            effective_cache_size = "8GB"
            hash_mem_multiplier = "2.0"
        return {
            "work_mem": work_mem,
            "temp_buffers": temp_buffers,
            "max_parallel_workers_per_gather": parallel,
            "effective_cache_size": effective_cache_size,
            "hash_mem_multiplier": hash_mem_multiplier,
            "jit": "off",
            "join_collapse_limit": 1,
            "from_collapse_limit": 1,
            "temp_file_limit": "-1",
        }

    raise ValueError(f"unknown engine {engine!r}")


def load_tuning_json(raw: str | None) -> dict[str, Any] | None:
    """Load explicit tuning JSON from a string or path.

    The JSON can be either a single tuning dict for one-engine invocations or a
    mapping of engine name to tuning dict for multi-engine runs.
    """
    if not raw:
        return None
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        text = raw
    elif (candidate := Path(raw)).exists():
        text = candidate.read_text()
    else:
        text = raw
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("--tuning-json must decode to a JSON object")
    return data


def tuning_for_run(
    profile: str,
    engine: str,
    tmp_root: Path,
    explicit_tuning: dict[str, Any] | None,
) -> dict[str, Any]:
    if explicit_tuning is None:
        return tuning_for(profile, engine, tmp_root)
    if engine in explicit_tuning:
        tuning = explicit_tuning[engine]
    else:
        tuning = explicit_tuning
    if not isinstance(tuning, dict):
        raise ValueError(f"explicit tuning for {engine!r} must be a JSON object")
    return dict(tuning)


def execute_optional(execute: Callable[[str], Any], sql: str) -> None:
    try:
        execute(sql)
    except Exception:
        pass


def run_with_tracemalloc(fn: Callable[[], Any]) -> dict[str, Any]:
    tracemalloc.start()
    tracemalloc.clear_traces()
    start = time.perf_counter()
    measured_wall_time_s: float | None = None
    try:
        result = fn()
        if isinstance(result, dict) and "rows" in result:
            rows = int(result.get("rows", 0))
            if result.get("wall_time_s") is not None:
                measured_wall_time_s = float(result["wall_time_s"])
        else:
            rows = int(result)
        status = "success"
        error = ""
    except TimeoutError as e:
        rows = 0
        status = "timeout"
        error = str(e)
    except Exception as e:
        rows = 0
        status = "error"
        error = f"{e}\n{traceback.format_exc(limit=4)}"
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "status": status,
        "wall_time_s": measured_wall_time_s if measured_wall_time_s is not None else time.perf_counter() - start,
        "rows_consumed": rows,
        "tracemalloc_peak_bytes": peak,
        "error_msg": flatten_error(error),
    }


def run_duckdb(query: str, tuning: dict[str, Any], timeout_s: float, chunk_size: int) -> Any:
    import duckdb

    timing_scope = tuning.get("_timing_scope", "full")
    temp_dir = Path(tuning["temp_directory"])
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={int(tuning['threads'])}")
    con.execute(f"SET memory_limit='{tuning['memory_limit']}'")
    con.execute(f"SET temp_directory='{temp_dir}'")
    execute_optional(con.execute, f"SET max_temp_directory_size='{tuning['max_temp_directory_size']}'")
    if not tuning.get("preserve_insertion_order", True):
        con.execute("SET preserve_insertion_order=false")
    execute_optional(con.execute, "SET enable_progress_bar=false")

    result: dict[str, Any] = {}

    def execute():
        try:
            start = time.perf_counter()
            cur = con.execute(query)
            rows = drain_cursor(cur, chunk_size=chunk_size)
            result["rows"] = rows
            if timing_scope == "contraction":
                result["wall_time_s"] = time.perf_counter() - start
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)
    if thread.is_alive():
        # DuckDB can block in close() while a monolithic query is still inside
        # execution/cancellation. Interrupt and return control to the tuner; the
        # daemon thread is process-scoped and will be reaped when the trial
        # worker exits.
        try:
            con.interrupt()
        except Exception:
            pass
        raise TimeoutError(f"duckdb timed out after {timeout_s}s")
    con.close()
    if "error" in result:
        raise result["error"]
    if timing_scope == "contraction":
        return {
            "rows": int(result.get("rows", 0)),
            "wall_time_s": result.get("wall_time_s"),
        }
    return int(result.get("rows", 0))


def run_sqlite(query: str, tuning: dict[str, Any], timeout_s: float, chunk_size: int) -> Any:
    import sqlite3

    timing_scope = tuning.get("_timing_scope", "full")
    db_path = Path(tuning["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db_path.unlink()
    except FileNotFoundError:
        pass

    con = sqlite3.connect(str(db_path), check_same_thread=False)
    cur = con.cursor()
    cur.execute(f"PRAGMA journal_mode={tuning.get('journal_mode', 'OFF')}")
    cur.execute(f"PRAGMA synchronous={tuning.get('synchronous', 'OFF')}")
    cur.execute(f"PRAGMA locking_mode={tuning.get('locking_mode', 'EXCLUSIVE')}")
    cur.execute(f"PRAGMA automatic_index={'ON' if tuning.get('automatic_index', True) else 'OFF'}")
    cur.execute(f"PRAGMA temp_store={tuning['temp_store']}")
    cur.execute(f"PRAGMA cache_size=-{int(tuning['cache_mb']) * 1024}")
    cur.execute(f"PRAGMA cache_spill={'ON' if tuning.get('cache_spill', True) else 'OFF'}")
    cur.execute(f"PRAGMA mmap_size={int(tuning['mmap_mb']) * 1024 * 1024}")
    execute_optional(cur.execute, f"PRAGMA threads={int(tuning['threads'])}")

    deadline = time.perf_counter() + timeout_s

    def progress_handler() -> int:
        return 1 if time.perf_counter() >= deadline else 0

    con.set_progress_handler(progress_handler, 100)
    try:
        start = time.perf_counter()
        cur.execute(query)
        rows = drain_cursor(cur, chunk_size=chunk_size)
        con.commit()
        execute_optional(cur.execute, "PRAGMA optimize")
        if timing_scope == "contraction":
            return {
                "rows": rows,
                "wall_time_s": time.perf_counter() - start,
            }
        return rows
    except sqlite3.OperationalError as e:
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"sqlite timed out after {timeout_s}s") from e
        raise
    finally:
        con.set_progress_handler(None, 0)
        cur.close()
        con.close()


def run_postgres(query: str, tuning: dict[str, Any], timeout_s: float, chunk_size: int) -> Any:
    import psycopg2

    timing_scope = tuning.get("_timing_scope", "full")
    con = psycopg2.connect(
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
        database=os.getenv("POSTGRES_DB", "postgres"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
    )
    con.set_session(autocommit=True)
    cur = con.cursor()
    statement_timeout_ms = max(1, math.ceil(timeout_s * 1000))
    cur.execute("SET statement_timeout = %s", (statement_timeout_ms,))
    cur.execute(f"SET work_mem = '{tuning['work_mem']}'")
    cur.execute(f"SET temp_buffers = '{tuning['temp_buffers']}'")
    cur.execute(f"SET max_parallel_workers_per_gather = {int(tuning['max_parallel_workers_per_gather'])}")
    cur.execute(f"SET effective_cache_size = '{tuning['effective_cache_size']}'")
    cur.execute(f"SET join_collapse_limit = {int(tuning['join_collapse_limit'])}")
    cur.execute(f"SET from_collapse_limit = {int(tuning['from_collapse_limit'])}")
    cur.execute(f"SET temp_file_limit = '{tuning['temp_file_limit']}'")
    execute_optional(cur.execute, f"SET jit = {tuning['jit']}")
    execute_optional(cur.execute, f"SET hash_mem_multiplier = {tuning['hash_mem_multiplier']}")
    execute_optional(cur.execute, "SET enable_partitionwise_aggregate = on")
    execute_optional(cur.execute, "SET synchronous_commit = off")

    result: dict[str, Any] = {}

    def execute():
        try:
            start = time.perf_counter()
            cur.execute(query)
            rows = drain_cursor(cur, chunk_size=chunk_size)
            result["rows"] = rows
            if timing_scope == "contraction":
                result["wall_time_s"] = time.perf_counter() - start
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)
    if thread.is_alive():
        try:
            con.cancel()
        finally:
            cur.close()
            con.close()
        raise TimeoutError(f"postgres timed out after {timeout_s}s")
    cur.close()
    con.close()
    if "error" in result:
        raise result["error"]
    if timing_scope == "contraction":
        return {
            "rows": int(result.get("rows", 0)),
            "wall_time_s": result.get("wall_time_s"),
        }
    return int(result.get("rows", 0))


RUNNERS: dict[str, Callable[[str, dict[str, Any], float, int], Any]] = {
    "duckdb": run_duckdb,
    "sqlite": run_sqlite,
    "postgres": run_postgres,
}


def flatten_error(msg: str) -> str:
    return (msg or "").replace("\\", "\\\\").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def iter_circuits(circuits_dir: Path) -> list[Path]:
    return sorted(circuits_dir.glob("*/*.qpy")) + sorted(circuits_dir.glob("*.qpy"))


def read_lines(path: Path) -> list[str]:
    with path.open() as f:
        return [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]


def read_hashes(path: Path) -> set[str]:
    return {line.split(",", 1)[0].strip() for line in read_lines(path)}


def read_qpy_list(path: Path) -> list[Path]:
    base = path.parent
    out: list[Path] = []
    for line in read_lines(path):
        p = Path(line.split(",", 1)[0].strip())
        out.append(p if p.is_absolute() else (base / p).resolve())
    return out


def read_seen(path: Path) -> set[tuple[str, str, str, str]]:
    if not path.exists():
        return set()
    with path.open() as f:
        return {
            (
                row["circuit_hash"],
                row["engine"],
                row["profile"],
                row["run_idx"],
            )
            for row in csv.DictReader(f)
        }


def assert_csv_schema(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(newline="") as f:
        header = next(csv.reader(f), [])
    if header and header != CSV_FIELDS:
        raise SystemExit(
            f"{path} has an older CSV schema; choose a new --out-csv or move the old file first"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--circuits-dir", type=Path, default=INFERQ_ROOT / "circuits")
    parser.add_argument("--out-csv", type=Path, default=INFERQ_ROOT / "analysis" / "finetuned_rdbms_results.csv")
    parser.add_argument("--engines", default="duckdb,sqlite,postgres")
    parser.add_argument("--profile", choices=PROFILES, default="balanced")
    parser.add_argument("--tuning-json", default=None,
                        help="Explicit tuning JSON string or path. Can be a single "
                             "engine tuning dict or a mapping of engine to tuning dict.")
    parser.add_argument("--tuning-label", default=None,
                        help="Profile label to write when --tuning-json is used.")
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--query-timeout-seconds", type=int, default=300)
    parser.add_argument("--fetch-chunk-size", type=int, default=8192)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--hashes-file", type=Path, default=None,
                        help="File containing exact circuit hashes to include, one per line.")
    parser.add_argument("--qpy-list", type=Path, default=None,
                        help="File containing exact .qpy paths to run, one per line.")
    parser.add_argument("--min-qubits", type=int, default=None)
    parser.add_argument("--max-qubits", type=int, default=None)
    parser.add_argument("--min-gates", type=int, default=None)
    parser.add_argument("--max-gates", type=int, default=None)
    parser.add_argument("--hash-prefix", default="",
                        help="Only run circuits whose filename hash starts with this prefix.")
    parser.add_argument("--tmp-root", type=Path, default=Path(tempfile.gettempdir()) / "inferq_finetuned_rdbms")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    invalid = sorted(set(engines) - set(ENGINES))
    if invalid:
        raise SystemExit(f"unsupported engines: {invalid}")
    try:
        explicit_tuning = load_tuning_json(args.tuning_json)
    except Exception as e:
        raise SystemExit(f"invalid --tuning-json: {e}") from e
    profile_label = args.tuning_label or args.profile

    if args.qpy_list:
        paths = read_qpy_list(args.qpy_list)
    else:
        paths = iter_circuits(args.circuits_dir)
    if args.hashes_file:
        wanted_hashes = read_hashes(args.hashes_file)
        paths = [p for p in paths if p.stem in wanted_hashes]
    if args.hash_prefix:
        paths = [p for p in paths if p.stem.startswith(args.hash_prefix)]
    if args.limit is not None:
        paths = paths[: args.limit]
    if not paths:
        raise SystemExit(f"no .qpy circuits found under {args.circuits_dir}")

    if args.dry_run:
        print(f"[dry-run] candidate circuits: {len(paths)}", file=sys.stderr)
        for idx, qpy_path in enumerate(paths, 1):
            print(f"[dry-run] [{idx}/{len(paths)}] {qpy_path}", file=sys.stderr)
            for engine in engines:
                tuning = tuning_for_run(args.profile, engine, args.tmp_root, explicit_tuning)
                print(
                    f"[dry-run]     {engine}/{profile_label} tuning="
                    f"{json.dumps(tuning, sort_keys=True)}",
                    file=sys.stderr,
                )
        return 0

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    assert_csv_schema(args.out_csv)
    seen = read_seen(args.out_csv) if args.resume else set()
    write_header = not args.out_csv.exists() or args.out_csv.stat().st_size == 0

    with args.out_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()

        for idx, qpy_path in enumerate(paths, 1):
            circuit_hash = qpy_path.stem
            try:
                qc = load_qpy(qpy_path)
                if args.min_qubits is not None and qc.num_qubits < args.min_qubits:
                    continue
                if args.max_qubits is not None and qc.num_qubits > args.max_qubits:
                    continue
                if args.min_gates is not None and qc.size() < args.min_gates:
                    continue
                if args.max_gates is not None and qc.size() > args.max_gates:
                    continue
                print(f"[{idx}/{len(paths)}] {circuit_hash[:8]} q={qc.num_qubits} gates={qc.size()}", file=sys.stderr)
                query, num_qubits, num_gates, query_gen_s = build_iqs_query_with_timeout(
                    qc, args.query_timeout_seconds
                )
                shape = query_shape(query)
                print(
                    f"    query={len(query)} bytes ctes={shape.total_ctes} "
                    f"tensors={shape.tensor_ctes} contractions={shape.contraction_ctes}",
                    file=sys.stderr,
                )
            except Exception as e:
                row = {
                    "circuit_hash": circuit_hash,
                    "qpy_path": str(qpy_path),
                    "num_qubits": getattr(locals().get("qc", None), "num_qubits", ""),
                    "num_gates": getattr(locals().get("qc", None), "size", lambda: "")(),
                    "query_gen_time_s": "",
                    "query_bytes": "",
                    "total_ctes": "",
                    "tensor_ctes": "",
                    "contraction_ctes": "",
                    "engine": "",
                    "profile": args.profile,
                    "run_idx": "",
                    "status": "query_error",
                    "wall_time_s": "",
                    "rows_consumed": "",
                    "tracemalloc_peak_bytes": "",
                    "tuning": "",
                    "error_msg": flatten_error(f"{e}\n{traceback.format_exc(limit=4)}"),
                }
                writer.writerow(row)
                f.flush()
                continue

            for engine in engines:
                tuning = tuning_for_run(args.profile, engine, args.tmp_root, explicit_tuning)
                labels = [f"warmup{i}" for i in range(args.warmup)] + [str(i) for i in range(args.n_runs)]
                for run_idx in labels:
                    key = (circuit_hash, engine, profile_label, run_idx)
                    if key in seen:
                        continue
                    print(f"    {engine}/{profile_label} run={run_idx}", file=sys.stderr)
                    runner = RUNNERS[engine]
                    result = run_with_tracemalloc(
                        lambda runner=runner, tuning=tuning, query=query: runner(
                            query, tuning, args.timeout_seconds, args.fetch_chunk_size
                        )
                    )
                    writer.writerow({
                        "circuit_hash": circuit_hash,
                        "qpy_path": str(qpy_path),
                        "num_qubits": num_qubits,
                        "num_gates": num_gates,
                        "query_gen_time_s": query_gen_s,
                        "query_bytes": len(query),
                        "total_ctes": shape.total_ctes,
                        "tensor_ctes": shape.tensor_ctes,
                        "contraction_ctes": shape.contraction_ctes,
                        "engine": engine,
                        "profile": profile_label,
                        "run_idx": run_idx,
                        "status": result["status"],
                        "wall_time_s": result["wall_time_s"],
                        "rows_consumed": result["rows_consumed"],
                        "tracemalloc_peak_bytes": result["tracemalloc_peak_bytes"],
                        "tuning": json.dumps(tuning, sort_keys=True),
                        "error_msg": result["error_msg"],
                    })
                    f.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
