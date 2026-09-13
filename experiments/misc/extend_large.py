"""Extend a sample of sparse-circuit QPY files by padding extra qubits,
attempt Qiskit Aer simulation for each, log failures, and write
updated QPY files + a JSONL manifest to an ooc_rdbms_only/ output dir.

The script intentionally pushes circuits into the regime where Aer
statevector/density-matrix simulation is expected to fail so that the
resulting manifest can be used as RDBMS-only workloads.

Run with:
  python experiments/misc/extend_large.py
  python experiments/misc/extend_large.py \\
      --qpy-dir downloaded_circuits \\
      --csv  analysis/sampled_output.csv \\
      --out-dir data/ooc_rdbms_only \\
      --extra-qubits 4 \\
      --target-min-qubits 31 \\
      --aer-shots 1 \\
      --aer-method statevector \\
      --timeout 30
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

import qiskit.qpy
from qiskit import QuantumCircuit

from experiments._common import BIN_EDGES_DEFAULT, assign_bin, write_manifest

# ---------------------------------------------------------------------------
# Repo-root bootstrap (mirrors experiments/ooc/build_sparse_spill_manifest.py)
# ---------------------------------------------------------------------------
from inferq import paths
from inferq.storage.qpy import load_circuit

try:
    from inferq.config import get_ooc_config
    _HAS_CONFIG = True
except Exception:
    _HAS_CONFIG = False


def load_csv_metadata(csv_path: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            h = row.get("RowKey", "").strip()
            if h:
                meta[h] = row
    return meta


# ---------------------------------------------------------------------------
# Circuit extension
# ---------------------------------------------------------------------------

_BASIS_GATES = ["u", "cx", "id", "rz", "sx", "x"]


def extend_circuit(qc: QuantumCircuit, extra_qubits: int) -> QuantumCircuit:
    """Return a new circuit with *extra_qubits* qubits appended and entangled.

    The original circuit is first transpiled to basis gates (no backend /
    coupling map) so that high-level instructions such as RealAmplitudes,
    EfficientSU2, or custom parameterised gates are fully decomposed before
    the circuit is copied.  This prevents AerError 'unknown instruction'.

    # The extra qubits are then entangled via a GHZ-style CNOT chain anchored
    # at the last original qubit and cascading down through all extras:

        cx(n-1, n)
        cx(n,   n+1)
        cx(n+1, n+2)
        ...

    This forces Aer to allocate the full 2^(n+extra) statevector and prevents
    it from shortcutting the simulation on idle/separable qubits.
    """
    from qiskit import transpile

    # Decompose high-level / custom gates to universal basis — no backend so
    # no coupling-map limit is imposed.
    qc = transpile(qc, basis_gates=_BASIS_GATES, optimization_level=3)

    if extra_qubits <= 0:
        return qc.copy()

    new_qc = QuantumCircuit(qc.num_qubits + extra_qubits,
                            qc.num_clbits,
                            name=qc.name)

    # Copy all original instructions verbatim onto the original qubit indices
    for instruction in qc.data:
        original_qubits = [new_qc.qubits[qc.qubits.index(q)] for q in instruction.qubits]
        original_clbits = [new_qc.clbits[qc.clbits.index(c)] for c in instruction.clbits]
        new_qc.append(instruction.operation, original_qubits, original_clbits)

    # # GHZ-style CNOT chain: last original qubit -> first extra -> second extra -> ...
    # anchor = qc.num_qubits - 1
    # for i in range(qc.num_qubits, qc.num_qubits + extra_qubits):
    #     ctrl = anchor if i == qc.num_qubits else i - 1
    #     new_qc.cx(new_qc.qubits[ctrl], new_qc.qubits[i])

    return new_qc


def stable_hash(qc: QuantumCircuit, original_hash: str, extra_qubits: int) -> str:
    """Derive a deterministic hash for the extended circuit."""
    raw = f"{original_hash}+ext{extra_qubits}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Aer simulation attempt
# ---------------------------------------------------------------------------

class _TimeoutError(Exception):
    pass


def _alarm_handler(signum, frame):          # POSIX only
    raise _TimeoutError("timeout")


def try_aer_simulate(
    qc: QuantumCircuit,
    method: str,
    shots: int,
    timeout_seconds: int,
) -> tuple[bool, str]:
    """Attempt a single Aer simulation.

    Returns (success: bool, error_message: str).
    error_message is "" on success.
    """
    try:
        from qiskit_aer import AerSimulator  # type: ignore
    except ImportError:
        return False, "qiskit_aer not installed"

    sim = AerSimulator(method=method, max_memory_mb=16384)

    # Set up a POSIX alarm for hard timeout (Linux/macOS only)
    use_alarm = hasattr(signal, "SIGALRM") and timeout_seconds > 0
    if use_alarm:
        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(timeout_seconds)

    try:
        # measure_all() forces Aer to actually execute the full statevector
        # simulation — no lazy path is possible when measurements are present.
        # save_statevector() alone is silently treated as a no-op by Aer.
        qc_probe = qc.copy()
        qc_probe.measure_all()
        job = sim.run(qc_probe, shots=shots)
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
    # --- config ---
    edges = BIN_EDGES_DEFAULT
    if _HAS_CONFIG:
        try:
            cfg = get_ooc_config()
            edges = cfg.get("bin_edges_qubits", BIN_EDGES_DEFAULT)
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="Extend circuits with extra qubits, probe Aer, write ooc_rdbms_only manifest."
    )
    ap.add_argument("--qpy-dir", type=Path,
                    default=paths.data_dir() / "downloaded_circuits",
                    help="Directory containing <hash>.qpy source files")
    ap.add_argument("--csv", type=Path,
                    default=paths.out_dir() / "sampled_output.csv",
                    help="Optional CSV with RowKey + metadata (e.g. statevector_saved_sparsity)")
    ap.add_argument("--out-dir", type=Path,
                    default=paths.data_dir() / "ooc_rdbms_only",
                    help="Output directory: QPY files, JSONL manifest, and simulation log")
    ap.add_argument("--extra-qubits", type=int, default=4,
                    help="Number of idle qubits to append to every circuit (default: 4)")
    ap.add_argument("--target-min-qubits", type=int, default=31,
                    help="Ensure extended circuit has at least this many qubits "
                         "(overrides --extra-qubits if needed, default: 31)")
    ap.add_argument("--aer-shots", type=int, default=1,
                    help="Shots to use in Aer simulation attempt (default: 1)")
    ap.add_argument("--aer-method", default="statevector",
                    choices=["statevector", "density_matrix", "matrix_product_state",
                             "stabilizer", "extended_stabilizer", "unitary"],
                    help="Aer simulation method (default: statevector)")
    ap.add_argument("--timeout", type=int, default=30,
                    help="Per-circuit Aer timeout in seconds, 0 = no limit (default: 30)")
    ap.add_argument("--skip-aer", action="store_true",
                    help="Skip Aer simulation probing entirely (just extend + write QPY/JSONL)")
    args = ap.parse_args()

    # --- output paths ---
    qpy_out_dir = args.out_dir / "circuits"
    qpy_out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "circuits_large.jsonl"
    log_path = args.out_dir / "aer_failures.log"

    # --- load source QPY files ---
    qpy_files = sorted(args.qpy_dir.glob("*.qpy"))
    if not qpy_files:
        print(f"[extend] No .qpy files found in {args.qpy_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"[extend] Found {len(qpy_files)} QPY files in {args.qpy_dir}", file=sys.stderr)

    # --- load optional CSV ---
    csv_meta: dict[str, dict] = {}
    if args.csv and args.csv.exists():
        csv_meta = load_csv_metadata(args.csv)
        print(f"[extend] Loaded {len(csv_meta)} rows from {args.csv}", file=sys.stderr)

    rows: list[dict] = []
    failure_log_lines: list[str] = []
    timestamp = datetime.now(UTC).isoformat()

    for qpy_path in qpy_files:
        orig_hash = qpy_path.stem

        # -- load original circuit --
        try:
            qc_orig = load_circuit(qpy_path)
        except Exception as exc:
            print(f"[extend] SKIP {orig_hash[:8]}: cannot load QPY – {exc}", file=sys.stderr)
            continue

        # -- determine how many qubits to add --
        orig_n = qc_orig.num_qubits
        extra = max(
            args.extra_qubits,
            max(0, args.target_min_qubits - orig_n),
        )
        qc_ext = extend_circuit(qc_orig, extra)
        ext_n = qc_ext.num_qubits
        ext_hash = stable_hash(qc_orig, orig_hash, extra)

        # -- write extended QPY --
        ext_qpy_path = qpy_out_dir / f"{ext_hash}.qpy"
        try:
            with ext_qpy_path.open("wb") as f:
                qiskit.qpy.dump(qc_ext, f)
        except Exception as exc:
            print(f"[extend] SKIP {orig_hash[:8]}: QPY write failed – {exc}", file=sys.stderr)
            continue

        # -- memory estimates --
        num_gates = qc_ext.size()
        peak_bytes = (2 ** ext_n) * 16
        peak_mb = peak_bytes / (1024 ** 2)
        bin_name, bin_order = assign_bin(ext_n, edges)

        # -- Aer simulation probe --
        aer_success: bool | None = None
        aer_error: str = ""
        if not args.skip_aer:
            aer_success, aer_error = try_aer_simulate(
                qc_ext,
                method=args.aer_method,
                shots=args.aer_shots,
                timeout_seconds=args.timeout,
            )
            status_tag = "OK" if aer_success else "FAIL"
            print(
                f"[extend]   {orig_hash[:8]} -> {ext_hash[:8]} "
                f"n={orig_n}->{ext_n} gates={num_gates:4d} "
                f"peak={peak_mb / 1024:.3f} GB  bin={bin_name}  aer={status_tag}",
                file=sys.stderr,
            )
            if not aer_success:
                failure_log_lines.append(
                    json.dumps({
                        "timestamp": timestamp,
                        "orig_hash": orig_hash,
                        "ext_hash": ext_hash,
                        "orig_qubits": orig_n,
                        "ext_qubits": ext_n,
                        "extra_added": extra,
                        "aer_method": args.aer_method,
                        "error": aer_error,
                    })
                )
        else:
            print(
                f"[extend]   {orig_hash[:8]} -> {ext_hash[:8]} "
                f"n={orig_n}->{ext_n} gates={num_gates:4d} "
                f"peak={peak_mb / 1024:.3f} GB  bin={bin_name}  aer=skipped",
                file=sys.stderr,
            )

        # -- build manifest row --
        row: dict = {
            "hash": ext_hash,
            "orig_hash": orig_hash,
            "qpy_path": str(ext_qpy_path.resolve()),
            "orig_qpy_path": str(qpy_path.resolve()),
            "num_qubits": ext_n,
            "orig_num_qubits": orig_n,
            "extra_qubits_added": extra,
            "num_gates": num_gates,
            "prior_peak_mem_mb": peak_mb,
            "prior_peak_mem_gb": peak_mb / 1024.0,
            "prior_rdbms_methods": [],
            "prior_aer_methods": [],
            "bin": bin_name,
            "bin_order": bin_order,
            "skip_engines": [],
            # Aer probe results (None if --skip-aer)
            "aer_probe": {
                "skipped": args.skip_aer,
                "method": args.aer_method if not args.skip_aer else None,
                "shots": args.aer_shots if not args.skip_aer else None,
                "timeout_s": args.timeout if not args.skip_aer else None,
                "success": aer_success,
                "error": aer_error,
            },
        }

        # carry over CSV metadata if present under original hash
        if orig_hash in csv_meta:
            sparsity = csv_meta[orig_hash].get("statevector_saved_sparsity", "").strip()
            if sparsity:
                row["statevector_saved_sparsity"] = float(sparsity)

        rows.append(row)

    # --- write manifest ---
    write_manifest(manifest_path, rows)
    print(f"[extend] Wrote manifest  -> {manifest_path}  ({len(rows)} circuits)", file=sys.stderr)

    # --- write failure log ---
    if not args.skip_aer:
        with log_path.open("w") as f:
            for line in failure_log_lines:
                f.write(line + "\n")
        n_fail = len(failure_log_lines)
        n_ok = sum(1 for r in rows if r["aer_probe"].get("success") is True)
        print(
            f"[extend] Wrote Aer log   -> {log_path}  "
            f"({n_ok} ok / {n_fail} failed / {len(rows) - n_ok - n_fail} skipped)",
            file=sys.stderr,
        )

    print("[extend] Done.", file=sys.stderr)


if __name__ == "__main__":
    main()