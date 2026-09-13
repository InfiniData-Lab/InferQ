"""Probe existing QPY circuits from a CSV of hashes against Qiskit Aer.

Reads RowKey hashes from a CSV, loads the corresponding <hash>.qpy files,
attempts simulation with a memory cap, and writes a JSONL log of results
(OK or failure reason).

Run with:
  python experiments/misc/probe_aer_ooc.py \\
      --csv analysis/my_hashes.csv \\
      --qpy-dir downloaded_circuits \\
      --out data/ooc_rdbms_only/aer_probe_results.jsonl \\
      --max-memory-mb 16384 \\
      --aer-method statevector \\
      --aer-shots 1 \\
      --timeout 30
"""
from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from qiskit import QuantumCircuit, transpile

from inferq import paths
from inferq.storage.qpy import load_circuit

_BASIS_GATES = ["u", "cx", "id", "rz", "sx", "x"]

# ---------------------------------------------------------------------------
# Timeout (POSIX only)
# ---------------------------------------------------------------------------

class _TimeoutError(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _TimeoutError("timeout")


# ---------------------------------------------------------------------------
# Aer probe
# ---------------------------------------------------------------------------

def try_aer_simulate(
    qc: QuantumCircuit,
    method: str,
    shots: int,
    timeout_seconds: int,
    max_memory_mb: int,
) -> tuple[bool, str]:
    """Attempt Aer simulation. Returns (success, error_message)."""
    try:
        from qiskit_aer import AerSimulator  # type: ignore
    except ImportError:
        return False, "qiskit_aer not installed"

    sim = AerSimulator(method=method, max_memory_mb=max_memory_mb)

    use_alarm = hasattr(signal, "SIGALRM") and timeout_seconds > 0
    if use_alarm:
        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(timeout_seconds)

    try:
        # Decompose high-level gates first
        qc_t = transpile(qc, basis_gates=_BASIS_GATES, optimization_level=0)
        # measure_all() forces full statevector allocation — no lazy shortcut
        qc_t.measure_all()
        job = sim.run(qc_t, shots=shots)
        result = job.result()
        if not result.success:
            return False, f"Result not successful: {result.status}"
        return True, ""
    except _TimeoutError:
        return False, f"Timed out after {timeout_seconds}s"
    except MemoryError as exc:
        return False, f"MemoryError: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if use_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Probe QPY circuits from a CSV of hashes against Qiskit Aer."
    )
    ap.add_argument("--csv", type=Path, required=True,
                    help="CSV file with a RowKey column containing circuit hashes")
    ap.add_argument("--qpy-dir", type=Path,
                    default=paths.data_dir() / "downloaded_circuits",
                    help="Directory containing <hash>.qpy files")
    ap.add_argument("--out", type=Path,
                    default=paths.data_dir() / "ooc_rdbms_only" / "aer_probe_results.jsonl",
                    help="Output JSONL file with per-circuit probe results")
    ap.add_argument("--max-memory-mb", type=int, default=16384,
                    help="Aer memory cap in MB (default: 16384 = 16 GB)")
    ap.add_argument("--aer-method", default="statevector",
                    choices=["statevector", "density_matrix", "matrix_product_state",
                             "stabilizer", "extended_stabilizer", "unitary"],
                    help="Aer simulation method (default: statevector)")
    ap.add_argument("--aer-shots", type=int, default=1,
                    help="Number of shots (default: 1)")
    ap.add_argument("--timeout", type=int, default=30,
                    help="Per-circuit timeout in seconds, 0 = no limit (default: 30)")
    args = ap.parse_args()

    # --- load hashes from CSV ---
    if not args.csv.exists():
        print(f"[probe] CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    hashes: list[str] = []
    with args.csv.open(newline="") as f:
        for row in csv.DictReader(f):
            h = row.get("RowKey", "").strip()
            if h:
                hashes.append(h)

    if not hashes:
        print(f"[probe] No RowKey hashes found in {args.csv}", file=sys.stderr)
        sys.exit(1)

    print(f"[probe] Loaded {len(hashes)} hashes from {args.csv}", file=sys.stderr)
    print(f"[probe] QPY dir : {args.qpy_dir}", file=sys.stderr)
    print(f"[probe] Method  : {args.aer_method}  max_mem={args.max_memory_mb} MB  "
          f"shots={args.aer_shots}  timeout={args.timeout}s", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    rows: list[dict] = []

    for h in hashes:
        qpy_path = args.qpy_dir / f"{h}.qpy"

        # -- locate QPY --
        if not qpy_path.exists():
            print(f"[probe]   {h[:8]}  SKIP  (QPY not found)", file=sys.stderr)
            rows.append({
                "timestamp": timestamp,
                "hash": h,
                "status": "skip",
                "reason": "QPY file not found",
                "num_qubits": None,
                "num_gates": None,
                "peak_mem_gb": None,
                "aer_method": args.aer_method,
                "aer_success": None,
                "aer_error": "QPY file not found",
            })
            continue

        # -- load circuit --
        try:
            qc = load_circuit(qpy_path)
        except Exception as exc:
            print(f"[probe]   {h[:8]}  SKIP  (load error: {exc})", file=sys.stderr)
            rows.append({
                "timestamp": timestamp,
                "hash": h,
                "status": "skip",
                "reason": f"QPY load error: {exc}",
                "num_qubits": None,
                "num_gates": None,
                "peak_mem_gb": None,
                "aer_method": args.aer_method,
                "aer_success": None,
                "aer_error": str(exc),
            })
            continue

        num_qubits = qc.num_qubits
        num_gates = qc.size()
        peak_gb = (2 ** num_qubits) * 16 / (1024 ** 3)

        # -- probe Aer --
        success, error = try_aer_simulate(
            qc,
            method=args.aer_method,
            shots=args.aer_shots,
            timeout_seconds=args.timeout,
            max_memory_mb=args.max_memory_mb,
        )

        status_tag = "OK  " if success else "FAIL"
        print(
            f"[probe]   {h[:8]}  {status_tag}  n={num_qubits}  gates={num_gates:4d}  "
            f"peak={peak_gb:.3f} GB"
            + (f"  err={error}" if not success else ""),
            file=sys.stderr,
        )

        rows.append({
            "timestamp": timestamp,
            "hash": h,
            "status": "ok" if success else "fail",
            "reason": None if success else error,
            "num_qubits": num_qubits,
            "num_gates": num_gates,
            "peak_mem_gb": peak_gb,
            "aer_method": args.aer_method,
            "aer_success": success,
            "aer_error": error,
        })

    # --- write output ---
    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    n_ok   = sum(1 for r in rows if r["aer_success"] is True)
    n_fail = sum(1 for r in rows if r["aer_success"] is False)
    n_skip = sum(1 for r in rows if r["aer_success"] is None)

    print(f"\n[probe] Results -> {args.out}", file=sys.stderr)
    print(f"[probe]   OK:   {n_ok}", file=sys.stderr)
    print(f"[probe]   FAIL: {n_fail}", file=sys.stderr)
    print(f"[probe]   SKIP: {n_skip}", file=sys.stderr)
    print("[probe] Done.", file=sys.stderr)


if __name__ == "__main__":
    main()