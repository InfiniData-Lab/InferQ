#!/usr/bin/env python3
"""
Benchmark Qiskit Aer simulation methods on the four extreme circuits
(win_1, win_2, lose_1, lose_2) stored in data/extremes/.

Measures:
  - wall time     (time.perf_counter)
  - CPU time      (time.process_time)
  - peak memory   (tracemalloc)

Runs each method in:
  - multi-core mode  (Aer defaults)
  - single-core mode (max_parallel_threads/experiments/shots = 1)

Also exports Qobj JSON files to data/extremes/ for the C++ benchmark.

Usage:
    uv run python analysis/benchmark_extremes.py
"""

import sys
import os
import time
import tracemalloc
import json
import csv
from pathlib import Path

import psutil
import qiskit.qpy
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CIRCUITS_DIR = PROJECT_ROOT / "data" / "extremes"
RESULTS_CSV  = Path(__file__).resolve().parent / "benchmark_extremes_results.csv"

CIRCUIT_LABELS = {
    "130b04bfb38aa8212ee0889dbe6618330a8ffa96612de553b101762cf2c3c2e1": "win_1",
    "0dcde7369202fa0a6f8a06321c9ce68bed7db53ec61b32cd9e05a21bea0a6786": "win_2",
    "05b85287a20d10750a9e4fd49c9acdd3d83b51af17c7e085be7805dbc2f3be48": "lose_1",
    "0036db2f669fb3d4cfcadc6628bd073af51622b260324d1eaa8513ea5bf478a8": "lose_2",
}

# All Aer methods (excluding infiniquantum)
METHODS = [
    "statevector",
    "density_matrix",
    "matrix_product_state",
    "stabilizer",
    "extended_stabilizer",
    "unitary",
    "automatic",
]

# Methods for C++ Qobj JSON export (subset that use standard instructions)
CPP_METHODS = ["statevector", "density_matrix", "matrix_product_state"]

SHOTS = 1024

# Basis gates that Aer C++ controller understands in Qobj format
BASIS_GATES = [
    "cx", "u3", "u2", "u1", "x", "h", "s", "sdg", "t", "tdg",
    "swap", "ccx", "id", "rz", "ry", "rx", "sx", "p", "reset", "measure",
]

SINGLE_CORE_OPTIONS = {
    "max_parallel_threads":     1,
    "max_parallel_experiments": 1,
    "max_parallel_shots":       1,
}

# ---------------------------------------------------------------------------
# Circuit loading
# ---------------------------------------------------------------------------

def load_circuits() -> dict[str, QuantumCircuit]:
    circuits: dict[str, QuantumCircuit] = {}
    for qpy_file in sorted(CIRCUITS_DIR.glob("*.qpy")):
        h = qpy_file.stem
        label = CIRCUIT_LABELS.get(h, h[:8])
        with open(qpy_file, "rb") as f:
            loaded = qiskit.qpy.load(f)
        qc = loaded[0] if isinstance(loaded, list) else loaded
        circuits[label] = qc
    return circuits

# ---------------------------------------------------------------------------
# Circuit preparation
# ---------------------------------------------------------------------------

def prepare_circuit(qc: QuantumCircuit, method: str) -> QuantumCircuit:
    """Transpile and add the right terminal instruction for the given method."""
    circ = transpile(qc, basis_gates=BASIS_GATES, optimization_level=0)

    if method == "unitary":
        # Unitary method cannot have measurements; save the full unitary instead
        circ.save_unitary()
    else:
        if not any(inst.operation.name == "measure" for inst in circ.data):
            circ.measure_all()

    return circ

# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------

def run_benchmark(
    sim: AerSimulator,
    circ: QuantumCircuit,
    shots: int = SHOTS,
) -> tuple[bool, str, float, float, int]:
    """
    Returns (success, status, wall_s, cpu_s, peak_bytes).
    """
    tracemalloc.start()
    t_wall = time.perf_counter()
    t_cpu  = time.process_time()

    job    = sim.run(circ, shots=shots)
    result = job.result()

    wall_s    = time.perf_counter() - t_wall
    cpu_s     = time.process_time()  - t_cpu
    _, peak_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return result.success, result.status, wall_s, cpu_s, peak_b

# ---------------------------------------------------------------------------
# Qobj JSON export for C++ benchmark
# ---------------------------------------------------------------------------

def circuit_to_qobj_dict(
    qc: QuantumCircuit,
    method: str,
    shots: int,
    single_core: bool = False,
) -> dict:
    """
    Manually builds a Qobj JSON dict from a transpiled QuantumCircuit.
    (qiskit.compiler.assemble was removed in Qiskit 2.0; we build it ourselves.)
    """
    instructions = []
    for inst in qc.data:
        name   = inst.operation.name
        qubits = [qc.find_bit(q).index for q in inst.qubits]

        # Skip Aer save-state instructions; not valid in legacy Qobj
        if name.startswith("save_"):
            continue
        # Skip barriers (no-op in simulation)
        if name == "barrier":
            continue

        entry: dict = {"name": name, "qubits": qubits}

        if inst.operation.params:
            entry["params"] = [float(p) for p in inst.operation.params]

        if name == "measure":
            cbits         = [qc.find_bit(c).index for c in inst.clbits]
            entry["memory"]   = cbits
            entry["register"] = cbits

        instructions.append(entry)

    n_q = qc.num_qubits
    n_c = qc.num_clbits or n_q

    cfg: dict = {
        "shots":         shots,
        "method":        method,
        "n_qubits":      n_q,
        "memory_slots":  n_c,
    }
    if single_core:
        cfg.update(SINGLE_CORE_OPTIONS)

    return {
        "qobj_id":        f"benchmark_{method}",
        "backend_name":   "aer_simulator",
        "backend_version": "0.17.0",
        "type":           "QASM",
        "schema_version": "1.3.0",
        "header":         {},
        "config":         cfg,
        "experiments": [{
            "header": {
                "name":          "circuit",
                "n_qubits":      n_q,
                "memory_slots":  n_c,
                "clbit_labels":  [["meas", i] for i in range(n_c)],
                "qubit_labels":  [["q",    i] for i in range(n_q)],
            },
            "config": {
                "n_qubits":     n_q,
                "memory_slots": n_c,
            },
            "instructions": instructions,
        }],
    }


def export_qobj_jsons(circuits: dict[str, QuantumCircuit]) -> None:
    """
    Export Qobj JSON files (multi-core and single-core) for the C++ benchmark.
    Files are written to data/extremes/<label>_<method>_[multi|single]_qobj.json
    """
    out_dir = CIRCUITS_DIR
    count = 0
    for label, qc in circuits.items():
        base_circ = transpile(qc, basis_gates=BASIS_GATES, optimization_level=0)
        base_circ.measure_all()

        for method in CPP_METHODS:
            for single_core in [False, True]:
                mode  = "single" if single_core else "multi"
                qobj  = circuit_to_qobj_dict(base_circ, method, SHOTS, single_core)
                fname = out_dir / f"{label}_{method}_{mode}_qobj.json"
                with open(fname, "w") as f:
                    json.dump(qobj, f, indent=2)
                count += 1

    print(f"  Exported {count} Qobj JSON files to {out_dir}")

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _fmt(v, decimals: int = 6) -> str:
    if isinstance(v, float):
        return f"{v:.{decimals}f}"
    return str(v)


def print_table(rows: list[dict]) -> None:
    sep = "-" * 108
    hdr = (
        f"{'circuit':<10} {'qubits':>6} {'depth':>5} "
        f"{'method':<26} {'mode':<7} "
        f"{'wall_s':>10} {'cpu_s':>10} {'peak_mem_KB':>12} {'ok':<6}"
    )
    print(f"\n{sep}\n{hdr}\n{sep}")
    for r in rows:
        print(
            f"{r['circuit']:<10} {r['n_qubits']:>6} {r['depth']:>5} "
            f"{r['method']:<26} {r['mode']:<7} "
            f"{_fmt(r['wall_s']):>10} {_fmt(r['cpu_s']):>10} "
            f"{_fmt(r['peak_kb'], 1):>12} "
            f"{'YES' if r['success'] else 'NO':<6}"
        )
    print(sep)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading circuits from data/extremes/ …")
    circuits = load_circuits()
    for label, qc in circuits.items():
        print(f"  {label}: {qc.num_qubits} qubits, depth {qc.depth()}")

    print("\nExporting Qobj JSON files for C++ benchmark …")
    export_qobj_jsons(circuits)

    rows: list[dict] = []

    print("\n--- Python benchmarks ---")
    for label, qc in circuits.items():
        print(f"\n[{label}]  {qc.num_qubits} qubits  depth={qc.depth()}")

        for method in METHODS:
            for single_core in [False, True]:
                mode = "single" if single_core else "multi"

                sim_kwargs = {"method": method}
                if single_core:
                    sim_kwargs |= SINGLE_CORE_OPTIONS

                try:
                    circ = prepare_circuit(qc, method)
                    sim  = AerSimulator(**sim_kwargs)
                    success, status, wall_s, cpu_s, peak_b = run_benchmark(sim, circ)
                    peak_kb = round(peak_b / 1024, 1)
                    wall_s  = round(wall_s, 6)
                    cpu_s   = round(cpu_s,  6)
                except Exception as exc:
                    success = False
                    status  = str(exc)[:80]
                    wall_s  = cpu_s = peak_kb = float("nan")

                rows.append({
                    "circuit":  label,
                    "n_qubits": qc.num_qubits,
                    "depth":    qc.depth(),
                    "method":   method,
                    "mode":     mode,
                    "wall_s":   wall_s,
                    "cpu_s":    cpu_s,
                    "peak_kb":  peak_kb,
                    "success":  success,
                    "status":   "OK" if success else status,
                })

                mark = "+" if success else "-"
                if success:
                    print(
                        f"  [{mark}] [{method:<26}][{mode:<6}] "
                        f"wall={wall_s:.4f}s  cpu={cpu_s:.4f}s  "
                        f"mem={peak_kb}KB"
                    )
                else:
                    print(f"  [{mark}] [{method:<26}][{mode:<6}] {status}")

    print_table(rows)

    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nResults saved to {RESULTS_CSV}")


if __name__ == "__main__":
    main()
