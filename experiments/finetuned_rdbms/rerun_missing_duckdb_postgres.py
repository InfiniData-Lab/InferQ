#!/usr/bin/env python3
"""Rerun DuckDB/Postgres timing for circuits that are missing it.

This is a focused backfill runner. Unlike ``run_full_7705_two_profile.py`` it:

* reads a *self-contained manifest CSV* (default
  ``missing_duckdb_postgres.csv`` next to this script) instead of the training
  parquet, so the box where it runs needs only this file plus the local ``.qpy``
  circuits -- no metadata parquets required;
* runs *only* DuckDB and Postgres, and for each circuit only the engine(s) the
  manifest marks as missing;
* applies the size-based finetuned tunings (``small_size`` for
  ``circuit_size <= --size-threshold``, ``large_size`` otherwise);
* times out each engine run at the circuit's SQLite baseline time
  (``--timeout-policy sqlite_only``), which is carried in the manifest.

The manifest is produced from ``rdbms_training_data.parquet`` and has columns::

    RowKey,num_qubits,circuit_size,need_duckdb,need_postgres,sqlite_time_s,best_qiskit_time_s

``need_duckdb`` / ``need_postgres`` are 0/1 flags; ``sqlite_time_s`` may be blank
(then the per-engine timeout falls back to ``--timeout-seconds``).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from experiments.finetuned_rdbms import run_finetuned_rdbms as runner
from experiments.finetuned_rdbms import run_full_7705_two_profile as twoprof
from inferq import paths

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = THIS_DIR / "missing_duckdb_postgres.csv"
SUPPORTED_ENGINES = ("duckdb", "postgres")


def parse_flag(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"RowKey", "circuit_size", "need_duckdb", "need_postgres"}
        missing_cols = required - set(reader.fieldnames or [])
        if missing_cols:
            raise SystemExit(f"manifest {path} is missing columns: {sorted(missing_cols)}")
        for raw in reader:
            row_key = twoprof.normalize_hash(raw["RowKey"])
            if not row_key or row_key in seen:
                continue
            seen.add(row_key)
            rows.append({
                "RowKey": row_key,
                "num_qubits": raw.get("num_qubits", ""),
                "circuit_size": float(raw["circuit_size"]),
                "need_duckdb": parse_flag(raw["need_duckdb"]),
                "need_postgres": parse_flag(raw["need_postgres"]),
                "sqlite_time_s": twoprof.finite_positive_float(raw.get("sqlite_time_s")),
            })
    rows.sort(key=lambda r: r["RowKey"])
    return rows


def engine_timeout(
    policy: str,
    sqlite_time_s: float | None,
    *,
    multiplier: float,
    floor_s: float,
    static_seconds: float,
) -> float:
    if policy == "sqlite_only" and sqlite_time_s is not None:
        return max(floor_s, sqlite_time_s * multiplier)
    return float(static_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                        help="Self-contained CSV of circuits missing DuckDB/Postgres timing.")
    parser.add_argument("--qpy-root", type=Path, action="append",
                        help="Directory searched recursively for <hash>.qpy. Repeatable.")
    parser.add_argument("--out-dir", type=Path,
                        default=paths.out_dir() / "rerun_missing_duckdb_postgres")
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--profile-tunings", type=Path, default=None,
                        help="Optional JSON overriding small_size/large_size engine tunings.")
    parser.add_argument("--size-threshold", type=float, default=33.0,
                        help="small_size for circuit_size <= threshold, else large_size.")
    parser.add_argument("--engines", default="duckdb,postgres",
                        help="Subset of duckdb,postgres to run.")
    parser.add_argument("--timeout-policy", choices=("sqlite_only", "static"),
                        default="sqlite_only",
                        help="sqlite_only uses each circuit's SQLite baseline time as the timeout.")
    parser.add_argument("--timeout-seconds", type=float, default=120.0,
                        help="Timeout for --timeout-policy static, and fallback when SQLite time is absent.")
    parser.add_argument("--timeout-multiplier", type=float, default=1.0,
                        help="Multiplier applied to the SQLite baseline timeout.")
    parser.add_argument("--timeout-floor-seconds", type=float, default=0.0,
                        help="Minimum timeout under --timeout-policy sqlite_only.")
    parser.add_argument("--timing-scope", choices=("full", "contraction"), default="contraction",
                        help="full times setup plus execution; contraction times only execute/fetch.")
    parser.add_argument("--query-timeout-seconds", type=int, default=300)
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--fetch-chunk-size", type=int, default=8192)
    parser.add_argument("--tmp-root", type=Path, default=None)
    parser.add_argument("--require-all", action="store_true",
                        help="Fail if any selected circuit has no local QPY file.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    invalid = sorted(set(engines) - set(SUPPORTED_ENGINES))
    if invalid:
        raise SystemExit(f"unsupported engines (only duckdb,postgres allowed): {invalid}")
    if not engines:
        raise SystemExit("no engines selected")
    if args.timeout_multiplier <= 0.0:
        raise SystemExit("--timeout-multiplier must be positive")
    if args.timeout_floor_seconds < 0.0:
        raise SystemExit("--timeout-floor-seconds must be non-negative")
    if args.num_shards < 1:
        raise SystemExit("--num-shards must be >= 1")
    if not 0 <= args.shard_index < args.num_shards:
        raise SystemExit("--shard-index must satisfy 0 <= shard-index < num-shards")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_csv or (out_dir / "results.csv")
    tmp_root = args.tmp_root or (out_dir / "tmp")
    qpy_roots = args.qpy_root or [
        paths.out_dir() / "finetuned_rdbms_7705" / "qpy",
        paths.out_dir() / "finetuned_rdbms_162" / "qpy",
        paths.out_dir() / "finetuned_rdbms_116" / "qpy",
        paths.circuits_dir(),
        paths.data_dir() / "extremes",
    ]

    manifest_rows = load_manifest(args.manifest)
    # Keep only circuits that still need at least one of the requested engines.
    selected = [
        r for r in manifest_rows
        if (r["need_duckdb"] and "duckdb" in engines)
        or (r["need_postgres"] and "postgres" in engines)
    ]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        raise SystemExit("no circuits in the manifest need the requested engines")

    by_hash = {r["RowKey"]: r for r in selected}
    for r in selected:
        r["size_profile"] = (
            "small_size" if r["circuit_size"] <= args.size_threshold else "large_size"
        )

    qpy_index = twoprof.index_qpy_files(qpy_roots)
    wanted_hashes = [r["RowKey"] for r in selected]
    all_found_paths = [qpy_index[h] for h in wanted_hashes if h in qpy_index]
    found_paths = [
        path for i, path in enumerate(all_found_paths)
        if i % args.num_shards == args.shard_index
    ]
    missing_hashes = [h for h in wanted_hashes if h not in qpy_index]

    tunings = twoprof.load_profile_tunings(args.profile_tunings, tmp_root)

    hashes_file = out_dir / "selected_hashes.txt"
    qpy_list = out_dir / "found_qpy_paths.txt"
    missing_file = out_dir / "missing_hashes.txt"
    tunings_file = out_dir / "profile_tunings.json"
    summary_file = out_dir / "selection_summary.json"
    manifest_echo = out_dir / "selected_manifest.csv"

    twoprof.write_lines(hashes_file, wanted_hashes)
    twoprof.write_lines(qpy_list, [str(p) for p in found_paths])
    twoprof.write_lines(missing_file, missing_hashes)
    tunings_file.write_text(json.dumps(tunings, indent=2, sort_keys=True) + "\n")
    with manifest_echo.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["RowKey", "num_qubits", "circuit_size", "size_profile",
                    "need_duckdb", "need_postgres", "sqlite_time_s"])
        for r in selected:
            w.writerow([r["RowKey"], r["num_qubits"], r["circuit_size"], r["size_profile"],
                        int(r["need_duckdb"]), int(r["need_postgres"]),
                        "" if r["sqlite_time_s"] is None else r["sqlite_time_s"]])

    profile_counts: dict[str, int] = {}
    for r in selected:
        profile_counts[r["size_profile"]] = profile_counts.get(r["size_profile"], 0) + 1
    summary = {
        "manifest": str(args.manifest),
        "selected_circuits": len(wanted_hashes),
        "need_duckdb": sum(1 for r in selected if r["need_duckdb"] and "duckdb" in engines),
        "need_postgres": sum(1 for r in selected if r["need_postgres"] and "postgres" in engines),
        "engines": engines,
        "qpy_roots": [str(p) for p in qpy_roots],
        "total_found_qpy": len(all_found_paths),
        "found_qpy": len(found_paths),
        "missing_qpy": len(missing_hashes),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "size_threshold": args.size_threshold,
        "profile_counts": profile_counts,
        "timeout_policy": args.timeout_policy,
        "timeout_seconds": args.timeout_seconds,
        "timeout_multiplier": args.timeout_multiplier,
        "timeout_floor_seconds": args.timeout_floor_seconds,
        "timing_scope": args.timing_scope,
        "results_csv": str(out_csv),
        "manifest_echo": str(manifest_echo),
    }
    summary_file.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(
        f"[prepare] selected={len(wanted_hashes)} found_qpy={len(found_paths)} "
        f"missing_qpy={len(missing_hashes)} size_threshold={args.size_threshold} "
        f"shard={args.shard_index}/{args.num_shards}",
        file=sys.stderr,
    )
    print(f"[prepare] profile_counts={profile_counts} engines={engines}", file=sys.stderr)
    print(f"[prepare] results={out_csv}", file=sys.stderr)
    if missing_hashes:
        print(f"[prepare] missing={missing_file} ({len(missing_hashes)} hashes)", file=sys.stderr)
        if args.require_all:
            raise SystemExit("not all selected circuits were found locally")
    if args.prepare_only:
        return 0
    if not found_paths:
        raise SystemExit("no selected QPY files were found locally")
    if args.dry_run:
        print("[dry-run] not executing engines", file=sys.stderr)
        return 0

    seen = {} if args.no_resume else twoprof.read_seen(out_csv)
    write_header = not out_csv.exists() or out_csv.stat().st_size == 0
    labels = [f"warmup{i}" for i in range(args.warmup)] + [str(i) for i in range(args.n_runs)]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=runner.CSV_FIELDS)
        if write_header:
            writer.writeheader()

        for idx, qpy_path in enumerate(found_paths, 1):
            circuit_hash = qpy_path.stem
            row = by_hash[circuit_hash]
            profile = row["size_profile"]
            engines_to_run = [
                e for e in engines
                if (e == "duckdb" and row["need_duckdb"])
                or (e == "postgres" and row["need_postgres"])
            ]
            if not engines_to_run:
                continue

            expected_keys = [
                (circuit_hash, engine, profile, run_idx)
                for engine in engines_to_run
                for run_idx in labels
            ]
            if expected_keys and all(twoprof.is_complete_status(seen.get(k)) for k in expected_keys):
                if idx == 1 or idx % 100 == 0:
                    print(f"[{idx}/{len(found_paths)}] {circuit_hash[:8]} already complete; skipping",
                          file=sys.stderr)
                continue

            timeout_s = engine_timeout(
                args.timeout_policy,
                row["sqlite_time_s"],
                multiplier=args.timeout_multiplier,
                floor_s=args.timeout_floor_seconds,
                static_seconds=args.timeout_seconds,
            )
            print(
                f"[{idx}/{len(found_paths)}] {circuit_hash[:8]} profile={profile} "
                f"circuit_size={row['circuit_size']:.0f} engines={engines_to_run} "
                f"timeout={timeout_s:.6g}s",
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
                twoprof.write_result_row(
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

            for engine in engines_to_run:
                for run_idx in labels:
                    key = (circuit_hash, engine, profile, run_idx)
                    if twoprof.is_complete_status(seen.get(key)):
                        continue
                    result = twoprof.run_engine_once(
                        query=query,
                        engine=engine,
                        profile=profile,
                        run_idx=run_idx,
                        tuning=tunings[profile][engine],
                        timeout_s=timeout_s,
                        timing_scope=args.timing_scope,
                        fetch_chunk_size=args.fetch_chunk_size,
                    )
                    twoprof.write_result_row(
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
