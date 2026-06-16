#!/usr/bin/env python3
"""Compare the SQLite small in-memory run against the small-group baseline."""
from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS = PROJECT_ROOT / "res" / "finetuned" / "sqlite_small_memory" / "results_sqlite_small_memory.csv"
DEFAULT_BASELINE = SCRIPT_DIR / "baselines" / "sqlite_small_group_baseline.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "res" / "finetuned" / "sqlite_small_memory" / "summary_vs_baseline.csv"
DEFAULT_BY_CIRCUIT = PROJECT_ROOT / "res" / "finetuned" / "sqlite_small_memory" / "by_circuit_vs_baseline.csv"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def load_baseline(path: Path) -> dict[str, float]:
    baseline: dict[str, float] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("engine") and row.get("engine") != "sqlite":
                continue
            circuit_hash = row["circuit_hash"]
            baseline.setdefault(circuit_hash, float(row["baseline_s"]))
    return baseline


def load_results(path: Path, profile: str) -> dict[str, float]:
    runs: dict[str, list[float]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("engine") != "sqlite":
                continue
            if profile and row.get("profile") != profile:
                continue
            if row.get("status") != "success":
                continue
            if row.get("run_idx", "").startswith("warmup"):
                continue
            runs.setdefault(row["circuit_hash"], []).append(float(row["wall_time_s"]))
    return {circuit_hash: statistics.median(times) for circuit_hash, times in runs.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-csv", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--baseline-by-circuit", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--profile", default="sqlite_small_memory")
    parser.add_argument("--out-summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-by-circuit", type=Path, default=DEFAULT_BY_CIRCUIT)
    args = parser.parse_args()

    baseline = load_baseline(args.baseline_by_circuit)
    observed = load_results(args.results_csv, args.profile)
    joined = []
    for circuit_hash, config_s in observed.items():
        baseline_s = baseline.get(circuit_hash)
        if baseline_s is None:
            continue
        speedup = baseline_s / config_s if config_s > 0 else float("nan")
        joined.append({
            "circuit_hash": circuit_hash,
            "baseline_s": baseline_s,
            "config_s": config_s,
            "speedup": speedup,
            "config_faster": speedup > 1.0,
        })

    if not joined:
        raise SystemExit("no overlapping successful sqlite rows to compare")

    baseline_times = [r["baseline_s"] for r in joined]
    config_times = [r["config_s"] for r in joined]
    speedups = [r["speedup"] for r in joined]
    geomean = math.exp(statistics.mean(math.log(s) for s in speedups if s > 0))
    summary = {
        "profile": args.profile,
        "matched_circuits": len(joined),
        "baseline_median_s": statistics.median(baseline_times),
        "config_median_s": statistics.median(config_times),
        "median_speedup": statistics.median(baseline_times) / statistics.median(config_times),
        "geomean_speedup": geomean,
        "baseline_sum_s": sum(baseline_times),
        "config_sum_s": sum(config_times),
        "total_speedup": sum(baseline_times) / sum(config_times),
        "baseline_p95_s": percentile(baseline_times, 0.95),
        "config_p95_s": percentile(config_times, 0.95),
        "p95_speedup": percentile(baseline_times, 0.95) / percentile(config_times, 0.95),
        "faster_circuits": sum(1 for r in joined if r["config_faster"]),
        "slower_circuits": sum(1 for r in joined if not r["config_faster"]),
    }

    args.out_by_circuit.parent.mkdir(parents=True, exist_ok=True)
    with args.out_by_circuit.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(joined[0]))
        writer.writeheader()
        writer.writerows(sorted(joined, key=lambda r: r["speedup"]))

    with args.out_summary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary))
        writer.writeheader()
        writer.writerow(summary)

    print(
        f"{args.profile}: matched={summary['matched_circuits']} "
        f"median={summary['median_speedup']:.3f}x "
        f"total={summary['total_speedup']:.3f}x "
        f"p95={summary['p95_speedup']:.3f}x "
        f"faster={summary['faster_circuits']}/{summary['matched_circuits']}"
    )
    print(f"summary: {args.out_summary}")
    print(f"by-circuit: {args.out_by_circuit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
