"""Build an OOC manifest from downloaded sparse-circuit QPY files.

Reads <hash>.qpy files from a directory (default: downloaded_circuits/),
optionally enriches rows with metadata from a CSV, and writes a JSONL
manifest in the run_experiment.py schema.

Run with:
  python scripts/build_sparse_spill_manifest.py
  python scripts/build_sparse_spill_manifest.py \\
      --qpy-dir downloaded_circuits \\
      --csv analysis/sampled_output.csv \\
      --out data/ooc/circuits_sparse.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import qiskit.qpy

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_ooc_config  # noqa: E402

BIN_EDGES_DEFAULT = [25, 28, 30, 31]


def assign_bin(num_qubits: int, edges: list[int]) -> tuple[str, int]:
    if num_qubits < edges[0]:
        return "B0_trivial", 0
    if num_qubits < edges[1]:
        return "B1_aer_ok_all_caps", 1
    if num_qubits < edges[2]:
        return "B2_aer_fails_at_4", 2
    if num_qubits < edges[3]:
        return "B3_aer_fails_at_8", 3
    return "B4_aer_impossible", 4


def load_csv_metadata(csv_path: Path) -> dict[str, dict]:
    meta = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            h = row.get("RowKey", "").strip()
            if h:
                meta[h] = row
    return meta


def main():
    try:
        cfg = get_ooc_config()
        edges = cfg.get("bin_edges_qubits", BIN_EDGES_DEFAULT)
    except Exception:
        edges = BIN_EDGES_DEFAULT

    ap = argparse.ArgumentParser(description="Build JSONL manifest from sparse QPY files.")
    ap.add_argument("--qpy-dir", type=Path, default=REPO_ROOT / "downloaded_circuits",
                    help="Directory containing <hash>.qpy files")
    ap.add_argument("--csv", type=Path, default=REPO_ROOT / "analysis" / "sampled_output.csv",
                    help="CSV with RowKey + metadata columns (e.g. statevector_saved_sparsity)")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "data" / "ooc" / "circuits_sparse.jsonl")
    args = ap.parse_args()

    qpy_files = sorted(args.qpy_dir.glob("*.qpy"))
    if not qpy_files:
        print(f"[sparse] No .qpy files found in {args.qpy_dir}", file=sys.stderr)
        sys.exit(1)

    csv_meta: dict[str, dict] = {}
    if args.csv and args.csv.exists():
        csv_meta = load_csv_metadata(args.csv)
        print(f"[sparse] loaded {len(csv_meta)} rows from {args.csv}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for qpy_path in qpy_files:
        h = qpy_path.stem
        try:
            with qpy_path.open("rb") as f:
                circuits = qiskit.qpy.load(f)
            qc = circuits[0]
        except Exception as e:
            print(f"[sparse] SKIP {h[:8]}: {e}", file=sys.stderr)
            continue

        num_qubits = qc.num_qubits
        num_gates = qc.size()
        peak_bytes = (2 ** num_qubits) * 16
        peak_mb = peak_bytes / (1024 ** 2)
        bin_name, bin_order = assign_bin(num_qubits, edges)

        row: dict = {
            "hash": h,
            "qpy_path": str(qpy_path.resolve()),
            "num_qubits": num_qubits,
            "num_gates": num_gates,
            "prior_peak_mem_mb": peak_mb,
            "prior_peak_mem_gb": peak_mb / 1024.0,
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
            "skip_engines": [],
        }

        if h in csv_meta:
            sparsity = csv_meta[h].get("statevector_saved_sparsity", "").strip()
            if sparsity:
                row["statevector_saved_sparsity"] = float(sparsity)

        rows.append(row)
        sparsity_tag = f" sparsity={row.get('statevector_saved_sparsity', 'n/a'):.3f}" \
            if "statevector_saved_sparsity" in row else ""
        print(f"[sparse]   {h[:8]} n={num_qubits} gates={num_gates:4d} "
              f"peak={peak_mb / 1024:.3f}GB -> {bin_name}{sparsity_tag}", file=sys.stderr)

    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"[sparse] wrote {args.out} ({len(rows)} circuits)", file=sys.stderr)


if __name__ == "__main__":
    main()
