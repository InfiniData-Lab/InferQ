#!/usr/bin/env python3
"""
Run deep SQLite-vs-Qiskit benchmarking for a parquet-selected dataset.

Default target:
    analysis/training_data/rdbms_all_methods_training_data.parquet

Outputs are incremental so the run can be resumed:
    analysis/deep_benchmark_162/sqlite_vs_qiskit_results.jsonl
    analysis/deep_benchmark_162/sqlite_vs_qiskit_summary.csv
    analysis/deep_benchmark_162/missing_hashes.txt
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import qiskit.qpy

from experiments.analysis import deep_benchmark as deep
from inferq import paths

DEFAULT_DATASET = paths.dataset("training") / "rdbms_all_methods_training_data.parquet"
DEFAULT_OUT_DIR = paths.out_dir() / "deep_benchmark_162"
DEFAULT_QPY_ROOTS = [
    paths.out_dir() / "finetuned_rdbms_162" / "qpy",
    paths.out_dir() / "finetuned_rdbms_116" / "qpy",
    paths.circuits_dir(),
    paths.data_dir() / "extremes",
    paths.data_dir() / "downloaded_circuits",
]
DEFAULT_AER_METHODS = [
    "statevector",
    "stabilizer",
    "density_matrix",
    "matrix_product_state",
    "extended_stabilizer",
    "unitary",
    "automatic",
]


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Not serialisable: {type(value)}")


def load_qpy(path: Path):
    with path.open("rb") as f:
        loaded = qiskit.qpy.load(f)
    return loaded[0] if isinstance(loaded, list) else loaded


def index_qpy_files(roots: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.qpy")):
            found.setdefault(path.stem, path.resolve())
    return found


def read_completed_hashes(jsonl_path: Path) -> set[str]:
    completed: set[str] = set()
    if not jsonl_path.exists():
        return completed
    with jsonl_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            circuit_hash = row.get("circuit_hash")
            if circuit_hash:
                completed.add(str(circuit_hash))
    return completed


def finite(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def best_aer_result(aer_rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    ok_rows = [r for r in aer_rows if r.get("success") and finite(r.get("wall_s")) is not None]
    if not ok_rows:
        return None, None
    best_time = min(ok_rows, key=lambda r: float(r["wall_s"]))
    best_rss = min(ok_rows, key=lambda r: int(r["peak_rss_bytes"]))
    return best_time, best_rss


def append_summary(csv_path: Path, circuit_hash: str, meta: dict[str, Any], result: dict[str, Any]) -> None:
    sqlite = result.get("sqlite", {})
    aer_rows = result.get("aer", [])
    best_time, best_rss = best_aer_result(aer_rows)
    row = {
        "circuit_hash": circuit_hash,
        "qpy_path": result.get("qpy_path"),
        "num_qubits": meta.get("num_qubits"),
        "depth": meta.get("depth"),
        "circuit_size": meta.get("circuit_size"),
        "sqlite_success": sqlite.get("success"),
        "sqlite_wall_s": sqlite.get("wall_s"),
        "sqlite_peak_rss_bytes": sqlite.get("peak_rss_bytes"),
        "sqlite_pagecache_overflow_bytes": sqlite.get("pagecache_overflow_bytes"),
        "sqlite_total_cte_count": sqlite.get("total_cte_count"),
        "sqlite_contraction_cte_count": sqlite.get("contraction_cte_count"),
        "best_qiskit_time_method": best_time.get("method") if best_time else None,
        "best_qiskit_time_mode": best_time.get("mode") if best_time else None,
        "best_qiskit_wall_s": best_time.get("wall_s") if best_time else None,
        "best_qiskit_rss_method": best_rss.get("method") if best_rss else None,
        "best_qiskit_rss_mode": best_rss.get("mode") if best_rss else None,
        "best_qiskit_peak_rss_bytes": best_rss.get("peak_rss_bytes") if best_rss else None,
        "successful_qiskit_runs": sum(1 for r in aer_rows if r.get("success")),
        "failed_qiskit_runs": sum(1 for r in aer_rows if not r.get("success")),
    }
    exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for line in lines:
            f.write(f"{line}\n")


def run_one(
    circuit_hash: str,
    qpy_path: Path,
    meta: dict[str, Any],
    log_dir: Path,
    verbose_deep: bool,
) -> dict[str, Any]:
    qc = load_qpy(qpy_path)
    print(
        f"\n{'=' * 80}\n"
        f"{circuit_hash}  ({qc.num_qubits} qubits, depth {qc.depth()})\n"
        f"{'=' * 80}",
        flush=True,
    )
    result: dict[str, Any] = {
        "circuit_hash": circuit_hash,
        "qpy_path": str(qpy_path),
        "metadata": meta,
        "sqlite": None,
        "aer": [],
    }

    log_path = log_dir / f"{circuit_hash}.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = None if verbose_deep else log_path.open("w")
    stdout_context = contextlib.nullcontext() if verbose_deep else contextlib.redirect_stdout(log_file)
    try:
        with stdout_context:
            try:
                iqs_qc = deep.qiskit_to_iqs(qc)
                result["sqlite"] = deep.sqlite_deep_run(iqs_qc, circuit_hash)
            except Exception as exc:
                print(f"  [ERROR] SQLite path for {circuit_hash}: {exc}", flush=True)
                traceback.print_exc()
                result["sqlite"] = {"success": False, "error": str(exc)}

            try:
                result["aer"] = deep.aer_deep_run(qc, circuit_hash)
            except Exception as exc:
                print(f"  [ERROR] Aer path for {circuit_hash}: {exc}", flush=True)
                traceback.print_exc()
                result["aer"] = []
    finally:
        if log_file is not None:
            log_file.close()

    if not verbose_deep:
        result["log_path"] = str(log_path)

    return result


def run_one_in_subprocess(
    circuit_hash: str,
    qpy_path: Path,
    meta: dict[str, Any],
    out_dir: Path,
    methods: list[str],
    timeout_seconds: int,
    heartbeat_seconds: int,
    verbose_deep: bool,
) -> dict[str, Any]:
    worker_dir = out_dir / "worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    meta_path = worker_dir / f"{circuit_hash}.meta.json"
    result_path = worker_dir / f"{circuit_hash}.result.json"
    driver_log_path = out_dir / "logs" / f"{circuit_hash}.driver.log"
    driver_log_path.parent.mkdir(parents=True, exist_ok=True)

    with meta_path.open("w") as f:
        json.dump(meta, f, default=_json_default)

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--worker-hash", circuit_hash,
        "--worker-qpy", str(qpy_path),
        "--worker-meta-json", str(meta_path),
        "--worker-result-json", str(result_path),
        "--out-dir", str(out_dir),
        "--aer-methods", ",".join(methods),
    ]
    if verbose_deep:
        cmd.append("--verbose-deep")

    timeout_result = {
        "circuit_hash": circuit_hash,
        "qpy_path": str(qpy_path),
        "metadata": meta,
        "log_path": str(out_dir / "logs" / f"{circuit_hash}.log"),
        "driver_log_path": str(driver_log_path),
        "sqlite": {
            "success": False,
            "status": "timeout",
            "error": f"circuit timed out after {timeout_seconds}s",
        },
        "aer": [],
    }

    with driver_log_path.open("w") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        next_heartbeat = started + max(1, heartbeat_seconds)
        while True:
            rc = proc.poll()
            if rc is not None:
                break

            now = time.monotonic()
            elapsed = int(now - started)
            if elapsed >= timeout_seconds:
                print(
                    f"  timeout: {circuit_hash} after {elapsed}s; killing worker pid={proc.pid}",
                    flush=True,
                )
                proc.kill()
                proc.wait()
                return timeout_result

            if now >= next_heartbeat:
                remaining = max(0, timeout_seconds - elapsed)
                print(
                    f"  still running {circuit_hash}: elapsed={elapsed}s remaining={remaining}s pid={proc.pid}",
                    flush=True,
                )
                next_heartbeat = now + max(1, heartbeat_seconds)

            time.sleep(1.0)

    if not result_path.exists():
        return {
            "circuit_hash": circuit_hash,
            "qpy_path": str(qpy_path),
            "metadata": meta,
            "driver_log_path": str(driver_log_path),
            "sqlite": {
                "success": False,
                "status": "worker_failed",
                "error": "worker exited without writing result JSON",
            },
            "aer": [],
        }

    with result_path.open() as f:
        result = json.load(f)
    result["driver_log_path"] = str(driver_log_path)
    return result


def worker_main(args: argparse.Namespace) -> None:
    methods = [m.strip() for m in args.aer_methods.split(",") if m.strip()]
    deep.AER_METHODS[:] = methods
    with args.worker_meta_json.open() as f:
        meta = json.load(f)
    result = run_one(
        args.worker_hash,
        args.worker_qpy,
        meta,
        args.out_dir / "logs",
        args.verbose_deep,
    )
    with args.worker_result_json.open("w") as f:
        json.dump(result, f, default=_json_default)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deep benchmark SQLite against Qiskit Aer for a parquet dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qpy-root", type=Path, action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verbose-deep", action="store_true")
    parser.add_argument("--circuit-timeout-seconds", type=int, default=1800)
    parser.add_argument("--heartbeat-seconds", type=int, default=30)
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-hash", help=argparse.SUPPRESS)
    parser.add_argument("--worker-qpy", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-meta-json", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-result-json", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--aer-methods",
        default=",".join(DEFAULT_AER_METHODS),
        help="Comma-separated Qiskit Aer methods to run.",
    )
    args = parser.parse_args()

    if args.worker:
        worker_main(args)
        return

    qpy_roots = args.qpy_root or DEFAULT_QPY_ROOTS
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "sqlite_vs_qiskit_results.jsonl"
    summary_csv = out_dir / "sqlite_vs_qiskit_summary.csv"
    missing_path = out_dir / "missing_hashes.txt"
    log_dir = out_dir / "logs"

    df = pd.read_parquet(args.dataset).drop_duplicates("RowKey", keep="first").sort_values("RowKey")
    if args.limit is not None:
        df = df.head(args.limit).copy()

    qpy_index = index_qpy_files(qpy_roots)
    wanted = [str(v) for v in df["RowKey"]]
    missing = [h for h in wanted if h not in qpy_index]
    found = [h for h in wanted if h in qpy_index]
    write_lines(missing_path, missing)

    completed = read_completed_hashes(jsonl_path) if args.resume else set()
    methods = [m.strip() for m in args.aer_methods.split(",") if m.strip()]
    deep.AER_METHODS[:] = methods

    print(f"dataset={args.dataset}")
    print(f"rows={len(wanted)} found_qpy={len(found)} missing_qpy={len(missing)}")
    print(f"qpy_roots={', '.join(str(p) for p in qpy_roots)}")
    print(f"aer_methods={methods}")
    print(f"circuit_timeout_seconds={args.circuit_timeout_seconds}")
    print(f"heartbeat_seconds={args.heartbeat_seconds}")
    print(f"out_jsonl={jsonl_path}")
    print(f"out_summary={summary_csv}")
    if missing:
        print(f"missing_hashes={missing_path}")
    if completed:
        print(f"resume: skipping {len(completed)} completed circuits")

    rows_by_hash = {str(row["RowKey"]): row.to_dict() for _, row in df.iterrows()}
    with jsonl_path.open("a") as jsonl:
        for idx, circuit_hash in enumerate(found, 1):
            if circuit_hash in completed:
                continue
            print(f"\n[{idx}/{len(found)}] {circuit_hash}", flush=True)
            if args.in_process:
                result = run_one(
                    circuit_hash,
                    qpy_index[circuit_hash],
                    rows_by_hash[circuit_hash],
                    log_dir,
                    args.verbose_deep,
                )
            else:
                result = run_one_in_subprocess(
                    circuit_hash,
                    qpy_index[circuit_hash],
                    rows_by_hash[circuit_hash],
                    out_dir,
                    methods,
                    args.circuit_timeout_seconds,
                    args.heartbeat_seconds,
                    args.verbose_deep,
                )
            jsonl.write(json.dumps(result, default=_json_default) + "\n")
            jsonl.flush()
            append_summary(summary_csv, circuit_hash, rows_by_hash[circuit_hash], result)

    print("\nDone.")
    print(f"Results: {jsonl_path}")
    print(f"Summary: {summary_csv}")
    print(f"Missing hashes: {missing_path} ({len(missing)})")


if __name__ == "__main__":
    main()
