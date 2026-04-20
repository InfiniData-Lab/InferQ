"""Orchestrator for OOC / limited-memory RDBMS experiments.

For every (circuit, cap, engine) triple:

1. (postgres only) Start a fresh Docker container with --memory=CAP and a tuned
   postgresql.conf. Wait for TCP accept.
2. Drop the OS page cache.
3. Launch worker.py under `systemd-run --user --scope --property=MemoryMax=CAP`
   (for embedded engines; postgres worker gets a loose cap since the real
   enforcement is on the container).
4. Wait for the worker to exit.
5. Read cgroup counters (memory.peak, memory.swap.peak, io.stat) from the
   container (postgres) or scope (embedded engines).
6. Stop + remove the container.
7. Parse the worker's JSON output.
8. Append one CSV row per timed run (warmup runs are kept with run_idx="warmup").
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
INFERQ_ROOT = REPO_ROOT / "InferQ"
if str(INFERQ_ROOT) not in sys.path:
    sys.path.insert(0, str(INFERQ_ROOT))

from config import get_ooc_config  # noqa: E402
from scripts.ooc import cgroup_metrics  # noqa: E402

WORKER_MODULE = "scripts.ooc.worker"

CSV_FIELDS = [
    "circuit_hash", "num_qubits", "num_gates", "prior_peak_mem_gb", "bin",
    "engine", "method", "cap_gb", "run_idx",
    "wall_time_s", "tracemalloc_peak_bytes", "proc_vm_peak_bytes",
    "cgroup_mem_peak_bytes", "cgroup_swap_peak_bytes",
    "cgroup_io_read_bytes", "cgroup_io_write_bytes",
    "dbms_temp_bytes_written", "dbms_temp_bytes_read",
    "status", "error_msg",
    "scope_unit", "container_id", "host_timestamp",
]


@dataclass
class CircuitEntry:
    hash: str
    qpy_path: Path
    num_qubits: int
    num_gates: int
    prior_peak_mem_gb: Optional[float]
    bin: str

    @classmethod
    def from_json(cls, d: dict) -> "CircuitEntry":
        return cls(
            hash=d["hash"],
            qpy_path=Path(d["qpy_path"]),
            num_qubits=d.get("num_qubits") or 0,
            num_gates=d.get("num_gates") or 0,
            prior_peak_mem_gb=d.get("prior_peak_mem_gb"),
            bin=d.get("bin", ""),
        )


# ─────────── Postgres Docker lifecycle ───────────

def start_pg_container(cap_gb: int, image: str, host_port: int, name: str,
                        ready_timeout: int = 60) -> str:
    """Start a fresh Postgres container with memory cap. Returns container id."""
    cmd = [
        "docker", "run", "-d", "--rm",
        "--name", name,
        "--memory", f"{cap_gb}g", "--memory-swap", f"{cap_gb}g",
        "--memory-swappiness", "0",
        "-e", f"CAP_GB={cap_gb}",
        "-e", "POSTGRES_PASSWORD=postgres",
        "-p", f"{host_port}:5432",
        image,
    ]
    cid = subprocess.check_output(cmd, text=True).strip()
    # Wait for PG to accept connections.
    deadline = time.time() + ready_timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            try:
                s.connect(("127.0.0.1", host_port))
                # Verify it's actually Postgres, not a half-up container, by
                # trying a simple SELECT via psycopg2 (pg_isready would also work).
                time.sleep(0.5)
                return cid
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
    # Timed out — grab logs for debugging before failing.
    logs = subprocess.run(["docker", "logs", "--tail=40", cid], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
    subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raise RuntimeError(f"Postgres did not become ready in {ready_timeout}s. Logs:\n{logs}")


def stop_pg_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────── Worker invocation ───────────

def build_worker_cmd(
    engine: str, cap_gb: int, circuit: CircuitEntry, aer_method: Optional[str],
    out_path: Path, cfg: dict, scope_unit: str, use_systemd: bool,
) -> list[str]:
    py = sys.executable
    inner = [
        py, "-m", WORKER_MODULE,
        "--engine", engine,
        "--cap-gb", str(cap_gb),
        "--circuit-qpy", str(circuit.qpy_path),
        "--circuit-hash", circuit.hash,
        "--bin", circuit.bin,
        "--out-path", str(out_path),
        "--n-runs", str(cfg["n_runs"]),
        "--warmup", str(cfg["warmup_runs"]),
        "--timeout-seconds", str(cfg["timeout_seconds"]),
        "--tmp-root", cfg["tmp_root"],
        "--pg-host", "127.0.0.1",
        "--pg-port", str(cfg["postgres_host_port"]),
    ]
    if engine == "aer" and aer_method:
        inner += ["--aer-method", aer_method]
        inner += ["--aer-pad-mb", str(cfg["aer_max_memory_pad_mb"])]
    if not use_systemd:
        return inner

    # For Postgres, the enforcement is on the container; use a loose scope cap.
    scope_cap_gb = cap_gb if engine != "postgres" else max(cap_gb, 60)
    scope_cmd = [
        "systemd-run", "--user", "--scope", "--quiet",
        "--unit", scope_unit,
        "--property", f"MemoryMax={scope_cap_gb}G",
        "--property", "MemorySwapMax=0",
        "--property", "IOAccounting=yes",
        "--property", "MemoryAccounting=yes",
        "--",
    ]
    return scope_cmd + inner


def run_worker(cmd: list[str], overall_timeout: int) -> tuple[int, str, str]:
    """Run the worker command; return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, text=True, capture_output=True, timeout=overall_timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + "\n[orchestrator timeout]"


# ─────────── Row emission ───────────

def cgroup_snapshot_for(engine: str, scope_unit: str, container_id: Optional[str]
                        ) -> Optional[cgroup_metrics.CgroupSnapshot]:
    path = None
    if engine == "postgres" and container_id:
        path = cgroup_metrics.find_docker_cgroup(container_id)
    else:
        path = cgroup_metrics.find_systemd_scope_cgroup(scope_unit)
    if path is None:
        return None
    return cgroup_metrics.read_cgroup(path)


def emit_rows(writer: csv.DictWriter, circuit: CircuitEntry, envelope: dict,
              engine: str, cap_gb: int, method: Optional[str],
              cg: Optional[cgroup_metrics.CgroupSnapshot],
              scope_unit: str, container_id: Optional[str]) -> None:
    base = {
        "circuit_hash": circuit.hash,
        "num_qubits": envelope.get("num_qubits", circuit.num_qubits),
        "num_gates": envelope.get("num_gates", circuit.num_gates),
        "prior_peak_mem_gb": circuit.prior_peak_mem_gb,
        "bin": circuit.bin,
        "engine": engine,
        "method": method or "",
        "cap_gb": cap_gb,
        "cgroup_mem_peak_bytes": cg.memory_peak_bytes if cg else None,
        "cgroup_swap_peak_bytes": cg.memory_swap_peak_bytes if cg else None,
        "cgroup_io_read_bytes": cg.io_read_bytes if cg else None,
        "cgroup_io_write_bytes": cg.io_write_bytes if cg else None,
        "scope_unit": scope_unit,
        "container_id": container_id or "",
        "host_timestamp": envelope.get("started_at"),
    }
    runs = envelope.get("runs") or []
    if not runs:
        # Pure-failure case: no runs executed (e.g., circuit loader crashed).
        writer.writerow({**base,
            "run_idx": "",
            "wall_time_s": None, "tracemalloc_peak_bytes": None, "proc_vm_peak_bytes": None,
            "dbms_temp_bytes_written": None, "dbms_temp_bytes_read": None,
            "status": envelope.get("status", "error"),
            "error_msg": envelope.get("error", ""),
        })
        return
    for r in runs:
        writer.writerow({**base,
            "run_idx": r.get("run_idx"),
            "wall_time_s": r.get("wall_time_s"),
            "tracemalloc_peak_bytes": r.get("tracemalloc_peak_bytes"),
            "proc_vm_peak_bytes": r.get("proc_vm_peak_bytes"),
            "dbms_temp_bytes_written": r.get("spill_bytes_written"),
            "dbms_temp_bytes_read": r.get("spill_bytes_read"),
            "status": r.get("status", "unknown"),
            "error_msg": r.get("error", ""),
        })


# ─────────── Main loop ───────────

def load_manifest(path: Path) -> list[CircuitEntry]:
    entries = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(CircuitEntry.from_json(json.loads(line)))
    return entries


def run_one(
    circuit: CircuitEntry, engine: str, cap_gb: int, method: Optional[str],
    cfg: dict, writer: csv.DictWriter, dry_run: bool, use_systemd: bool,
) -> None:
    scope_unit = f"ooc-{circuit.hash[:8]}-{engine}-{cap_gb}-{uuid.uuid4().hex[:6]}.scope"
    container_id = None
    container_name = f"pg_ooc_{uuid.uuid4().hex[:8]}"
    if engine == "postgres":
        print(f"    [pg] starting container {container_name} --memory={cap_gb}g", file=sys.stderr)
        try:
            container_id = start_pg_container(
                cap_gb, cfg["postgres_image"], cfg["postgres_host_port"], container_name,
            )
        except Exception as e:
            print(f"    [pg] startup FAILED: {e}", file=sys.stderr)
            # Emit a single error row and move on.
            envelope = {"status": "pg_startup_failed", "error": str(e), "runs": []}
            emit_rows(writer, circuit, envelope, engine, cap_gb, method, None,
                      scope_unit, container_id)
            return

    try:
        if cfg["drop_page_cache"]:
            cgroup_metrics.drop_page_cache(use_sudo=True)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            out_path = Path(tmp.name)

        cmd = build_worker_cmd(engine, cap_gb, circuit, method, out_path, cfg,
                               scope_unit, use_systemd)
        per_engine_budget = cfg["timeout_seconds"] * (cfg["n_runs"] + cfg["warmup_runs"] + 2)
        if dry_run:
            print(f"    [dry] would run: {' '.join(cmd)}")
            envelope = {"status": "dry_run", "runs": []}
        else:
            rc, stdout, stderr = run_worker(cmd, per_engine_budget)
            if stderr:
                print(stderr[-400:], file=sys.stderr)
            try:
                envelope = json.loads(out_path.read_text())
            except Exception:
                envelope = {
                    "status": "oom_kill" if rc == 137 else ("timeout" if rc == 124 else "error"),
                    "error": f"worker rc={rc}; no output: {stderr[-200:]}",
                    "runs": [],
                }
        cg = cgroup_snapshot_for(engine, scope_unit, container_id) if not dry_run else None
        emit_rows(writer, circuit, envelope, engine, cap_gb, method, cg,
                  scope_unit, container_id)
    finally:
        if engine == "postgres":
            stop_pg_container(container_name)
        try:
            out_path.unlink()
        except Exception:
            pass


def main():
    cfg = get_ooc_config()

    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=REPO_ROOT / "InferQ" / cfg["circuits_manifest"])
    ap.add_argument("--results-csv", type=Path,
                    default=REPO_ROOT / "InferQ" / cfg["results_dir"] / "results.csv")
    ap.add_argument("--caps-gb", type=str, default=",".join(str(c) for c in cfg["caps_gb"]),
                    help="Comma-separated caps to sweep")
    ap.add_argument("--engines", type=str, default=",".join(cfg["engines"]))
    ap.add_argument("--aer-methods", type=str, default=",".join(cfg["aer_methods"]))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-systemd-run", action="store_true",
                    help="Run worker directly (no cgroup cap) — for smoke tests off-Linux")
    ap.add_argument("--resume", action="store_true",
                    help="Skip (circuit, cap, engine, method) triples already in results-csv")
    args = ap.parse_args()

    caps = [int(x) for x in args.caps_gb.split(",") if x.strip()]
    engines = [x.strip() for x in args.engines.split(",") if x.strip()]
    aer_methods = [x.strip() for x in args.aer_methods.split(",") if x.strip()]

    entries = load_manifest(args.manifest)
    print(f"[run] {len(entries)} circuits × {len(caps)} caps × {len(engines)} engines",
          file=sys.stderr)

    args.results_csv.parent.mkdir(parents=True, exist_ok=True)
    is_new = not args.results_csv.exists()
    seen: set[tuple] = set()
    if args.resume and not is_new:
        with args.results_csv.open() as rf:
            for row in csv.DictReader(rf):
                seen.add((row["circuit_hash"], row["cap_gb"], row["engine"], row["method"]))
    f = args.results_csv.open("a", newline="")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    if is_new:
        writer.writeheader()

    use_systemd = (not args.no_systemd_run) and shutil.which("systemd-run") is not None
    if not use_systemd:
        print("[run] systemd-run not available — running worker without cgroup cap "
              "(results will NOT be memory-constrained)", file=sys.stderr)

    interrupted = {"flag": False}
    def _sigint(*_):
        interrupted["flag"] = True
        print("\n[run] SIGINT received — finishing current triple then stopping", file=sys.stderr)
    signal.signal(signal.SIGINT, _sigint)

    total = 0; skipped = 0
    for ci, circuit in enumerate(entries, 1):
        for cap_gb in caps:
            for engine in engines:
                methods = aer_methods if engine == "aer" else [None]
                for method in methods:
                    key = (circuit.hash, str(cap_gb), engine, method or "")
                    if key in seen:
                        skipped += 1
                        continue
                    total += 1
                    tag = f"[{ci}/{len(entries)}] {circuit.hash[:8]} cap={cap_gb}G {engine}"
                    if method:
                        tag += f"/{method}"
                    print(tag, file=sys.stderr)
                    run_one(circuit, engine, cap_gb, method, cfg, writer,
                            args.dry_run, use_systemd)
                    f.flush()
                if interrupted["flag"]:
                    break
            if interrupted["flag"]:
                break
        if interrupted["flag"]:
            break

    f.close()
    print(f"[run] done: {total} triples executed, {skipped} skipped", file=sys.stderr)


if __name__ == "__main__":
    main()
