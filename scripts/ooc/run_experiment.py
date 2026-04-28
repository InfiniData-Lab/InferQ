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
        "docker", "run", "-d",  # no --rm: we need logs if it crashes before ready
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
        # Step 1: TCP port open?
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            try:
                s.connect(("127.0.0.1", host_port))
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
                continue
        # Step 2: Postgres protocol ready? (TCP open ≠ PG accepting queries.)
        try:
            import psycopg2
            test_con = psycopg2.connect(
                host="127.0.0.1", port=host_port,
                user="postgres", password="postgres",
                dbname="postgres", connect_timeout=2,
            )
            test_con.close()
            return cid
        except Exception:
            time.sleep(0.5)
    # Timed out — grab logs for debugging before failing.
    logs = subprocess.run(["docker", "logs", "--tail=40", cid], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
    subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raise RuntimeError(f"Postgres did not become ready in {ready_timeout}s. Logs:\n{logs}")


def stop_pg_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────── Worker invocation ───────────

def build_worker_args(
    engine: str, cap_gb: int, circuit: CircuitEntry, aer_method: Optional[str],
    out_path: Path, cfg: dict,
) -> list[str]:
    """Argv for `python -m scripts.ooc.worker ...` — runner-independent."""
    args = [
        "-m", WORKER_MODULE,
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
        args += ["--aer-method", aer_method, "--aer-pad-mb", str(cfg["aer_max_memory_pad_mb"])]
    return args


def build_worker_cmd(
    engine: str, cap_gb: int, circuit: CircuitEntry, aer_method: Optional[str],
    out_path: Path, cfg: dict, container_name: str, runner: str,
) -> list[str]:
    """Compose the full subprocess argv for one worker invocation.

    runner == "docker": wraps the worker in a memory-capped container.
    runner == "none":   direct exec, no cap (smoke test only — DO NOT use for
                        paper runs; results will not be memory-constrained).
    """
    worker_args = build_worker_args(engine, cap_gb, circuit, aer_method, out_path, cfg)

    if runner == "none":
        return [sys.executable] + worker_args

    if runner != "docker":
        raise ValueError(f"unknown runner {runner!r}")

    # For Postgres, enforcement is on the postgres container — the worker
    # container only runs psycopg2 + EXPLAIN, so a generous cap is fine.
    container_cap_gb = cap_gb if engine != "postgres" else max(cap_gb, 60)
    repo_root = str(REPO_ROOT)
    inferq_root = str(INFERQ_ROOT)
    iqs_root = str(REPO_ROOT / "Infinidata-rdbms-simulator")
    tmp_root = cfg["tmp_root"]

    # No --rm: we read the container's cgroup from the host AFTER the worker
    # process exits but BEFORE removing the container (cgroup is destroyed
    # when Docker drops its last reference). _stop_container() in run_one's
    # finally block handles cleanup.
    docker_cmd = [
        "docker", "run",
        "--name", container_name,
        "--memory", f"{container_cap_gb}g",
        "--memory-swap", f"{container_cap_gb}g",
        "--memory-swappiness", "0",
        # Host network so we reach the postgres container's published port and
        # so the cgroup/memory namespace stays simple. Embedded engines do no
        # network anyway.
        "--network", "host",
        # cgroupns=host + cgroup bind-mount: the worker self-reports its own
        # cgroup peak from /proc/self/cgroup, and the path resolves the same
        # inside as on the host.
        "--cgroupns", "host",
    ]
    # Bind-mount /sys/fs/cgroup. On hybrid v1+v2 hosts, sub-mounts (memory,
    # cpu, unified, …) are NOT propagated by a single `-v` bind, so the worker
    # would see only the empty parent tmpfs. Add explicit mounts for any v1
    # controllers and the v2 unified hierarchy that exist on this host.
    docker_cmd += ["-v", "/sys/fs/cgroup:/sys/fs/cgroup:ro"]
    for sub in ("memory", "unified", "cpu,cpuacct", "cpu", "blkio", "pids"):
        host_path = Path("/sys/fs/cgroup") / sub
        if host_path.exists():
            docker_cmd += ["-v", f"{host_path}:{host_path}:ro"]
    docker_cmd += [
        "-v", f"{repo_root}:{repo_root}:ro",
        "-v", f"{tmp_root}:{tmp_root}",
        "-v", "/tmp:/tmp",
        "-e", f"PYTHONPATH={iqs_root}:{inferq_root}",
        "-w", inferq_root,
        cfg["worker_image"],
    ]
    return docker_cmd + worker_args


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

def cgroup_snapshot_for(engine: str, worker_container: Optional[str],
                        pg_container_id: Optional[str]
                        ) -> Optional[cgroup_metrics.CgroupSnapshot]:
    """Best-effort host-side cgroup read.

    For postgres, the postgres container holds the cap. For embedded engines,
    the worker container itself holds the cap. The container's cgroup
    directory may be torn down right after exit (especially with --rm) — when
    that happens the orchestrator falls back to the worker self-report.
    """
    target = pg_container_id if engine == "postgres" else worker_container
    if not target:
        return None
    path = cgroup_metrics.find_docker_cgroup(target)
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


def _stop_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_one(
    circuit: CircuitEntry, engine: str, cap_gb: int, method: Optional[str],
    cfg: dict, writer: csv.DictWriter, dry_run: bool, runner: str,
) -> None:
    uniq = uuid.uuid4().hex[:8]
    pg_container_name = f"pg_ooc_{uniq}"
    worker_container_name = f"ooc_worker_{circuit.hash[:8]}_{engine}_{cap_gb}_{uniq}"
    pg_container_id = None
    if engine == "postgres":
        print(f"    [pg] starting container {pg_container_name} --memory={cap_gb}g", file=sys.stderr)
        try:
            pg_container_id = start_pg_container(
                cap_gb, cfg["postgres_image"], cfg["postgres_host_port"], pg_container_name,
            )
        except Exception as e:
            print(f"    [pg] startup FAILED: {e}", file=sys.stderr)
            envelope = {"status": "pg_startup_failed", "error": str(e), "runs": []}
            emit_rows(writer, circuit, envelope, engine, cap_gb, method, None,
                      worker_container_name, pg_container_id)
            return

    try:
        if cfg["drop_page_cache"]:
            cgroup_metrics.drop_page_cache(use_sudo=True)

        # The output JSON is created on the host and written by the worker
        # inside the docker container. Container UID may differ from host UID
        # (rootless docker, userns-remap), so put the file under OOC_TMP_ROOT
        # (already bind-mounted rw) and make it world-writable.
        out_dir = Path(cfg["tmp_root"]) / "orchestrator_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          dir=str(out_dir)) as tmp:
            out_path = Path(tmp.name)
        try:
            os.chmod(out_path, 0o666)
        except OSError:
            pass

        cmd = build_worker_cmd(engine, cap_gb, circuit, method, out_path, cfg,
                               worker_container_name, runner)
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
        # Cgroup peak strategy:
        #   - For postgres: read the postgres container's cgroup; that's where
        #     the cap is enforced and the container is still alive here.
        #   - For embedded engines: the worker container exited already and
        #     its cgroup directory may be gone. Prefer the worker self-report
        #     (read from inside the container before exit) and the polling
        #     sampler. Take the max as the true peak.
        cg = None
        host_cg = None
        if not dry_run:
            # Host-side cgroup read. For postgres: the postgres container
            # itself. For embedded engines: the worker container, which is
            # still in Exited state (we drop --rm) so its cgroup persists
            # until we docker-rm it.
            host_cg = cgroup_snapshot_for(
                engine, worker_container_name if runner == "docker" else None,
                pg_container_id,
            )
            wc = envelope.get("cgroup", {}) if isinstance(envelope.get("cgroup"), dict) else {}
            sampled_peak = envelope.get("cgroup_sampled_peak_bytes") or 0
            wc_peak = wc.get("cgroup_mem_peak_bytes") or 0
            host_peak = host_cg.memory_peak_bytes if host_cg else 0
            # Three independent peak sources. Take the max — they all observe
            # the same cgroup, so the largest is the most reliable high-water.
            best_peak = max(int(wc_peak), int(sampled_peak), int(host_peak))
            if best_peak > 0 or wc or host_cg:
                cg = cgroup_metrics.CgroupSnapshot(
                    memory_peak_bytes=best_peak,
                    memory_swap_peak_bytes=max(
                        int(wc.get("cgroup_swap_peak_bytes", 0) or 0),
                        int(host_cg.memory_swap_peak_bytes if host_cg else 0),
                    ),
                    io_read_bytes=max(
                        int(wc.get("cgroup_io_read_bytes", 0) or 0),
                        int(host_cg.io_read_bytes if host_cg else 0),
                    ),
                    io_write_bytes=max(
                        int(wc.get("cgroup_io_write_bytes", 0) or 0),
                        int(host_cg.io_write_bytes if host_cg else 0),
                    ),
                    cgroup_path=(host_cg.cgroup_path if host_cg
                                 else wc.get("cgroup_path", "")),
                )
        emit_rows(writer, circuit, envelope, engine, cap_gb, method, cg,
                  worker_container_name, pg_container_id)
    finally:
        # Clean up any straggler worker container (--rm should have removed it,
        # but if `docker run` was force-killed, the container can survive).
        if runner == "docker":
            _stop_container(worker_container_name)
        if engine == "postgres":
            stop_pg_container(pg_container_name)
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
    ap.add_argument("--runner", choices=["docker", "none"], default=None,
                    help="Embedded-engine runtime: 'docker' (cap enforced by --memory) "
                         "or 'none' (direct exec, no cap — smoke tests only). "
                         "Defaults to OOC_RUNNER / config.")
    ap.add_argument("--no-systemd-run", action="store_true",
                    help="Deprecated alias for --runner=none.")
    ap.add_argument("--resume", action="store_true",
                    help="Skip (circuit, cap, engine, method) triples already in results-csv")
    ap.add_argument("--rerun-statuses", type=str, default="",
                    help="Comma-separated statuses to re-run even when already in the CSV "
                         "(e.g. 'error,pg_startup_failed'). Matching rows are stripped from "
                         "the CSV before the run so results stay clean.")
    args = ap.parse_args()

    caps = [int(x) for x in args.caps_gb.split(",") if x.strip()]
    engines = [x.strip() for x in args.engines.split(",") if x.strip()]
    aer_methods = [x.strip() for x in args.aer_methods.split(",") if x.strip()]
    rerun_statuses: set[str] = {s.strip() for s in args.rerun_statuses.split(",") if s.strip()}

    # Ensure OOC_TMP_ROOT exists and is writable by any container UID.
    # Worker containers may run as a remapped/rootless UID, so 0o1777 (sticky,
    # world-writable) is the safest setting for paths shared across containers.
    tmp_root = Path(cfg["tmp_root"])
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(tmp_root, 0o1777)
    except OSError as e:
        print(f"[run] warning: chmod 1777 {tmp_root} failed: {e}", file=sys.stderr)

    entries = load_manifest(args.manifest)
    print(f"[run] {len(entries)} circuits × {len(caps)} caps × {len(engines)} engines",
          file=sys.stderr)

    args.results_csv.parent.mkdir(parents=True, exist_ok=True)
    is_new = not args.results_csv.exists()
    seen: set[tuple] = set()
    if args.resume and not is_new:
        if rerun_statuses:
            # Strip rows whose status should be retried, rewrite the CSV, then
            # build `seen` from what remains so those triples are re-queued.
            kept_rows: list[dict] = []
            stripped = 0
            with args.results_csv.open() as rf:
                reader = csv.DictReader(rf)
                fields = reader.fieldnames or CSV_FIELDS
                for row in reader:
                    if row.get("status") in rerun_statuses:
                        stripped += 1
                        continue
                    kept_rows.append(row)
                    seen.add((row["circuit_hash"], row["cap_gb"], row["engine"], row["method"]))
            with args.results_csv.open("w", newline="") as wf:
                w = csv.DictWriter(wf, fieldnames=fields)
                w.writeheader()
                w.writerows(kept_rows)
            print(f"[run] stripped {stripped} rows with status in {rerun_statuses}",
                  file=sys.stderr)
        else:
            with args.results_csv.open() as rf:
                for row in csv.DictReader(rf):
                    seen.add((row["circuit_hash"], row["cap_gb"], row["engine"], row["method"]))
    f = args.results_csv.open("a", newline="")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    if is_new:
        writer.writeheader()

    runner = args.runner or cfg.get("runner", "docker")
    if args.no_systemd_run:
        runner = "none"
    if runner == "docker":
        if shutil.which("docker") is None:
            print("[run] docker not on PATH — falling back to runner=none (NO cap enforcement)",
                  file=sys.stderr)
            runner = "none"
        else:
            # Verify the worker image exists; surface a clear error rather than
            # failing on the first triple.
            check = subprocess.run(
                ["docker", "image", "inspect", cfg["worker_image"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if check.returncode != 0:
                raise SystemExit(
                    f"[run] worker image {cfg['worker_image']!r} not found. "
                    f"Build it first: ./scripts/ooc/docker/worker/build.sh"
                )
    if runner == "none":
        print("[run] runner=none — workers will run directly with NO memory cap. "
              "Results will not be paper-ready.", file=sys.stderr)

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
                            args.dry_run, runner)
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
