"""Stratified sampler for OOC experiments.

Reads the InferQ metadata parquet shards, keeps circuits with at least one
successful RDBMS run, assigns each to a memory bin based on prior peak memory
(or to the "Aer-impossible" bin if Aer skipped/failed and RDBMS succeeded),
then samples a fixed quota per bin with sub-stratification on qubit count.

Emits a JSONL manifest consumed by run_experiment.py.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

# Allow running both as a module (`python -m scripts.ooc.select_circuits`) and
# as a script (`python scripts/ooc/select_circuits.py`).
REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from scripts.lib import assign_bin as assign_qubit_bin  # noqa: E402

RDBMS_MEM_COLS = ["rdbms_sqlite_memory_mb", "rdbms_psql_memory_mb", "rdbms_ducksql_memory_mb"]
RDBMS_TIME_COLS = ["rdbms_sqlite_time_s", "rdbms_psql_time_s", "rdbms_ducksql_time_s"]
AER_TIME_COLS = [
    "statevector_execution_time",
    "statevector_saved_execution_time",
    "automatic_execution_time",
    "matrix_product_state_execution_time",
    "density_matrix_execution_time",
    "stabilizer_execution_time",
]


def load_metadata(paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        try:
            frames.append(pd.read_parquet(p))
        except Exception as e:
            print(f"[warn] failed to read {p}: {e}", file=sys.stderr)
    if not frames:
        raise RuntimeError("no metadata parquet files loaded")
    df = pd.concat(frames, ignore_index=True)
    # Prefer RowKey as hash, fallback to any hash column.
    if "RowKey" in df.columns:
        df["hash"] = df["RowKey"].astype(str)
    elif "hash" in df.columns:
        df["hash"] = df["hash"].astype(str)
    else:
        raise RuntimeError("no hash/RowKey column in metadata")
    return df


def assign_bin(row: pd.Series, edges_q: list[int]) -> tuple[str, int] | None:
    """Return (bin_name, bin_order) or None if the circuit should be excluded.

    Binning is by qubit count because Aer statevector memory = 2^N · 16 B, so
    qubits directly predict which caps OOM Aer. The prior tracemalloc-based
    RDBMS memory numbers in the metadata underestimate real footprint by orders
    of magnitude and aren't usable for stratification.

    edges_q = [e1, e2, e3, e4]:
        B0 "trivial"          : q <  e1          (Aer fits everywhere, baseline)
        B1 "aer_ok_all_caps"  : e1 ≤ q < e2      (Aer ≤2 GB, cap=4 also fine)
        B2 "aer_fails_at_4"   : e2 ≤ q < e3      (Aer 4-8 GB, fails at cap=4)
        B3 "aer_fails_at_8"   : e3 ≤ q < e4      (Aer 16 GB, fails at caps 4,8)
        B4 "aer_impossible"   : q ≥ e4           (Aer 32+ GB, fails everywhere)
    """
    # Prior RDBMS success = at least one non-null time column. Required because
    # we need circuits whose SQL plan is known to work before spending time on
    # memory-constrained reruns.
    rdbms_ok = any(
        pd.notna(row.get(c)) and row.get(c) is not None for c in RDBMS_TIME_COLS
    )
    if not rdbms_ok:
        return None

    num_qubits = int(row.get("num_qubits") or row.get("circuit_qubits") or 0)
    if num_qubits <= 0:
        return None

    return assign_qubit_bin(num_qubits, edges_q)


def resolve_qpy_path(circuit_hash: str, base: Path) -> Path | None:
    subdir = base / circuit_hash[:2]
    candidate = subdir / f"{circuit_hash}.qpy"
    if candidate.exists():
        return candidate
    flat = base / f"{circuit_hash}.qpy"
    if flat.exists():
        return flat
    return None


def stratified_sample(
    df: pd.DataFrame, per_bin: int, seed: int, qubit_buckets: int
) -> pd.DataFrame:
    """Sample per_bin rows per bin with qubit sub-stratification.

    Within each bin we rank by hardness (max prior RDBMS time) so smaller bins
    don't get dominated by trivially short queries. Sub-stratification on qubit
    count ensures one qubit-count doesn't drown out others inside a bin.
    """
    df = df.copy()
    df["_hardness"] = df[RDBMS_TIME_COLS].max(axis=1).fillna(0.0)
    rng = random.Random(seed)
    out_rows = []
    for _bin_name, bin_df in df.groupby("bin"):
        if len(bin_df) <= per_bin:
            out_rows.extend(bin_df.to_dict("records"))
            continue
        qs = bin_df["num_qubits"].astype(int)
        q_min, q_max = qs.min(), qs.max()
        if q_min == q_max or qubit_buckets <= 1:
            buckets = [bin_df]
        else:
            edges = [q_min + i * (q_max - q_min + 1) / qubit_buckets for i in range(qubit_buckets + 1)]
            buckets = []
            for i in range(qubit_buckets):
                lo, hi = edges[i], edges[i + 1]
                if i == qubit_buckets - 1:
                    buckets.append(bin_df[(qs >= lo) & (qs <= hi)])
                else:
                    buckets.append(bin_df[(qs >= lo) & (qs < hi)])

        nonempty = [b for b in buckets if len(b) > 0]
        per_bucket = max(1, per_bin // max(1, len(nonempty)))
        remaining = per_bin
        for bucket in nonempty:
            if remaining <= 0:
                break
            # Hybrid: take the top-half by hardness, then random-sample the slot
            # count from that pool. Keeps hard circuits without producing a
            # single deterministic pick.
            sorted_bucket = bucket.sort_values("_hardness", ascending=False)
            pool_size = max(per_bucket * 3, len(sorted_bucket) // 2)
            pool = sorted_bucket.head(min(pool_size, len(sorted_bucket)))
            take = min(per_bucket, len(pool), remaining)
            idxs = rng.sample(range(len(pool)), take)
            rows = pool.iloc[idxs].to_dict("records")
            out_rows.extend(rows)
            remaining -= take
        # Top up from the bin (hardness-ranked) if rounding left quota.
        if remaining > 0:
            already = {r["hash"] for r in out_rows}
            leftover = bin_df.sort_values("_hardness", ascending=False)
            leftover = [r for r in leftover.to_dict("records") if r["hash"] not in already]
            out_rows.extend(leftover[:remaining])
    return pd.DataFrame(out_rows).drop(columns=["_hardness"], errors="ignore")


def build_manifest_row(row: pd.Series, qpy_path: Path) -> dict:
    rdbms_methods_ok = [
        c.replace("rdbms_", "").replace("_time_s", "")
        for c in RDBMS_TIME_COLS if pd.notna(row.get(c))
    ]
    rdbms_peak_mb = max(
        (row[c] for c in RDBMS_MEM_COLS if pd.notna(row.get(c))),
        default=float("nan"),
    )
    aer_methods_ok = [
        c.replace("_execution_time", "")
        for c in AER_TIME_COLS if pd.notna(row.get(c))
    ]
    return {
        "hash": str(row["hash"]),
        "qpy_path": str(qpy_path),
        "num_qubits": int(row.get("num_qubits") or row.get("circuit_qubits") or 0),
        "num_gates": int(row.get("circuit_size") or 0),
        "prior_peak_mem_mb": float(rdbms_peak_mb) if pd.notna(rdbms_peak_mb) else None,
        "prior_peak_mem_gb": (float(rdbms_peak_mb) / 1024.0) if pd.notna(rdbms_peak_mb) else None,
        "prior_rdbms_methods": rdbms_methods_ok,
        "prior_aer_methods": aer_methods_ok,
        "bin": row["bin"],
        "bin_order": int(row["bin_order"]),
    }


def main():
    cfg = get_ooc_config()

    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata-dir", type=Path,
                    default=REPO_ROOT / "InferQ" / "data" / "metadata",
                    help="Directory of metadata_part_*.parquet shards")
    ap.add_argument("--circuits-dir", type=Path,
                    default=REPO_ROOT / "InferQ" / "circuits",
                    help="Base dir of <hash[:2]>/<hash>.qpy files")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "InferQ" / cfg["circuits_manifest"])
    ap.add_argument("--per-bin", type=int, default=cfg["circuits_per_bin"])
    ap.add_argument("--pilot", action="store_true",
                    help="Use pilot_circuits_per_bin instead of full count")
    ap.add_argument("--qubit-buckets", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--require-qpy", action="store_true",
                    help="Drop circuits whose .qpy file can't be resolved locally")
    args = ap.parse_args()

    per_bin = cfg["pilot_circuits_per_bin"] if args.pilot else args.per_bin
    edges_q = cfg["bin_edges_qubits"]

    metadata_paths = sorted(args.metadata_dir.glob("metadata_part_*.parquet"))
    if not metadata_paths:
        raise SystemExit(f"no parquet shards found under {args.metadata_dir}")
    print(f"[select] loading {len(metadata_paths)} parquet shards", file=sys.stderr)
    df = load_metadata(metadata_paths)
    print(f"[select] loaded {len(df):,} circuits", file=sys.stderr)

    assignments = df.apply(lambda r: assign_bin(r, edges_q), axis=1)
    df = df[assignments.notna()].copy()
    df[["bin", "bin_order"]] = pd.DataFrame(assignments.dropna().tolist(), index=df.index)
    print(f"[select] {len(df):,} after filtering for RDBMS success", file=sys.stderr)
    print(df["bin"].value_counts().to_string(), file=sys.stderr)

    sampled = stratified_sample(df, per_bin, args.seed, args.qubit_buckets)
    print(f"[select] sampled {len(sampled)} circuits across {sampled['bin'].nunique()} bins",
          file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    skipped = 0
    with args.out.open("w") as f:
        for _, row in sampled.iterrows():
            qpy = resolve_qpy_path(str(row["hash"]), args.circuits_dir)
            if qpy is None:
                if args.require_qpy:
                    skipped += 1
                    continue
                qpy = args.circuits_dir / row["hash"][:2] / f"{row['hash']}.qpy"
            f.write(json.dumps(build_manifest_row(row, qpy)) + "\n")
    print(f"[select] wrote {args.out} (skipped {skipped} with missing .qpy)", file=sys.stderr)


if __name__ == "__main__":
    main()
