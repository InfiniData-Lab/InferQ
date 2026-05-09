"""Build a spill-forcing OOC manifest using random-expander circuits.

Background
----------
The metadata-derived sample in data/ooc/circuits.jsonl is dominated by sparse
circuits whose contraction never fills memory (cgroup_io_write_bytes=0 in
prior results.csv — the engines never spilled). The natural dense candidate
(standard QFT) does not fit the IQS 603-character index alphabet at n>11:
each transpiled gate consumes up to 3 indices, and full QFT(n) transpiles
to ~3·n(n+1)/2 gates. Aggressive QFT approximation fits the budget but
collapses the contraction to a chain, defeating the spill purpose.

Pattern used here
-----------------
H on every qubit, then `layers` random perfect matchings of CX gates.
After the H layer every qubit is in superposition and untangled; once any
matching layer connects them, opt_einsum.contract_path is forced to keep
all N qubits open at the peak intermediate. So:

  peak_intermediate_elements = 2^N   (for layers >= 2)
  peak_intermediate_bytes    = 2^N · 16   (complex128)

Transpiled gate count is ~5N · layers, well below the 603-index budget
for any N we care about.

Spill thresholds (peak >= cap):
  cap=4G  → N >= 28
  cap=8G  → N >= 29
  cap=16G → N >= 30

Output
------
  - .qpy files under circuits/<hash[:2]>/<hash>.qpy
  - data/ooc/circuits_spill.jsonl manifest in the run_experiment.py schema

Run with:
  python -m scripts.ooc.build_spill_manifest
  python -m scripts.ooc.run_experiment \\
      --manifest data/ooc/circuits_spill.jsonl --resume
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.qpy import dump as qpy_dump

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from utils.circuit_hash import compute_circuit_hash  # noqa: E402

DEFAULT_QUBITS = [18, 20, 22, 24, 26, 28]
DEFAULT_LAYERS = 3
DEFAULT_SEED = 4
# By default, include DuckDB for every generated circuit. Use
# --duckdb-max-qubits only for targeted debugging runs where known-bad rows
# should be skipped explicitly.
DEFAULT_DUCKDB_MAX_QUBITS = 0


def assign_bin(num_qubits: int, edges: list[int]) -> tuple[str, int]:
    """Match the bin scheme in scripts/ooc/select_circuits.py::assign_bin."""
    if num_qubits < edges[0]:
        return "B0_trivial", 0
    if num_qubits < edges[1]:
        return "B1_aer_ok_all_caps", 1
    if num_qubits < edges[2]:
        return "B2_aer_fails_at_4", 2
    if num_qubits < edges[3]:
        return "B3_aer_fails_at_8", 3
    return "B4_aer_impossible", 4


def expander_circuit(n: int, layers: int, seed: int) -> QuantumCircuit:
    """H on all qubits, then `layers` random perfect matchings of CX gates."""
    rng = random.Random((seed << 16) ^ n)
    qc = QuantumCircuit(n, name=f"expander_n{n}_L{layers}_s{seed}")
    for q in range(n):
        qc.h(q)
    for _ in range(layers):
        perm = list(range(n))
        rng.shuffle(perm)
        for i in range(0, n - 1, 2):
            qc.cx(perm[i], perm[i + 1])
    qc.metadata = {
        "algorithm": "wide_expander",
        "n_qubits": n,
        "layers": layers,
        "seed": seed,
    }
    return qc


def main():
    cfg = get_ooc_config()
    edges = cfg.get("bin_edges_qubits", [25, 28, 30, 31])

    ap = argparse.ArgumentParser()
    ap.add_argument("--qubits", type=str,
                    default=",".join(str(q) for q in DEFAULT_QUBITS),
                    help="Comma-separated qubit counts to generate")
    ap.add_argument("--layers", type=int, default=DEFAULT_LAYERS,
                    help="Random matching layers after the H layer (>= 2 required to "
                         "lock peak intermediate at 2^N)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="Base seed for the random matchings")
    ap.add_argument("--duckdb-max-qubits", type=int, default=DEFAULT_DUCKDB_MAX_QUBITS,
                    help="Skip duckdb (write skip_engines=['duckdb']) for circuits "
                         "with num_qubits > this value. Set 0 to never skip. "
                         "Default: %(default)s")
    ap.add_argument("--circuits-dir", type=Path, default=INFERQ_ROOT / "circuits")
    ap.add_argument("--out", type=Path,
                    default=INFERQ_ROOT / "data" / "ooc" / "circuits_spill.jsonl")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-serialize .qpy files even if already present")
    args = ap.parse_args()

    if args.layers < 2:
        print(f"[spill] WARNING: layers={args.layers} < 2 — peak intermediate may be "
              f"smaller than 2^N if the path optimizer finds a better contraction",
              file=sys.stderr)

    qubits = [int(x) for x in args.qubits.split(",") if x.strip()]
    print(f"[spill] generating expander circuits for n in {qubits} (L={args.layers})",
          file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.circuits_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for n in qubits:
        qc = expander_circuit(n, args.layers, args.seed)
        h, _bytes, _method = compute_circuit_hash(qc)
        subdir = args.circuits_dir / h[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        qpy_path = subdir / f"{h}.qpy"
        if args.overwrite or not qpy_path.exists():
            with qpy_path.open("wb") as f:
                qpy_dump(qc, f)
        bin_name, bin_order = assign_bin(n, edges)
        # Peak intermediate is forced to 2^N elements (complex128 = 16 B).
        peak_bytes = (2 ** n) * 16
        peak_mb = peak_bytes / (1024 ** 2)
        skip_engines = ["duckdb"] if args.duckdb_max_qubits and n > args.duckdb_max_qubits else []
        rows.append({
            "hash": h,
            "qpy_path": str(qpy_path),
            "num_qubits": n,
            "num_gates": qc.size(),
            "prior_peak_mem_mb": peak_mb,
            "prior_peak_mem_gb": peak_mb / 1024.0,
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
            "skip_engines": skip_engines,
        })
        skip_tag = f" skip={skip_engines}" if skip_engines else ""
        print(f"[spill]   {h[:8]} n={n} L={args.layers} gates={qc.size():3d} "
              f"peak=2^{n}={peak_bytes/1e9:7.3f}GB -> {bin_name}{skip_tag}",
              file=sys.stderr)

    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"[spill] wrote {args.out} ({len(rows)} circuits)", file=sys.stderr)


if __name__ == "__main__":
    main()
