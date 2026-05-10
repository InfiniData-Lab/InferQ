#!/usr/bin/env python3
"""Run the fine-tuned RDBMS benchmark on the 116 all-engine baseline circuits.

The 116-circuit set is selected from rdbms_training_data.parquet by requiring
non-null DuckDB, SQLite, and PostgreSQL baseline times. This script writes a
manifest for the full set, discovers matching .qpy files under local roots, and
then invokes run_finetuned_rdbms.py on the discovered circuits.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "InferQ").is_dir() and (parent / "Infinidata-rdbms-simulator").is_dir():
            return parent
    raise RuntimeError(f"could not find repo root from {start}")


REPO_ROOT = find_repo_root(Path(__file__).resolve())
INFERQ_ROOT = REPO_ROOT / "InferQ"
THIS_DIR = Path(__file__).resolve().parent
RUNNER = THIS_DIR / "run_finetuned_rdbms.py"

BASELINE_TIME_COLS = [
    "rdbms_ducksql_time_s",
    "rdbms_sqlite_time_s",
    "rdbms_psql_time_s",
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
]


def select_all_engine_baselines(parquet_path: Path):
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    missing_cols = [c for c in BASELINE_TIME_COLS if c not in df.columns]
    if missing_cols:
        raise SystemExit(f"{parquet_path} is missing columns: {missing_cols}")
    selected = df[df[BASELINE_TIME_COLS].notna().all(axis=1)].copy()
    selected = selected.sort_values("RowKey")
    return selected


def index_qpy_files(roots: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.qpy")):
            found.setdefault(path.stem, path.resolve())
    return found


def write_text_lines(path: Path, lines) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for line in lines:
            f.write(f"{line}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path,
                        default=INFERQ_ROOT / "analysis" / "training_data" / "rdbms_training_data.parquet")
    parser.add_argument("--qpy-root", type=Path, action="append",
                        help="Directory to search recursively for .qpy files. Can be repeated.")
    parser.add_argument("--out-dir", type=Path,
                        default=INFERQ_ROOT / "analysis" / "finetuned_rdbms_116")
    parser.add_argument("--engines", default="duckdb,sqlite,postgres")
    parser.add_argument("--profile", choices=("balanced", "fast", "spill_safe"), default="balanced")
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--query-timeout-seconds", type=int, default=300)
    parser.add_argument("--fetch-chunk-size", type=int, default=8192)
    parser.add_argument("--tmp-root", type=Path, default=None)
    parser.add_argument("--require-all", action="store_true",
                        help="Fail instead of running a partial local subset when some hashes are missing.")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Only write manifests and command files; do not invoke the runner.")
    parser.add_argument("--runner-dry-run", action="store_true",
                        help="Invoke the runner with --dry-run after preparing manifests.")
    parser.add_argument("--no-resume", action="store_true",
                        help="Do not pass --resume to the runner.")
    args = parser.parse_args()

    qpy_roots = args.qpy_root or [INFERQ_ROOT / "circuits", INFERQ_ROOT / "data" / "extremes"]
    tmp_root = args.tmp_root or (args.out_dir / "tmp")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    selected = select_all_engine_baselines(args.parquet)
    manifest_cols = [c for c in MANIFEST_COLS if c in selected.columns]
    full_manifest = args.out_dir / "all_116_manifest.csv"
    selected[manifest_cols].to_csv(full_manifest, index=False)

    wanted_hashes = [str(x) for x in selected["RowKey"]]
    qpy_index = index_qpy_files(qpy_roots)
    found_paths = [qpy_index[h] for h in wanted_hashes if h in qpy_index]
    missing_hashes = [h for h in wanted_hashes if h not in qpy_index]

    hashes_file = args.out_dir / "all_116_hashes.txt"
    qpy_list = args.out_dir / "found_qpy_paths.txt"
    missing_file = args.out_dir / "missing_hashes.txt"
    results_csv = args.out_dir / f"results_{args.profile}.csv"
    command_file = args.out_dir / "runner_command.txt"
    summary_file = args.out_dir / "selection_summary.json"

    write_text_lines(hashes_file, wanted_hashes)
    write_text_lines(qpy_list, [str(p) for p in found_paths])
    write_text_lines(missing_file, missing_hashes)

    summary = {
        "parquet": str(args.parquet),
        "selected_hashes": len(wanted_hashes),
        "qpy_roots": [str(p) for p in qpy_roots],
        "found_qpy": len(found_paths),
        "missing_qpy": len(missing_hashes),
        "full_manifest": str(full_manifest),
        "hashes_file": str(hashes_file),
        "qpy_list": str(qpy_list),
        "missing_file": str(missing_file),
        "results_csv": str(results_csv),
    }
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")

    print(
        f"[prepare] selected={len(wanted_hashes)} found_qpy={len(found_paths)} "
        f"missing_qpy={len(missing_hashes)}",
        file=sys.stderr,
    )
    print(f"[prepare] manifest={full_manifest}", file=sys.stderr)
    print(f"[prepare] qpy_list={qpy_list}", file=sys.stderr)
    if missing_hashes:
        print(f"[prepare] missing={missing_file}", file=sys.stderr)
        if args.require_all:
            raise SystemExit("not all 116 selected circuits were found locally")
    if not found_paths and not args.prepare_only:
        raise SystemExit("no selected .qpy files were found locally")

    cmd = [
        sys.executable,
        str(RUNNER),
        "--qpy-list",
        str(qpy_list),
        "--out-csv",
        str(results_csv),
        "--engines",
        args.engines,
        "--profile",
        args.profile,
        "--n-runs",
        str(args.n_runs),
        "--warmup",
        str(args.warmup),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--query-timeout-seconds",
        str(args.query_timeout_seconds),
        "--fetch-chunk-size",
        str(args.fetch_chunk_size),
        "--tmp-root",
        str(tmp_root),
    ]
    if not args.no_resume:
        cmd.append("--resume")
    if args.runner_dry_run:
        cmd.append("--dry-run")

    command_file.write_text(" ".join(cmd) + "\n")
    print(f"[prepare] command={command_file}", file=sys.stderr)

    if args.prepare_only:
        return 0
    return subprocess.call(cmd, cwd=REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
