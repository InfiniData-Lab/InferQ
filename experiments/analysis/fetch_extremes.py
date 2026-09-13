#!/usr/bin/env python3
"""
Fetch circuits that win/lose by the widest memory margin
between SQLite (rdbms_sqlite_memory_mb) and the best Qiskit method
(minimum memory across all available Qiskit simulation methods).

Win  = Qiskit uses far less memory than SQLite  (sqlite / best_qiskit is large)
Lose = Qiskit uses far more memory than SQLite  (best_qiskit / sqlite is large)

Output JSON contains all original circuit metadata columns plus computed fields:
  best_qiskit_mem_mb, best_qiskit_method, qiskit_wins_ratio / sqlite_wins_ratio

Usage:
    uv run python analysis/fetch_extremes.py [--top N] [--dataset PARQUET] [--out PATH]
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from inferq import paths

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_DATASET = paths.dataset("training") / "rdbms_training_data.parquet"
DEFAULT_OUT = paths.out_dir() / "extremes_results.json"

QISKIT_MEM_COLS = [
    "statevector_memory_usage",
    "density_matrix_memory_usage",
    "matrix_product_state_memory_usage",
    "extended_stabilizer_memory_usage",
    "automatic_memory_usage",
    "stabilizer_memory_usage",
    "unitary_memory_usage",
]

SQLITE_MEM_COL = "rdbms_sqlite_memory_mb"

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_df(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    print(f"Loaded {len(df):,} rows from {path.name}")
    return df


def compute_extremes(df: pd.DataFrame, top: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.dropna(subset=[SQLITE_MEM_COL]).copy()

    qiskit_cols = [c for c in QISKIT_MEM_COLS if c in df.columns]
    if not qiskit_cols:
        raise ValueError("No Qiskit memory columns found in dataset.")

    print(f"Using Qiskit memory columns: {qiskit_cols}")

    df["best_qiskit_mem_mb"] = df[qiskit_cols].min(axis=1)
    df["best_qiskit_method"] = df[qiskit_cols].idxmin(axis=1).str.replace(
        "_memory_usage", "", regex=False
    )

    df = df.dropna(subset=["best_qiskit_mem_mb"])
    df = df[(df["best_qiskit_mem_mb"] > 0) & (df[SQLITE_MEM_COL] > 0)]

    df["qiskit_wins_ratio"] = df[SQLITE_MEM_COL] / df["best_qiskit_mem_mb"]
    df["sqlite_wins_ratio"] = df["best_qiskit_mem_mb"] / df[SQLITE_MEM_COL]

    wins = (
        df.sort_values("qiskit_wins_ratio", ascending=False)
        .head(top)
        .reset_index(drop=True)
    )
    loses = (
        df.sort_values("sqlite_wins_ratio", ascending=False)
        .head(top)
        .reset_index(drop=True)
    )

    return wins, loses


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to JSON-serialisable records (handles NaN / non-scalar types)."""
    records = []
    for _, row in df.iterrows():
        record = {}
        for col, val in row.items():
            if pd.isna(val) if not isinstance(val, (dict, list)) else False:
                record[col] = None
            elif isinstance(val, (int, float, str, bool)):
                record[col] = val
            else:
                # e.g. dicts stored in gate_counts columns
                record[col] = val
        records.append(record)
    return records


def print_table(title: str, df: pd.DataFrame, ratio_col: str) -> None:
    print(f"\n{'=' * 90}")
    print(f"  {title}")
    print(f"{'=' * 90}")
    print(
        f"{'#':>3}  {'RowKey':<66}  {'SQLite MB':>10}  {'Qiskit MB':>10}"
        f"  {'Best Method':<30}  {'Ratio':>10}"
    )
    print("-" * 137)
    for rank, row in df.iterrows():
        print(
            f"{rank + 1:>3}  {row['RowKey']:<66}  "
            f"{row[SQLITE_MEM_COL]:>10.4f}  "
            f"{row['best_qiskit_mem_mb']:>10.4f}  "
            f"{row['best_qiskit_method']:<30}  "
            f"{row[ratio_col]:>9.2f}x"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find circuits with the widest SQLite vs Qiskit memory margin."
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of extreme circuits per category (default: 10)"
    )
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET,
        help="Path to the parquet training dataset (default: rdbms_training_data.parquet)"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help="Output JSON file path (default: extremes_results.json)"
    )
    args = parser.parse_args()

    df = load_df(args.dataset)
    wins, loses = compute_extremes(df, args.top)

    print_table(
        f"TOP {args.top}  QISKIT WINS  —  Qiskit uses far less memory than SQLite",
        wins, "qiskit_wins_ratio",
    )
    print_table(
        f"TOP {args.top}  SQLITE WINS  —  SQLite uses far less memory than Qiskit",
        loses, "sqlite_wins_ratio",
    )

    output = {
        "dataset": str(args.dataset),
        "top": args.top,
        "qiskit_wins": df_to_records(wins),
        "sqlite_wins": df_to_records(loses),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to {args.out}")


if __name__ == "__main__":
    main()
