"""Build a QFT-only OOC manifest.

The metadata-derived sample in data/ooc/circuits.jsonl is dominated by small
circuits that never pressure RDBMS engines (B0_trivial rows show
cgroup_io_write_bytes=0 in results.csv — engines never spilled). To exercise
spill behaviour deterministically, this script generates pure QFT circuits at
fixed qubit counts. QFT statevector grows as 2^N · 16 B and contraction
intermediate tensors grow with N, so spill is forced from ~24q upward at
cap=4 G.

Output:
  - .qpy files under circuits/<hash[:2]>/<hash>.qpy (worker reads via qiskit.qpy.load)
  - data/ooc/circuits_qft.jsonl manifest in the schema run_experiment.py expects

Use it by pointing the orchestrator at the new manifest:
  python -m scripts.ooc.run_experiment \\
    --manifest data/ooc/circuits_qft.jsonl
or:
  OOC_MANIFEST=data/ooc/circuits_qft.jsonl python -m scripts.ooc.run_experiment
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qiskit.qpy import dump as qpy_dump

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from generators.algorithms.qft import QFTGenerator  # noqa: E402
from generators.lib.generator import BaseParams  # noqa: E402
from utils.circuit_hash import compute_circuit_hash  # noqa: E402

DEFAULT_QUBITS = [22, 24, 26, 28, 30, 32, 34, 36]


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


def build_qft(n: int, inverse: bool, do_swaps: bool, measure: bool):
    params = BaseParams(min_qubits=n, max_qubits=n, measure=measure, seed=4)
    gen = QFTGenerator(params)
    return gen.generate(
        num_qubits=n, inverse=inverse, do_swaps=do_swaps, entangled=False
    )


def main():
    cfg = get_ooc_config()
    edges = cfg.get("bin_edges_qubits", [25, 28, 30, 31])

    ap = argparse.ArgumentParser()
    ap.add_argument("--qubits", type=str,
                    default=",".join(str(q) for q in DEFAULT_QUBITS),
                    help="Comma-separated qubit counts to generate")
    ap.add_argument("--circuits-dir", type=Path, default=INFERQ_ROOT / "circuits")
    ap.add_argument("--out", type=Path,
                    default=INFERQ_ROOT / "data" / "ooc" / "circuits_qft.jsonl")
    ap.add_argument("--inverse", action="store_true",
                    help="Generate inverse QFT instead of forward")
    ap.add_argument("--no-swaps", dest="do_swaps", action="store_false",
                    help="Omit final qubit-reversal swaps (reduces gate count)")
    ap.add_argument("--measure", action="store_true",
                    help="Append measurement (not used by exact-contraction harness)")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-serialize .qpy files even if already present")
    args = ap.parse_args()

    qubits = [int(x) for x in args.qubits.split(",") if x.strip()]
    print(f"[qft] generating QFT circuits for n in {qubits}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.circuits_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for n in qubits:
        print(f"[qft] n={n} building circuit ...", file=sys.stderr)
        qc = build_qft(n, inverse=args.inverse, do_swaps=args.do_swaps,
                       measure=args.measure)
        h, _qpy_hash_bytes, _method = compute_circuit_hash(qc)
        subdir = args.circuits_dir / h[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        qpy_path = subdir / f"{h}.qpy"
        if args.overwrite or not qpy_path.exists():
            with qpy_path.open("wb") as f:
                qpy_dump(qc, f)
        bin_name, bin_order = assign_bin(n, edges)
        # Aer statevector footprint = 2^N * 16 B. Stored only as a reference
        # value in `prior_peak_mem_*`; binning is by qubit count.
        sv_mb = (2 ** n) * 16 / (1024 ** 2)
        rows.append({
            "hash": h,
            "qpy_path": str(qpy_path),
            "num_qubits": n,
            "num_gates": qc.size(),
            "prior_peak_mem_mb": sv_mb,
            "prior_peak_mem_gb": sv_mb / 1024.0,
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
        })
        print(f"[qft]   {h[:8]} n={n} gates={qc.size()} -> {bin_name}",
              file=sys.stderr)

    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"[qft] wrote {args.out} ({len(rows)} circuits)", file=sys.stderr)


if __name__ == "__main__":
    main()
