"""Aggregate OOC results into summary tables for the revision.

This script intentionally uses only the Python standard library. The OOC runner
is often used on fresh benchmark boxes where pandas is not installed, and the
summary step should still work on a raw results CSV.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]

SUCCESS = "success"
RDBMS_ENGINES = {"postgres", "sqlite", "duckdb"}


def _float(row: dict, key: str) -> float | None:
    try:
        value = row.get(key, "")
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: Iterable[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


def _is_warmup(row: dict) -> bool:
    return str(row.get("run_idx", "")) == "warmup"


def _is_oom(status: str) -> bool:
    return status.startswith("oom")


def _spill_proxy_bytes(row: dict) -> float | None:
    """Best available per-row spill/write proxy.

    New runs write an explicit spill_proxy_bytes column: PostgreSQL uses exact
    EXPLAIN temp blocks, while DuckDB/SQLite use per-run /proc/self/io write
    deltas. Older CSVs did not have that column, so keep a conservative
    fallback for backward compatibility.
    """
    explicit = _float(row, "spill_proxy_bytes")
    if explicit is not None:
        return explicit
    dbms = _float(row, "dbms_temp_bytes_written")
    if dbms and dbms > 0:
        return dbms
    proc = _float(row, "proc_io_write_bytes")
    if proc is not None:
        return proc
    return _float(row, "cgroup_io_write_bytes")


def _write_bytes(row: dict) -> float | None:
    proc = _float(row, "proc_io_write_bytes")
    if proc is not None:
        return proc
    return _float(row, "cgroup_io_write_bytes")


def load_results(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["is_warmup"] = _is_warmup(row)
    return rows


def summary_by_engine_cap(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["is_warmup"]:
            continue
        groups[(row.get("bin", ""), row.get("engine", ""), row.get("cap_gb", ""))].append(row)

    out = []
    for (bin_, engine, cap), group in sorted(groups.items(), key=lambda x: (x[0][0], _cap_key(x[0][2]), x[0][1])):
        circuits = {r["circuit_hash"] for r in group}
        successful = [r for r in group if r.get("status") == SUCCESS]
        success_circuits = {r["circuit_hash"] for r in successful}
        spillers = [r for r in successful if (_spill_proxy_bytes(r) or 0) > 0]
        statuses = [r.get("status", "") for r in group]
        out.append({
            "bin": bin_,
            "engine": engine,
            "cap_gb": cap,
            "n_circuits": len(circuits),
            "completed": len(success_circuits),
            "completion_rate": _ratio(len(success_circuits), len(circuits)),
            "timeout_count": sum(1 for s in statuses if s == "timeout"),
            "oom_abort_count": sum(1 for s in statuses if _is_oom(s)),
            "median_wall_time_s": _median(_float(r, "wall_time_s") for r in successful),
            "median_cgroup_peak_gb": _gb(_median(_float(r, "cgroup_mem_peak_bytes") for r in group)),
            "spill_rate": _ratio(len({r["circuit_hash"] for r in spillers}), len(success_circuits)),
            "median_spill_gb": _gb(_median(_spill_proxy_bytes(r) for r in spillers)),
            "median_write_gb": _gb(_median(_write_bytes(r) for r in successful)),
        })
    return out


def aer_failure_table(rows: list[dict]) -> list[dict]:
    timed = [r for r in rows if not r["is_warmup"]]
    by_circuit_cap: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in timed:
        by_circuit_cap[(row.get("circuit_hash", ""), row.get("cap_gb", ""))].append(row)

    out = []
    for (circuit_hash, cap), group in sorted(by_circuit_cap.items(), key=lambda x: (_cap_key(x[0][1]), x[0][0])):
        aer = [r for r in group if r.get("engine") == "aer"]
        if not aer:
            continue
        rdbms = [r for r in group if r.get("engine") in RDBMS_ENGINES]
        aer_success_methods = sorted({r.get("method", "") for r in aer if r.get("status") == SUCCESS})
        rdbms_ok = sorted({r.get("engine", "") for r in rdbms if r.get("status") == SUCCESS})
        first = aer[0]
        out.append({
            "circuit_hash": circuit_hash,
            "cap_gb": cap,
            "num_qubits": first.get("num_qubits", ""),
            "bin": first.get("bin", ""),
            "aer_success_methods": ";".join(aer_success_methods),
            "aer_all_failed": str(not aer_success_methods).lower(),
            "rdbms_success_engines": ";".join(rdbms_ok),
            "rdbms_any_success": str(bool(rdbms_ok)).lower(),
            "headline_case": str((not aer_success_methods) and bool(rdbms_ok)).lower(),
        })
    return out


def per_circuit_wide(rows: list[dict]) -> list[dict]:
    timed = [r for r in rows if not r["is_warmup"]]
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in timed:
        grouped[(row.get("circuit_hash", ""), row.get("cap_gb", ""), row.get("bin", ""), row.get("num_qubits", ""))].append(row)

    out = []
    for key, group in sorted(grouped.items(), key=lambda x: (x[0][0], _cap_key(x[0][1]))):
        circuit_hash, cap, bin_, qubits = key
        row = {
            "circuit_hash": circuit_hash,
            "cap_gb": cap,
            "bin": bin_,
            "num_qubits": qubits,
        }
        for engine in sorted({r.get("engine", "") for r in group}):
            eg = [r for r in group if r.get("engine") == engine]
            success = [r for r in eg if r.get("status") == SUCCESS]
            best = min(success, key=lambda r: _float(r, "wall_time_s") or float("inf")) if success else eg[0]
            row[f"{engine}_status"] = SUCCESS if success else best.get("status", "")
            row[f"{engine}_wall_time_s"] = best.get("wall_time_s", "") if success else ""
            row[f"{engine}_cgroup_mem_peak_gb"] = _gb(_float(best, "cgroup_mem_peak_bytes"))
            row[f"{engine}_spill_gb"] = _gb(_spill_proxy_bytes(best)) if success else ""
        out.append(row)
    return out


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def _gb(value: float | None) -> float | None:
    return value / (1 << 30) if value is not None else None


def _cap_key(cap: str) -> int:
    try:
        return int(float(cap))
    except (TypeError, ValueError):
        return -1


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-csv", type=Path,
                    default=REPO_ROOT / "InferQ" / "scripts" / "ooc" / "results" / "results.csv")
    ap.add_argument("--out-dir", type=Path,
                    default=REPO_ROOT / "InferQ" / "scripts" / "ooc" / "results")
    args = ap.parse_args()

    if not args.results_csv.exists():
        raise SystemExit(f"no results file at {args.results_csv}")

    rows = load_results(args.results_csv)
    print(f"[analyze] loaded {len(rows)} rows", file=sys.stderr)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "summary_by_engine_cap.csv", summary_by_engine_cap(rows))
    write_csv(args.out_dir / "aer_failures.csv", aer_failure_table(rows))
    write_csv(args.out_dir / "per_circuit_wide.csv", per_circuit_wide(rows))
    print(f"[analyze] wrote 3 summary CSVs to {args.out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
