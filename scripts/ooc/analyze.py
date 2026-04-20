"""Aggregate OOC results into summary tables for the revision.

Reads results.csv written by run_experiment.py and produces:

- summary_by_engine_cap.csv — completion rate, median wall time, median spill,
  memory-peak per (engine, cap), partitioned by bin
- aer_failures.csv — per-circuit Aer status at each cap vs RDBMS status; the
  "RDBMS completed but Aer didn't" rows go into the paper text
- per_circuit_wide.csv — wide table (one row per circuit × cap) with all four
  engines side by side for quick spot-checking

Run after the orchestrator is done. Idempotent.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_results(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Coerce numeric columns.
    num_cols = [
        "wall_time_s", "tracemalloc_peak_bytes", "proc_vm_peak_bytes",
        "cgroup_mem_peak_bytes", "cgroup_swap_peak_bytes",
        "cgroup_io_read_bytes", "cgroup_io_write_bytes",
        "dbms_temp_bytes_written", "dbms_temp_bytes_read",
        "num_qubits", "num_gates", "prior_peak_mem_gb", "cap_gb",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Drop warm-up rows from headline statistics but keep them available.
    df["is_warmup"] = df["run_idx"].astype(str) == "warmup"
    return df


def summary_by_engine_cap(df: pd.DataFrame) -> pd.DataFrame:
    timed = df[~df["is_warmup"]].copy()
    # Collapse Aer methods: take the best (earliest-success) method per circuit/cap
    # so the engine is "aer succeeded somewhere" not per-method.
    def agg_aer(group):
        any_success = (group["status"] == "success").any()
        rows = group if any_success else group
        if any_success:
            g = group[group["status"] == "success"]
        else:
            g = group
        return pd.Series({
            "wall_time_s": g["wall_time_s"].median(),
            "cgroup_mem_peak_bytes": g["cgroup_mem_peak_bytes"].median(),
            "dbms_temp_bytes_written": 0,
            "status": "success" if any_success else group["status"].iloc[0],
        })

    out_rows = []
    for (bin_, engine, cap), g in timed.groupby(["bin", "engine", "cap_gb"], dropna=False):
        total = g["circuit_hash"].nunique()
        ok = g[g["status"] == "success"]["circuit_hash"].nunique()
        out_rows.append({
            "bin": bin_,
            "engine": engine,
            "cap_gb": cap,
            "n_circuits": total,
            "completion_rate": ok / total if total else 0.0,
            "median_wall_time_s": g[g["status"] == "success"]["wall_time_s"].median(),
            "median_cgroup_peak_gb": g["cgroup_mem_peak_bytes"].median() / (1 << 30)
                if not g["cgroup_mem_peak_bytes"].isna().all() else None,
            "median_spill_gb": g["dbms_temp_bytes_written"].median() / (1 << 30)
                if not g["dbms_temp_bytes_written"].isna().all() else None,
            "oom_rate": (g["status"].str.startswith("oom", na=False)).sum() / len(g)
                if len(g) else 0.0,
            "timeout_rate": (g["status"] == "timeout").sum() / len(g) if len(g) else 0.0,
        })
    return pd.DataFrame(out_rows).sort_values(["bin", "cap_gb", "engine"])


def aer_failure_table(df: pd.DataFrame) -> pd.DataFrame:
    timed = df[~df["is_warmup"]]
    aer = timed[timed["engine"] == "aer"]
    rdbms = timed[timed["engine"].isin(["postgres", "sqlite", "duckdb"])]
    rows = []
    for (h, cap), g_aer in aer.groupby(["circuit_hash", "cap_gb"]):
        aer_success_methods = sorted(g_aer[g_aer["status"] == "success"]["method"].unique())
        aer_fail = len(aer_success_methods) == 0
        g_rd = rdbms[(rdbms["circuit_hash"] == h) & (rdbms["cap_gb"] == cap)]
        rdbms_ok = sorted(g_rd[g_rd["status"] == "success"]["engine"].unique())
        rows.append({
            "circuit_hash": h,
            "cap_gb": cap,
            "num_qubits": int(g_aer["num_qubits"].max()),
            "bin": g_aer["bin"].iloc[0],
            "aer_success_methods": ";".join(aer_success_methods),
            "aer_all_failed": aer_fail,
            "rdbms_success_engines": ";".join(rdbms_ok),
            "rdbms_any_success": len(rdbms_ok) > 0,
            "headline_case": aer_fail and len(rdbms_ok) > 0,
        })
    return pd.DataFrame(rows).sort_values(["cap_gb", "headline_case"], ascending=[True, False])


def per_circuit_wide(df: pd.DataFrame) -> pd.DataFrame:
    timed = df[~df["is_warmup"]].copy()
    # Collapse Aer methods to best status per circuit/cap.
    def engine_status_row(g):
        if (g["status"] == "success").any():
            best = g[g["status"] == "success"].sort_values("wall_time_s").iloc[0]
            return pd.Series({
                "status": "success",
                "wall_time_s": best["wall_time_s"],
                "cgroup_mem_peak_gb": (best["cgroup_mem_peak_bytes"] or 0) / (1 << 30),
                "spill_gb": (best["dbms_temp_bytes_written"] or 0) / (1 << 30),
            })
        return pd.Series({
            "status": g["status"].iloc[0],
            "wall_time_s": None,
            "cgroup_mem_peak_gb": (g["cgroup_mem_peak_bytes"].max() or 0) / (1 << 30),
            "spill_gb": None,
        })

    collapsed = (timed.groupby(["circuit_hash", "cap_gb", "bin", "engine", "num_qubits"])
                 .apply(engine_status_row).reset_index())
    wide = collapsed.pivot_table(
        index=["circuit_hash", "cap_gb", "bin", "num_qubits"],
        columns="engine",
        values=["status", "wall_time_s", "cgroup_mem_peak_gb", "spill_gb"],
        aggfunc="first",
    )
    wide.columns = [f"{engine}_{metric}" for metric, engine in wide.columns]
    return wide.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-csv", type=Path,
                    default=REPO_ROOT / "InferQ" / "scripts" / "ooc" / "results" / "results.csv")
    ap.add_argument("--out-dir", type=Path,
                    default=REPO_ROOT / "InferQ" / "scripts" / "ooc" / "results")
    args = ap.parse_args()

    if not args.results_csv.exists():
        raise SystemExit(f"no results file at {args.results_csv}")

    df = load_results(args.results_csv)
    print(f"[analyze] loaded {len(df)} rows", file=sys.stderr)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_by_engine_cap(df).to_csv(args.out_dir / "summary_by_engine_cap.csv", index=False)
    aer_failure_table(df).to_csv(args.out_dir / "aer_failures.csv", index=False)
    per_circuit_wide(df).to_csv(args.out_dir / "per_circuit_wide.csv", index=False)
    print(f"[analyze] wrote 3 summary CSVs to {args.out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
