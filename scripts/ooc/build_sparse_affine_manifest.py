"""Build a 40..50 qubit sparse affine-expander OOC manifest.

Design
------
Start from |0...0>, apply H to `h_seeds` source qubits, then use only CX
gates. The H gates introduce exactly `h_seeds` independent binary variables.
Every CX is an invertible linear map over GF(2), so it permutes computational
basis states and never changes the support size.

That gives an exact sparsity estimate for every generated circuit:

    nonzero_amplitudes = 2 ** h_seeds
    density            = 2 ** (h_seeds - num_qubits)

The CX pattern has two deterministic phases:
  1. deterministic fanout from the H seeds to all remaining qubits;
  2. round-robin CX matchings to mix those variables across the register.

The fanout makes all physical qubits carry a nonzero linear form of the seed
variables, while the mixer makes the connectivity less tree-like without
changing sparsity. This is intentionally different from scripts/ooc/
build_spill_manifest.py, which applies H to every qubit and is designed to
force dense intermediates.

Example:
  python -m scripts.ooc.build_sparse_affine_manifest
  python -m scripts.ooc.run_experiment \\
      --manifest data/ooc/circuits_sparse_affine_40_50_h18.jsonl \\
      --engines postgres,duckdb,sqlite --mode split --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qiskit import QuantumCircuit, transpile
from qiskit.qpy import dump as qpy_dump

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from utils.circuit_hash import compute_circuit_hash  # noqa: E402


DEFAULT_MIN_QUBITS = 40
DEFAULT_MAX_QUBITS = 50
DEFAULT_H_SEEDS = 18
DEFAULT_MIX_LAYERS = 2


def assign_bin(num_qubits: int, edges: list[int]) -> tuple[str, int]:
    """Match scripts/ooc/select_circuits.py::assign_bin."""
    if num_qubits < edges[0]:
        return "B0_trivial", 0
    if num_qubits < edges[1]:
        return "B1_aer_ok_all_caps", 1
    if num_qubits < edges[2]:
        return "B2_aer_fails_at_4", 2
    if num_qubits < edges[3]:
        return "B3_aer_fails_at_8", 3
    return "B4_aer_impossible", 4


def _rank_gf2(rows: list[int]) -> int:
    """Rank of integer bit-vectors over GF(2)."""
    basis: dict[int, int] = {}
    for value in rows:
        x = value
        while x:
            pivot = x.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = x
                break
            x ^= basis[pivot]
    return len(basis)


def sparsity_trace(num_qubits: int, h_seeds: int, ops: list[tuple[str, int, int | None]]) -> dict:
    """Track exact support rank and active qubits through the H/CX circuit."""
    expr = [0] * num_qubits
    next_var = 0
    events = []

    for step, (gate, a, b) in enumerate(ops, 1):
        if gate == "h":
            if expr[a] != 0:
                raise ValueError("sparsity model only supports H on inactive |0> qubits")
            if next_var >= h_seeds:
                raise ValueError("more H gates than h_seeds")
            expr[a] = 1 << next_var
            next_var += 1
        elif gate == "cx":
            if b is None:
                raise ValueError("cx op missing target")
            expr[b] ^= expr[a]
        else:
            raise ValueError(f"unknown gate {gate!r}")

        rank = _rank_gf2([x for x in expr if x])
        active = sum(1 for x in expr if x)
        events.append({
            "step": step,
            "gate": gate,
            "rank": rank,
            "active_qubits": active,
            "nonzero_amplitudes": 1 << rank,
        })

    final_rank = _rank_gf2([x for x in expr if x])
    return {
        "final_rank": final_rank,
        "final_active_qubits": sum(1 for x in expr if x),
        "final_nonzero_amplitudes": 1 << final_rank,
        "max_rank": max((e["rank"] for e in events), default=0),
        "max_nonzero_amplitudes": max((e["nonzero_amplitudes"] for e in events), default=1),
        "events": events,
    }


def sparse_affine_expander(
    num_qubits: int,
    h_seeds: int,
    mix_layers: int,
) -> tuple[QuantumCircuit, dict]:
    """Return a circuit plus exact sparsity metadata."""
    if h_seeds <= 0:
        raise ValueError("h_seeds must be positive")
    if h_seeds >= num_qubits:
        raise ValueError("h_seeds must be smaller than num_qubits")
    if mix_layers < 0:
        raise ValueError("mix_layers must be non-negative")

    qc = QuantumCircuit(num_qubits, name=f"sparse_affine_n{num_qubits}_h{h_seeds}_L{mix_layers}")
    ops: list[tuple[str, int, int | None]] = []
    expr = [0] * num_qubits

    for q in range(h_seeds):
        qc.h(q)
        ops.append(("h", q, None))
        expr[q] = 1 << q

    # Fanout deterministically activates every non-seed qubit while keeping the
    # rank fixed. Each target initially receives one seed variable.
    for target in range(h_seeds, num_qubits):
        control = (target - h_seeds) % h_seeds
        qc.cx(control, target)
        ops.append(("cx", control, target))
        expr[target] ^= expr[control]

    # Mix with sparse deterministic matchings. Orientation alternates by layer to avoid
    # a one-way control/target bias while preserving the exact support size. If
    # both qubits currently carry the same linear form, CX would zero the target;
    # skip that pair so the final circuit keeps every physical qubit active.
    for layer in range(mix_layers):
        for a, b in round_robin_matching(num_qubits, layer):
            if expr[a] == expr[b]:
                continue
            control, target = (a, b) if layer % 2 == 0 else (b, a)
            qc.cx(control, target)
            ops.append(("cx", control, target))
            expr[target] ^= expr[control]

    trace = sparsity_trace(num_qubits, h_seeds, ops)
    if trace["final_rank"] != h_seeds:
        raise AssertionError(f"rank drifted: expected {h_seeds}, got {trace['final_rank']}")
    if trace["final_active_qubits"] != num_qubits:
        raise AssertionError(
            f"inactive qubits after mixing: expected {num_qubits}, got {trace['final_active_qubits']}"
        )

    evolution = [
        {
            "stage": "after_h",
            "rank": h_seeds,
            "active_qubits": h_seeds,
            "nonzero_amplitudes": 1 << h_seeds,
        },
        {
            "stage": "after_fanout",
            "rank": h_seeds,
            "active_qubits": num_qubits,
            "nonzero_amplitudes": 1 << h_seeds,
        },
        {
            "stage": "after_mix",
            "rank": trace["final_rank"],
            "active_qubits": trace["final_active_qubits"],
            "nonzero_amplitudes": trace["final_nonzero_amplitudes"],
        },
    ]

    qc.metadata = {
        "algorithm": "sparse_affine_expander",
        "n_qubits": num_qubits,
        "h_seeds": h_seeds,
        "mix_layers": mix_layers,
        "mixing_schedule": "deterministic_round_robin",
        "sparsity_model": "initial_h_rank_then_cx_linear_permutation",
        "estimated_nonzero_amplitudes": 1 << h_seeds,
        "estimated_density_log2": h_seeds - num_qubits,
        "final_active_qubits": trace["final_active_qubits"],
        "sparsity_evolution": evolution,
    }
    trace["evolution"] = evolution
    return qc, trace


def round_robin_matching(num_qubits: int, layer: int) -> list[tuple[int, int]]:
    """Deterministic matching from the round-robin tournament schedule.

    For even n this is a perfect matching. For odd n, a dummy vertex is added
    and pairs involving it are dropped, leaving exactly one idle qubit.
    """
    vertices: list[int | None] = list(range(num_qubits))
    if num_qubits % 2:
        vertices.append(None)

    rounds = len(vertices) - 1
    layer = layer % rounds
    for _ in range(layer):
        vertices = [vertices[0], vertices[-1], *vertices[1:-1]]

    pairs: list[tuple[int, int]] = []
    for i in range(len(vertices) // 2):
        a = vertices[i]
        b = vertices[-1 - i]
        if a is None or b is None:
            continue
        pairs.append((a, b))
    return pairs


def transpiled_gate_count(qc: QuantumCircuit) -> int:
    tqc = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)
    return len([instr for instr in tqc.data if instr.operation.name not in ("barrier", "measure")])


def main() -> None:
    cfg = get_ooc_config()
    edges = cfg.get("bin_edges_qubits", [25, 28, 30, 31])

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-qubits", type=int, default=DEFAULT_MIN_QUBITS)
    ap.add_argument("--max-qubits", type=int, default=DEFAULT_MAX_QUBITS)
    ap.add_argument("--h-seeds", type=int, default=DEFAULT_H_SEEDS,
                    help="Number of initial Hadamard source qubits; exact nonzero count is 2^h.")
    ap.add_argument("--mix-layers", type=int, default=DEFAULT_MIX_LAYERS,
                    help="Deterministic round-robin CX layers after fanout.")
    ap.add_argument("--index-budget", type=int, default=603)
    ap.add_argument("--circuits-dir", type=Path, default=INFERQ_ROOT / "circuits")
    ap.add_argument("--out", type=Path,
                    default=INFERQ_ROOT / "data" / "ooc" /
                    f"circuits_sparse_affine_{DEFAULT_MIN_QUBITS}_{DEFAULT_MAX_QUBITS}_h{DEFAULT_H_SEEDS}.jsonl")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if args.h_seeds >= args.min_qubits:
        raise SystemExit("--h-seeds must be smaller than --min-qubits")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.circuits_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for n in range(args.min_qubits, args.max_qubits + 1):
        qc, trace = sparse_affine_expander(n, args.h_seeds, args.mix_layers)
        transpiled_gates = transpiled_gate_count(qc)
        estimated_indices = n + 3 * transpiled_gates
        if estimated_indices >= args.index_budget:
            raise RuntimeError(
                f"n={n} exceeds IQS index budget: {estimated_indices} >= {args.index_budget}"
            )

        h, _bytes, _method = compute_circuit_hash(qc)
        subdir = args.circuits_dir / h[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        qpy_path = subdir / f"{h}.qpy"
        if args.overwrite or not qpy_path.exists():
            with qpy_path.open("wb") as f:
                qpy_dump(qc, f)

        bin_name, bin_order = assign_bin(n, edges)
        dense_statevector_bytes = (2 ** n) * 16
        sparse_rows = 1 << args.h_seeds
        rows.append({
            "hash": h,
            "qpy_path": str(qpy_path),
            "num_qubits": n,
            "num_gates": qc.size(),
            "transpiled_num_gates": transpiled_gates,
            "iqs_estimated_indices": estimated_indices,
            "sparse_affine_h_seeds": args.h_seeds,
            "sparse_affine_mix_layers": args.mix_layers,
            "sparse_affine_mixing_schedule": "deterministic_round_robin",
            "estimated_nonzero_amplitudes": sparse_rows,
            "estimated_density_log2": args.h_seeds - n,
            "estimated_density": 2.0 ** (args.h_seeds - n),
            "sparsity_rank": trace["final_rank"],
            "final_active_qubits": trace["final_active_qubits"],
            "sparsity_evolution": trace["evolution"],
            "max_nonzero_amplitudes_by_prefix": trace["max_nonzero_amplitudes"],
            "prior_peak_mem_mb": dense_statevector_bytes / (1024 ** 2),
            "prior_peak_mem_gb": dense_statevector_bytes / (1024 ** 3),
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
            "skip_engines": [],
        })
        print(
            f"[sparse-affine] {h[:8]} n={n:2d} h={args.h_seeds:2d} "
            f"gates={qc.size():3d} idx={estimated_indices:3d}/{args.index_budget} "
            f"nnz=2^{args.h_seeds} density=2^{args.h_seeds - n} "
            f"active={trace['final_active_qubits']:2d} -> {bin_name}",
            file=sys.stderr,
        )

    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"[sparse-affine] wrote {args.out} ({len(rows)} circuits)", file=sys.stderr)


if __name__ == "__main__":
    main()
