"""SQLite CTE-prefix study for out-of-core diagnosis.

Runs checkpoint prefixes of one IQS query under SQLite and writes:

  circuit_hash,qubits,checkpoint_cte,budget_gb,runtime_s,peak_rss_mb,write_mb,plan_note

The goal is to locate the contraction step where runtime/write volume jumps,
then inspect SQLite's plan around that point.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import resource
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from experiments.ooc.worker import (
    _build_iqs_query_with_timeout,
    _load_qiskit_circuit,
    _TempDirSampler,
)
from inferq import paths
from inferq.sql.query_modes import split_iqs_query_per_step

FIELDS = [
    "circuit_hash", "qubits", "checkpoint_cte", "budget_gb", "runtime_s",
    "peak_rss_mb", "write_mb", "plan_note",
]

CREATE_TABLE_RE = re.compile(r"\s*CREATE\s+(?:TEMP\s+)?TABLE\s+([^\s]+)\s+AS\s+", re.IGNORECASE)


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes. The benchmark containers are Linux,
    # but this keeps local smoke tests readable.
    return usage / (1024 * 1024) if usage > 10_000_000 else usage / 1024


def _plan_note(cur: sqlite3.Cursor, sql: str) -> str:
    try:
        rows = cur.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    except sqlite3.Error as e:
        return f"explain_failed: {e}"
    details = " | ".join(str(r[-1]) for r in rows)
    flags = []
    upper = details.upper()
    if "TEMP B-TREE" in upper:
        flags.append("TEMP B-TREE")
    if "AUTOMATIC" in upper:
        flags.append("AUTOMATIC INDEX")
    return "; ".join(flags) if flags else details[:400]


def _run_checkpoint(
    statements: list[str],
    checkpoint: int,
    args: argparse.Namespace,
    circuit_hash: str,
    qubits: int,
) -> dict:
    tmp_dir = Path(args.tmp_root) / f"prefix_sqlite_{os.getpid()}_{checkpoint}"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SQLITE_TMPDIR"] = str(tmp_dir)
    os.environ["TMPDIR"] = str(tmp_dir)

    db_path = tmp_dir / "prefix.db"
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    sampler = _TempDirSampler(tmp_dir, interval_s=0.25)
    sampler.start()
    tic = time.perf_counter()
    plan = ""
    try:
        cur.execute(f"PRAGMA cache_size = -{args.sqlite_cache_mb * 1024}")
        cur.execute("PRAGMA temp_store = FILE")
        cur.execute("PRAGMA cache_spill = ON")
        try:
            cur.execute(f"PRAGMA temp_store_directory = '{tmp_dir}'")
        except sqlite3.OperationalError:
            pass
        cur.execute("PRAGMA mmap_size = 0")

        if checkpoint >= len(statements):
            for stmt in statements:
                cur.execute(stmt)
                if not stmt.lstrip().upper().startswith("CREATE"):
                    cur.fetchall()
            checkpoint_label = "final"
            explain_sql = statements[-1]
        else:
            for stmt in statements[:checkpoint]:
                cur.execute(stmt)
            m = CREATE_TABLE_RE.match(statements[checkpoint - 1])
            table_name = m.group(1) if m else f"K{checkpoint}"
            explain_sql = f"SELECT COUNT(*) FROM {table_name}"
            plan = _plan_note(cur, explain_sql)
            cur.execute(explain_sql).fetchall()
            checkpoint_label = str(checkpoint)
        con.commit()
        runtime = time.perf_counter() - tic
        if not plan:
            plan = _plan_note(cur, explain_sql)
        return {
            "circuit_hash": circuit_hash,
            "qubits": qubits,
            "checkpoint_cte": checkpoint_label,
            "budget_gb": args.budget_gb,
            "runtime_s": runtime,
            "peak_rss_mb": _rss_mb(),
            "write_mb": sampler.peak_bytes / (1024 * 1024),
            "plan_note": plan,
        }
    finally:
        sampler.stop()
        try:
            cur.close()
            con.close()
        finally:
            if not args.keep_tmp:
                shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--circuit-qpy", type=Path, required=True)
    ap.add_argument("--circuit-hash", required=True)
    ap.add_argument("--budget-gb", type=int, default=8)
    ap.add_argument("--checkpoints", default="5,10,15,20,final")
    ap.add_argument("--sqlite-cache-mb", type=int, default=64)
    ap.add_argument("--timeout-seconds", type=int, default=1800)
    ap.add_argument("--tmp-root", default="/data/inferq_ooc")
    ap.add_argument("--out-csv", type=Path,
                    default=paths.out_dir() / "ooc" / "runs_prefix.csv")
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    Path(args.tmp_root).mkdir(parents=True, exist_ok=True)
    qc = _load_qiskit_circuit(str(args.circuit_qpy))
    query, qubits, _gates = _build_iqs_query_with_timeout(qc, args.timeout_seconds)
    statements = split_iqs_query_per_step(query, temp=False)
    n_ctes = max(0, len(statements) - 1)

    checkpoints: list[int] = []
    include_final = False
    for token in args.checkpoints.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "final":
            include_final = True
        else:
            ck = int(token)
            if 1 <= ck <= n_ctes:
                checkpoints.append(ck)
    if include_final:
        checkpoints.append(len(statements))

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    is_new = not args.out_csv.exists()
    with args.out_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        for checkpoint in checkpoints:
            row = _run_checkpoint(statements, checkpoint, args, args.circuit_hash, qubits)
            writer.writerow(row)
            f.flush()
            print(f"[prefix] checkpoint={row['checkpoint_cte']} runtime={row['runtime_s']:.3f}s "
                  f"write={row['write_mb']:.1f}MB", file=sys.stderr)


if __name__ == "__main__":
    main()
