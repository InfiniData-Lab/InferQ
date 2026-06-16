"""Build a QFT OOC manifest for a dense 3..26 qubit sweep.

For each qubit count, the builder starts from full QFT and increases Qiskit's
approximation_degree only if needed to fit InferQ/IQS's finite index alphabet
after transpilation. This gives the densest QFT variant that the SQL pipeline
can actually execute.

Example:
  python -m scripts.ooc.build_qft_manifest --min-qubits 3 --max-qubits 26
  python -m scripts.ooc.run_experiment \\
      --manifest data/ooc/circuits_qft_3_26.jsonl \\
      --results-csv scripts/ooc/results/res7_qft_3_26_cpu1.csv \\
      --caps-gb 4,8,16 --engines postgres,duckdb,sqlite --mode split --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qiskit import transpile
from qiskit.circuit.library import QFT
from qiskit.qpy import dump as qpy_dump

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from utils.circuit_hash import compute_circuit_hash  # noqa: E402


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


def qft_circuit(num_qubits: int, approximation_degree: int, do_swaps: bool):
    qc = QFT(
        num_qubits=num_qubits,
        approximation_degree=approximation_degree,
        do_swaps=do_swaps,
        inverse=False,
        name=f"qft_n{num_qubits}_a{approximation_degree}_sw{int(do_swaps)}",
    ).decompose()
    qc.metadata = {
        "algorithm": "qft",
        "n_qubits": num_qubits,
        "approximation_degree": approximation_degree,
        "do_swaps": do_swaps,
    }
    return qc


def transpiled_gate_count(qc) -> int:
    tqc = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)
    return len([instr for instr in tqc.data if instr.operation.name not in ("barrier", "measure")])


def densest_qft(num_qubits: int, index_budget: int, do_swaps: bool):
    """Return (qc, approximation_degree, transpiled_gates, estimated_indices)."""
    best = None
    for degree in range(0, num_qubits + 1):
        qc = qft_circuit(num_qubits, degree, do_swaps)
        gates = transpiled_gate_count(qc)
        estimated = num_qubits + 3 * gates
        if estimated < index_budget:
            return qc, degree, gates, estimated
        best = (qc, degree, gates, estimated)
    raise RuntimeError(
        f"no QFT variant fits index budget for n={num_qubits}; "
        f"least dense estimate was {best[3] if best else 'unknown'} >= {index_budget}"
    )


def main() -> None:
    cfg = get_ooc_config()
    edges = cfg.get("bin_edges_qubits", [25, 28, 30, 31])

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-qubits", type=int, default=3)
    ap.add_argument("--max-qubits", type=int, default=26)
    ap.add_argument("--index-budget", type=int, default=603,
                    help="IQS index alphabet size. Worker rejects estimated >= this.")
    ap.add_argument("--do-swaps", action="store_true",
                    help="Include final QFT swaps if they still fit the index budget.")
    ap.add_argument("--circuits-dir", type=Path, default=INFERQ_ROOT / "circuits")
    ap.add_argument("--out", type=Path,
                    default=INFERQ_ROOT / "data" / "ooc" / "circuits_qft_3_26.jsonl")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.circuits_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for n in range(args.min_qubits, args.max_qubits + 1):
        qc, degree, transpiled_gates, estimated = densest_qft(
            n, args.index_budget, args.do_swaps
        )
        h, _bytes, _method = compute_circuit_hash(qc)
        subdir = args.circuits_dir / h[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        qpy_path = subdir / f"{h}.qpy"
        if args.overwrite or not qpy_path.exists():
            with qpy_path.open("wb") as f:
                qpy_dump(qc, f)

        bin_name, bin_order = assign_bin(n, edges)
        statevector_bytes = (2 ** n) * 16
        rows.append({
            "hash": h,
            "qpy_path": str(qpy_path),
            "num_qubits": n,
            "num_gates": qc.size(),
            "transpiled_num_gates": transpiled_gates,
            "iqs_estimated_indices": estimated,
            "qft_approximation_degree": degree,
            "qft_do_swaps": args.do_swaps,
            "prior_peak_mem_mb": statevector_bytes / (1024 ** 2),
            "prior_peak_mem_gb": statevector_bytes / (1024 ** 3),
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
            "skip_engines": [],
        })
        print(
            f"[qft] {h[:8]} n={n:2d} approx={degree:2d} "
            f"gates={qc.size():4d} transpiled={transpiled_gates:4d} "
            f"idx={estimated:3d}/{args.index_budget} -> {bin_name}",
            file=sys.stderr,
        )

    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"[qft] wrote {args.out} ({len(rows)} circuits)", file=sys.stderr)


if __name__ == "__main__":
    main()
