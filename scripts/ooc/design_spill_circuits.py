"""Classify OOC pilot results into no/light/hard spill circuit bands.

The paper needs circuits that exercise different out-of-core regimes. Qubit
count is a useful first proxy, but the final labels should come from observed
behavior under the exact engine, cap, and query mode. This script reads a pilot
CSV from run_experiment.py and emits:

  - spill_design_candidates.csv: one row per successful measured run
  - spill_design_manifest.jsonl: selected circuits copied from the input
    manifest, with a spill_design label added

Example:
  python -m scripts.ooc.design_spill_circuits \
      --results-csv scripts/ooc/results/res6_fixed_split_duck_sqlite_fair.csv \
      --manifest data/ooc/circuits_spill.jsonl \
      --mode split \
      --engines sqlite,duckdb \
      --caps-gb 4,8,16 \
      --out-dir scripts/ooc/results/res6_spill_design
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]


def _float(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spill_proxy_bytes(row: dict) -> float:
    """Use the best available spill/write signal for a successful run."""
    dbms = _float(row, "dbms_temp_bytes_written") or 0.0
    cgroup = _float(row, "cgroup_io_write_bytes") or 0.0
    return max(dbms, cgroup)


def _gb(value: float | None) -> float:
    return (value or 0.0) / (1 << 30)


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _read_manifest(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[str(row["hash"])] = row
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _median(values: Iterable[float]) -> float:
    clean = sorted(values)
    if not clean:
        return 0.0
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2


def classify_row(row: dict, light_gb: float, hard_gb: float, pressure: float) -> str:
    """Classify one successful measured run.

    Hard spill should capture either large disk traffic or runs that complete
    very close to the memory cap. Light spill is deliberately small but nonzero,
    useful for demonstrating graceful degradation before the hard case.
    """
    spill_gb = _gb(_spill_proxy_bytes(row))
    mem_gb = _gb(_float(row, "cgroup_mem_peak_bytes"))
    cap_gb = _float(row, "cap_gb") or 0.0
    mem_pressure = (mem_gb / cap_gb) if cap_gb > 0 else 0.0
    if spill_gb >= hard_gb or mem_pressure >= pressure:
        return "hard_spill"
    if spill_gb >= light_gb:
        return "light_spill"
    return "no_spill"


def candidates(rows: list[dict], args: argparse.Namespace) -> list[dict]:
    engines = {x.strip() for x in args.engines.split(",") if x.strip()}
    caps = {x.strip() for x in args.caps_gb.split(",") if x.strip()}
    out = []
    for row in rows:
        if row.get("run_idx") == "warmup":
            continue
        if row.get("status") != "success":
            continue
        if args.mode and row.get("mode") != args.mode:
            continue
        if engines and row.get("engine") not in engines:
            continue
        if caps and row.get("cap_gb") not in caps:
            continue
        spill_bytes = _spill_proxy_bytes(row)
        mem_gb = _gb(_float(row, "cgroup_mem_peak_bytes"))
        cap_gb = _float(row, "cap_gb") or 0.0
        pressure = (mem_gb / cap_gb) if cap_gb > 0 else 0.0
        out.append({
            "spill_band": classify_row(row, args.light_spill_gb, args.hard_spill_gb, args.hard_mem_pressure),
            "engine": row.get("engine", ""),
            "mode": row.get("mode", ""),
            "cap_gb": row.get("cap_gb", ""),
            "circuit_hash": row.get("circuit_hash", ""),
            "num_qubits": row.get("num_qubits", ""),
            "num_gates": row.get("num_gates", ""),
            "bin": row.get("bin", ""),
            "wall_time_s": row.get("wall_time_s", ""),
            "mem_peak_gb": mem_gb,
            "mem_pressure": pressure,
            "spill_proxy_gb": _gb(spill_bytes),
            "dbms_temp_gb": _gb(_float(row, "dbms_temp_bytes_written")),
            "cgroup_write_gb": _gb(_float(row, "cgroup_io_write_bytes")),
        })
    return sorted(out, key=lambda r: (
        r["engine"],
        r["cap_gb"],
        {"no_spill": 0, "light_spill": 1, "hard_spill": 2}.get(r["spill_band"], 9),
        float(r["num_qubits"] or 0),
    ))


def select_manifest_rows(cands: list[dict], manifest: dict[str, dict], per_band: int) -> list[dict]:
    """Pick representative circuits per engine/cap/band, deduped by hash."""
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in cands:
        grouped[(row["engine"], row["cap_gb"], row["spill_band"])].append(row)

    selected: dict[str, dict] = {}
    for key, group in sorted(grouped.items()):
        # Prefer the median spill/pressure example in each bucket over extremes.
        target_spill = _median(float(r["spill_proxy_gb"]) for r in group)
        ranked = sorted(group, key=lambda r: (
            abs(float(r["spill_proxy_gb"]) - target_spill),
            float(r["wall_time_s"] or math.inf),
        ))
        for row in ranked[:per_band]:
            h = row["circuit_hash"]
            if h not in manifest:
                continue
            out = dict(manifest[h])
            labels = set(out.get("spill_design", []))
            labels.add(f"{row['engine']}:{row['cap_gb']}G:{row['mode']}:{row['spill_band']}")
            out["spill_design"] = sorted(labels)
            selected[h] = out
    return sorted(selected.values(), key=lambda r: (int(r.get("num_qubits") or 0), r["hash"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-csv", type=Path, required=True)
    ap.add_argument("--manifest", type=Path,
                    default=REPO_ROOT / "InferQ" / "data" / "ooc" / "circuits_spill.jsonl")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--mode", default="")
    ap.add_argument("--engines", default="sqlite,duckdb,postgres")
    ap.add_argument("--caps-gb", default="4,8,16")
    ap.add_argument("--light-spill-gb", type=float, default=0.01,
                    help="Minimum spill proxy for light_spill. Default: 10 MiB-ish.")
    ap.add_argument("--hard-spill-gb", type=float, default=1.0,
                    help="Minimum spill proxy for hard_spill.")
    ap.add_argument("--hard-mem-pressure", type=float, default=0.85,
                    help="Classify as hard if cgroup peak / cap exceeds this.")
    ap.add_argument("--per-band", type=int, default=2,
                    help="Manifest rows to select per (engine, cap, band).")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(args.results_csv)
    cands = candidates(rows, args)
    _write_csv(args.out_dir / "spill_design_candidates.csv", cands)

    manifest = _read_manifest(args.manifest)
    selected = select_manifest_rows(cands, manifest, args.per_band)
    with (args.out_dir / "spill_design_manifest.jsonl").open("w") as f:
        for row in selected:
            f.write(json.dumps(row) + "\n")

    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in cands:
        counts[(row["engine"], row["cap_gb"], row["spill_band"])] += 1
    for (engine, cap, band), count in sorted(counts.items()):
        print(f"{engine:8s} cap={cap:>2s}G {band:11s} {count}")
    print(f"wrote {args.out_dir}")


if __name__ == "__main__":
    main()
