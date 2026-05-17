#!/usr/bin/env python3
"""Run the full RDBMS training parquet with two size-based tuned profiles.

For each circuit, this runner generates the SQL query once and runs the selected
engines under the corresponding size-based profile. SQLite is run first so its
result is recorded consistently, but SQLite timeouts do not gate the remaining
engines.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import traceback
from typing import Any

import run_finetuned_rdbms as runner


def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "InferQ").is_dir() and (parent / "Infinidata-rdbms-simulator").is_dir():
            return parent
    raise RuntimeError(f"could not find repo root from {start}")


REPO_ROOT = find_repo_root(Path(__file__).resolve())
INFERQ_ROOT = REPO_ROOT / "InferQ"
THIS_DIR = Path(__file__).resolve().parent

BASELINE_TIME_COLS = [
    "rdbms_ducksql_time_s",
    "rdbms_sqlite_time_s",
    "rdbms_psql_time_s",
]

QISKIT_TIME_COLS = [
    "statevector_saved_execution_time",
    "statevector_execution_time",
    "stabilizer_execution_time",
    "density_matrix_execution_time",
    "matrix_product_state_execution_time",
    "extended_stabilizer_execution_time",
    "unitary_execution_time",
    "automatic_execution_time",
]

MANIFEST_COLS = [
    "RowKey",
    "num_qubits",
    "circuit_size",
    "depth",
    "num_joins",
    "num_group_bys",
    "num_select_columns",
    "rdbms_ducksql_time_s",
    "rdbms_ducksql_memory_mb",
    "rdbms_sqlite_time_s",
    "rdbms_sqlite_memory_mb",
    "rdbms_psql_time_s",
    "rdbms_psql_memory_mb",
    "best_time_method",
    "best_mem_method",
    "baseline_sqlite_time_s",
    "best_qiskit_time_s",
    "engine_timeout_s",
]


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def normalize_hash(value: Any) -> str:
    return str(value).strip()


def finite_positive_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0.0:
        return None
    return out


def best_qiskit_time(row: Any) -> float | None:
    times = [
        finite_positive_float(row.get(col))
        for col in QISKIT_TIME_COLS
    ]
    times = [t for t in times if t is not None]
    return min(times) if times else None


def compute_engine_timeout(row: Any) -> float:
    sqlite_time = finite_positive_float(row.get("rdbms_sqlite_time_s"))
    qiskit_time = best_qiskit_time(row)
    if sqlite_time is None:
        raise ValueError("missing positive rdbms_sqlite_time_s")
    if qiskit_time is None:
        raise ValueError("missing positive Qiskit execution-time columns")
    return min(sqlite_time, qiskit_time)


def load_dataset(parquet_path: Path, require_all_engine_baselines: bool):
    import pandas as pd

    try:
        df = pd.read_parquet(parquet_path)
    except ImportError as e:
        raise SystemExit(
            "reading the training parquet requires pyarrow or fastparquet; "
            "install one in the active Python environment"
        ) from e
    if "RowKey" not in df.columns:
        raise SystemExit(f"{parquet_path} is missing RowKey")
    if "circuit_size" not in df.columns:
        raise SystemExit(f"{parquet_path} is missing circuit_size")
    timeout_cols = ["rdbms_sqlite_time_s", *QISKIT_TIME_COLS]
    missing_timeout_cols = [c for c in timeout_cols if c not in df.columns]
    if missing_timeout_cols:
        raise SystemExit(
            f"{parquet_path} is missing columns required for dynamic timeouts: "
            f"{missing_timeout_cols}"
        )
    if require_all_engine_baselines:
        missing_cols = [c for c in BASELINE_TIME_COLS if c not in df.columns]
        if missing_cols:
            raise SystemExit(f"{parquet_path} is missing columns: {missing_cols}")
        df = df[df[BASELINE_TIME_COLS].notna().all(axis=1)].copy()
    df = df[df["RowKey"].notna()].copy()
    df["RowKey"] = df["RowKey"].map(normalize_hash)
    df = df.drop_duplicates("RowKey", keep="first").sort_values("RowKey")
    df["circuit_size"] = df["circuit_size"].astype(float)
    df["baseline_sqlite_time_s"] = df["rdbms_sqlite_time_s"].map(finite_positive_float)
    df["best_qiskit_time_s"] = df.apply(best_qiskit_time, axis=1)
    try:
        df["engine_timeout_s"] = df.apply(compute_engine_timeout, axis=1)
    except ValueError as e:
        raise SystemExit(f"could not compute dynamic timeouts: {e}") from e
    return df


def index_qpy_files(roots: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.qpy")):
            found.setdefault(path.stem, path.resolve())
    return found


def write_lines(path: Path, lines) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for line in lines:
            f.write(f"{line}\n")


def sqlite_small_tuning(_tmp_root: Path) -> dict[str, Any]:
    return {
        "cache_mb": 64,
        "db_path": ":memory:",
        "mmap_mb": 0,
        "temp_store": "MEMORY",
        "threads": 1,
    }


def default_tuning(profile: str, engine: str, tmp_root: Path) -> dict[str, Any]:
    profile_tmp = tmp_root / profile
    if profile == "small_size":
        if engine == "duckdb":
            return {
                "max_temp_directory_size": "256GB",
                "memory_limit": "10780MB",
                "preserve_insertion_order": False,
                "temp_directory": str(profile_tmp / "duckdb"),
                "threads": 2,
            }
        if engine == "sqlite":
            return sqlite_small_tuning(profile_tmp)
        if engine == "postgres":
            return {
                "effective_cache_size": "8GB",
                "from_collapse_limit": 1,
                "hash_mem_multiplier": "2.0",
                "jit": "off",
                "join_collapse_limit": 1,
                "max_parallel_workers_per_gather": 4,
                "temp_buffers": "128MB",
                "temp_file_limit": "-1",
                "work_mem": "256MB",
            }
    elif profile == "large_size":
        if engine == "duckdb":
            return {
                "max_temp_directory_size": "128GB",
                "memory_limit": "7409MB",
                "preserve_insertion_order": True,
                "temp_directory": str(profile_tmp / "duckdb"),
                "threads": 1,
            }
        if engine == "sqlite":
            return {
                "cache_mb": 128,
                "db_path": str(profile_tmp / "sqlite" / "bench.db"),
                "mmap_mb": 128,
                "temp_store": "MEMORY",
                "threads": 1,
            }
        if engine == "postgres":
            return {
                "effective_cache_size": "2GB",
                "from_collapse_limit": 1,
                "hash_mem_multiplier": "1.94",
                "jit": "off",
                "join_collapse_limit": 4,
                "max_parallel_workers_per_gather": 0,
                "temp_buffers": "65MB",
                "temp_file_limit": "-1",
                "work_mem": "55MB",
            }
    raise ValueError(f"no default tuning for {profile}/{engine}")


def load_profile_tunings(path: Path | None, tmp_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    tunings = {
        profile: {
            engine: default_tuning(profile, engine, tmp_root)
            for engine in runner.ENGINES
        }
        for profile in ("small_size", "large_size")
    }
    if not path:
        return tunings
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("--profile-tunings must be a JSON object")
    for profile, profile_data in data.items():
        if profile not in tunings:
            raise ValueError(f"unknown profile in tuning JSON: {profile}")
        if not isinstance(profile_data, dict):
            raise ValueError(f"tuning JSON profile {profile!r} must be an object")
        for engine, engine_tuning in profile_data.items():
            if engine not in runner.ENGINES:
                raise ValueError(f"unknown engine in tuning JSON: {engine}")
            if not isinstance(engine_tuning, dict):
                raise ValueError(f"tuning JSON {profile}/{engine} must be an object")
            tunings[profile][engine] = dict(engine_tuning)
    return tunings


def read_seen(path: Path) -> dict[tuple[str, str, str, str], str]:
    if not path.exists():
        return {}
    seen: dict[tuple[str, str, str, str], str] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            seen[
                (
                    row["circuit_hash"],
                    row["engine"],
                    row["profile"],
                    row["run_idx"],
                )
            ] = row["status"]
    return seen


def is_complete_status(status: str | None) -> bool:
    return bool(status) and status != "skipped_sqlite_timeout"


def write_result_row(
    writer: csv.DictWriter,
    *,
    circuit_hash: str,
    qpy_path: Path,
    num_qubits: Any,
    num_gates: Any,
    query_gen_s: Any,
    query: str | None,
    shape: runner.QueryShape | None,
    engine: str,
    profile: str,
    run_idx: str,
    status: str,
    rows_consumed: Any = "",
    wall_time_s: Any = "",
    tracemalloc_peak_bytes: Any = "",
    tuning: dict[str, Any] | None = None,
    error_msg: str = "",
) -> None:
    writer.writerow({
        "circuit_hash": circuit_hash,
        "qpy_path": str(qpy_path),
        "num_qubits": num_qubits,
        "num_gates": num_gates,
        "query_gen_time_s": query_gen_s,
        "query_bytes": len(query) if query is not None else "",
        "total_ctes": shape.total_ctes if shape else "",
        "tensor_ctes": shape.tensor_ctes if shape else "",
        "contraction_ctes": shape.contraction_ctes if shape else "",
        "engine": engine,
        "profile": profile,
        "run_idx": run_idx,
        "status": status,
        "wall_time_s": wall_time_s,
        "rows_consumed": rows_consumed,
        "tracemalloc_peak_bytes": tracemalloc_peak_bytes,
        "tuning": json.dumps(tuning, sort_keys=True) if tuning else "",
        "error_msg": runner.flatten_error(error_msg),
    })


def run_engine_once(
    *,
    query: str,
    engine: str,
    profile: str,
    run_idx: str,
    tuning: dict[str, Any],
    timeout_s: float,
    fetch_chunk_size: int,
) -> dict[str, Any]:
    print(f"    {engine}/{profile} run={run_idx} timeout={timeout_s:.6g}s", file=sys.stderr)
    engine_runner = runner.RUNNERS[engine]
    return runner.run_with_tracemalloc(
        lambda: engine_runner(query, tuning, timeout_s, fetch_chunk_size)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path,
                        default=INFERQ_ROOT / "analysis" / "training_data" / "rdbms_training_data.parquet")
    parser.add_argument("--qpy-root", type=Path, action="append",
                        help="Directory to search recursively for .qpy files. Can be repeated.")
    parser.add_argument("--out-dir", type=Path,
                        default=INFERQ_ROOT / "analysis" / "finetuned_rdbms_7705_two_profile")
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--profile-tunings", type=Path, default=None,
                        help="Optional JSON overriding small_size/large_size engine tunings.")
    parser.add_argument("--size-threshold", type=float, default=None,
                        help="Use small_size for circuit_size <= threshold; default is median circuit_size.")
    parser.add_argument("--split-quantile", type=float, default=0.5,
                        help="Quantile used when --size-threshold is omitted.")
    parser.add_argument("--engines", default="sqlite,duckdb,postgres")
    parser.add_argument("--timeout-policy", choices=("baseline_min", "static"),
                        default="baseline_min",
                        help=(
                            "baseline_min uses each circuit's min(rdbms_sqlite_time_s, "
                            "best Qiskit execution time); static uses the fixed timeout flags."
                        ))
    parser.add_argument("--sqlite-timeout-seconds", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=10,
                        help="Timeout for DuckDB/Postgres engines.")
    parser.add_argument("--timeout-multiplier", type=float, default=1.0,
                        help="Multiplier applied to baseline_min timeouts before execution.")
    parser.add_argument("--timeout-floor-seconds", type=float, default=0.0,
                        help="Minimum execution timeout when --timeout-policy=baseline_min.")
    parser.add_argument("--query-timeout-seconds", type=int, default=300)
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--fetch-chunk-size", type=int, default=8192)
    parser.add_argument("--tmp-root", type=Path, default=None)
    parser.add_argument("--require-all", action="store_true",
                        help="Fail if any selected parquet circuit has no local QPY file.")
    parser.add_argument("--require-all-engine-baselines", action="store_true",
                        help="Only select rows with all three baseline RDBMS times present.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    invalid = sorted(set(engines) - set(runner.ENGINES))
    if invalid:
        raise SystemExit(f"unsupported engines: {invalid}")
    if "sqlite" in engines:
        engines = ["sqlite"] + [e for e in engines if e != "sqlite"]
    else:
        raise SystemExit("sqlite must be included because it is the gate engine")
    if not 0.0 <= args.split_quantile <= 1.0:
        raise SystemExit("--split-quantile must be between 0 and 1")
    if args.timeout_multiplier <= 0.0:
        raise SystemExit("--timeout-multiplier must be positive")
    if args.timeout_floor_seconds < 0.0:
        raise SystemExit("--timeout-floor-seconds must be non-negative")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_csv or (out_dir / "results_two_profile.csv")
    tmp_root = args.tmp_root or (out_dir / "tmp")
    qpy_roots = args.qpy_root or [
        INFERQ_ROOT / "analysis" / "finetuned_rdbms_7705" / "qpy",
        INFERQ_ROOT / "analysis" / "finetuned_rdbms_162" / "qpy",
        INFERQ_ROOT / "analysis" / "finetuned_rdbms_116" / "qpy",
        INFERQ_ROOT / "circuits",
        INFERQ_ROOT / "data" / "extremes",
    ]

    selected = load_dataset(args.parquet, args.require_all_engine_baselines)
    if args.limit is not None:
        selected = selected.head(args.limit).copy()
    sizes = [float(v) for v in selected["circuit_size"].dropna().tolist()]
    if not sizes:
        raise SystemExit("no circuit_size values found")
    size_threshold = args.size_threshold
    if size_threshold is None:
        size_threshold = percentile(sizes, args.split_quantile)

    selected["size_profile"] = selected["circuit_size"].map(
        lambda x: "small_size" if float(x) <= float(size_threshold) else "large_size"
    )
    manifest_cols = [c for c in MANIFEST_COLS if c in selected.columns] + ["size_profile"]
    manifest_csv = out_dir / "full_7705_two_profile_manifest.csv"
    selected[manifest_cols].to_csv(manifest_csv, index=False)

    qpy_index = index_qpy_files(qpy_roots)
    wanted_hashes = [str(x) for x in selected["RowKey"]]
    found_paths = [qpy_index[h] for h in wanted_hashes if h in qpy_index]
    missing_hashes = [h for h in wanted_hashes if h not in qpy_index]
    hashes_file = out_dir / "full_7705_hashes.txt"
    qpy_list = out_dir / "found_qpy_paths.txt"
    missing_file = out_dir / "missing_hashes.txt"
    tunings_file = out_dir / "profile_tunings.json"
    summary_file = out_dir / "selection_summary.json"

    write_lines(hashes_file, wanted_hashes)
    write_lines(qpy_list, [str(p) for p in found_paths])
    write_lines(missing_file, missing_hashes)
    profile_by_hash = dict(zip(selected["RowKey"], selected["size_profile"]))
    circuit_size_by_hash = dict(zip(selected["RowKey"], selected["circuit_size"]))
    timeout_by_hash = dict(zip(selected["RowKey"], selected["engine_timeout_s"]))
    selected_by_hash = {str(row.RowKey): row for row in selected.itertuples(index=False)}

    tunings = load_profile_tunings(args.profile_tunings, tmp_root)
    tunings_file.write_text(json.dumps(tunings, indent=2, sort_keys=True) + "\n")

    summary = {
        "parquet": str(args.parquet),
        "selected_circuits": len(wanted_hashes),
        "qpy_roots": [str(p) for p in qpy_roots],
        "found_qpy": len(found_paths),
        "missing_qpy": len(missing_hashes),
        "size_threshold": size_threshold,
        "split_quantile": args.split_quantile,
        "profile_counts": selected["size_profile"].value_counts().to_dict(),
        "manifest_csv": str(manifest_csv),
        "hashes_file": str(hashes_file),
        "qpy_list": str(qpy_list),
        "missing_file": str(missing_file),
        "profile_tunings": str(tunings_file),
        "results_csv": str(out_csv),
        "timeout_policy": args.timeout_policy,
        "sqlite_timeout_seconds": args.sqlite_timeout_seconds,
        "timeout_seconds": args.timeout_seconds,
        "timeout_multiplier": args.timeout_multiplier,
        "timeout_floor_seconds": args.timeout_floor_seconds,
        "dynamic_timeout_min_s": float(selected["engine_timeout_s"].min()),
        "dynamic_timeout_median_s": float(selected["engine_timeout_s"].median()),
        "dynamic_timeout_max_s": float(selected["engine_timeout_s"].max()),
    }
    summary_file.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(
        f"[prepare] selected={len(wanted_hashes)} found_qpy={len(found_paths)} "
        f"missing_qpy={len(missing_hashes)} size_threshold={size_threshold}",
        file=sys.stderr,
    )
    print(f"[prepare] profile_counts={summary['profile_counts']}", file=sys.stderr)
    print(f"[prepare] manifest={manifest_csv}", file=sys.stderr)
    print(f"[prepare] qpy_list={qpy_list}", file=sys.stderr)
    print(f"[prepare] results={out_csv}", file=sys.stderr)
    if missing_hashes:
        print(f"[prepare] missing={missing_file}", file=sys.stderr)
        if args.require_all:
            raise SystemExit("not all selected circuits were found locally")
    if args.prepare_only:
        return 0
    if not found_paths:
        raise SystemExit("no selected QPY files were found locally")
    if args.dry_run:
        print("[dry-run] not executing engines", file=sys.stderr)
        return 0

    seen = {} if args.no_resume else read_seen(out_csv)
    write_header = not out_csv.exists() or out_csv.stat().st_size == 0
    labels = [f"warmup{i}" for i in range(args.warmup)] + [str(i) for i in range(args.n_runs)]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=runner.CSV_FIELDS)
        if write_header:
            writer.writeheader()

        for idx, qpy_path in enumerate(found_paths, 1):
            circuit_hash = qpy_path.stem
            profile = profile_by_hash[circuit_hash]
            parquet_size = circuit_size_by_hash[circuit_hash]
            expected_keys = [
                (circuit_hash, engine, profile, run_idx)
                for engine in engines
                for run_idx in labels
            ]
            if expected_keys and all(is_complete_status(seen.get(key)) for key in expected_keys):
                if idx == 1 or idx % 100 == 0:
                    print(
                        f"[{idx}/{len(found_paths)}] {circuit_hash[:8]} already complete; skipping",
                        file=sys.stderr,
                    )
                continue
            dynamic_timeout_s = float(timeout_by_hash[circuit_hash])
            baseline_min_timeout_s = max(
                args.timeout_floor_seconds,
                dynamic_timeout_s * args.timeout_multiplier,
            )
            sqlite_timeout_s = (
                baseline_min_timeout_s
                if args.timeout_policy == "baseline_min"
                else args.sqlite_timeout_seconds
            )
            engine_timeout_s = (
                baseline_min_timeout_s
                if args.timeout_policy == "baseline_min"
                else args.timeout_seconds
            )
            print(
                f"[{idx}/{len(found_paths)}] {circuit_hash[:8]} "
                f"profile={profile} parquet_circuit_size={parquet_size} "
                f"threshold={dynamic_timeout_s:.6g}s timeout={engine_timeout_s:.6g}s",
                file=sys.stderr,
            )
            try:
                qc = runner.load_qpy(qpy_path)
                query, num_qubits, num_gates, query_gen_s = runner.build_iqs_query_with_timeout(
                    qc, args.query_timeout_seconds
                )
                shape = runner.query_shape(query)
                print(
                    f"    query={len(query)} bytes ctes={shape.total_ctes} "
                    f"tensors={shape.tensor_ctes} contractions={shape.contraction_ctes}",
                    file=sys.stderr,
                )
            except Exception as e:
                write_result_row(
                    writer,
                    circuit_hash=circuit_hash,
                    qpy_path=qpy_path,
                    num_qubits=getattr(locals().get("qc", None), "num_qubits", ""),
                    num_gates=getattr(locals().get("qc", None), "size", lambda: "")(),
                    query_gen_s="",
                    query=None,
                    shape=None,
                    engine="",
                    profile=profile,
                    run_idx="",
                    status="query_error",
                    error_msg=f"{e}\n{traceback.format_exc(limit=4)}",
                )
                f.flush()
                continue

            for run_idx in labels:
                key = (circuit_hash, "sqlite", profile, run_idx)
                if is_complete_status(seen.get(key)):
                    continue
                sqlite_result = run_engine_once(
                    query=query,
                    engine="sqlite",
                    profile=profile,
                    run_idx=run_idx,
                    tuning=tunings[profile]["sqlite"],
                    timeout_s=sqlite_timeout_s,
                    fetch_chunk_size=args.fetch_chunk_size,
                )
                write_result_row(
                    writer,
                    circuit_hash=circuit_hash,
                    qpy_path=qpy_path,
                    num_qubits=num_qubits,
                    num_gates=num_gates,
                    query_gen_s=query_gen_s,
                    query=query,
                    shape=shape,
                    engine="sqlite",
                    profile=profile,
                    run_idx=run_idx,
                    status=sqlite_result["status"],
                    rows_consumed=sqlite_result["rows_consumed"],
                    wall_time_s=sqlite_result["wall_time_s"],
                    tracemalloc_peak_bytes=sqlite_result["tracemalloc_peak_bytes"],
                    tuning=tunings[profile]["sqlite"],
                    error_msg=sqlite_result["error_msg"],
                )
                f.flush()
                seen[key] = sqlite_result["status"]

            for engine in engines:
                if engine == "sqlite":
                    continue
                for run_idx in labels:
                    key = (circuit_hash, engine, profile, run_idx)
                    if is_complete_status(seen.get(key)):
                        continue
                    result = run_engine_once(
                        query=query,
                        engine=engine,
                        profile=profile,
                        run_idx=run_idx,
                        tuning=tunings[profile][engine],
                        timeout_s=engine_timeout_s,
                        fetch_chunk_size=args.fetch_chunk_size,
                    )
                    write_result_row(
                        writer,
                        circuit_hash=circuit_hash,
                        qpy_path=qpy_path,
                        num_qubits=num_qubits,
                        num_gates=num_gates,
                        query_gen_s=query_gen_s,
                        query=query,
                        shape=shape,
                        engine=engine,
                        profile=profile,
                        run_idx=run_idx,
                        status=result["status"],
                        rows_consumed=result["rows_consumed"],
                        wall_time_s=result["wall_time_s"],
                        tracemalloc_peak_bytes=result["tracemalloc_peak_bytes"],
                        tuning=tunings[profile][engine],
                        error_msg=result["error_msg"],
                    )
                    f.flush()
                    seen[key] = result["status"]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
