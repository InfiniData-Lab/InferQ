"""Orchestrator for OOC / limited-memory RDBMS experiments.

For every (circuit, cap, engine) triple:

1. (postgres only) Start a fresh Docker container with --memory=CAP and a tuned
   postgresql.conf. Wait for TCP accept.
2. Drop the OS page cache.
3. Launch worker.py. Embedded engines run in a fresh Docker worker container
   with --memory=CAP; postgres uses a lightweight client worker because the
   database server container owns the memory cap.
4. Wait for the worker to exit.
5. Read cgroup counters (memory.peak, memory.swap.peak, io.stat) from the
   relevant Docker container.
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
    "engine", "method", "cap_gb", "mode", "run_idx",
    "container_cpus", "duckdb_memory_limit_mb", "duckdb_threads", "sqlite_cache_mb",
    "wall_time_s", "tracemalloc_peak_bytes", "proc_vm_peak_bytes",
    "proc_io_read_bytes", "proc_io_write_bytes",
    "cgroup_mem_peak_bytes", "cgroup_swap_peak_bytes",
    "cgroup_io_read_bytes", "cgroup_io_write_bytes",
    "dbms_temp_bytes_written", "dbms_temp_bytes_read",
    "spill_proxy_bytes", "temp_dir_peak_bytes", "temp_dir_final_bytes",
    "spill_metric_kind",
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
    skip_engines: frozenset[str]

    @classmethod
    def from_json(cls, d: dict) -> "CircuitEntry":
        return cls(
            hash=d["hash"],
            qpy_path=Path(d["qpy_path"]),
            num_qubits=d.get("num_qubits") or 0,
            num_gates=d.get("num_gates") or 0,
            prior_peak_mem_gb=d.get("prior_peak_mem_gb"),
            bin=d.get("bin", ""),
            skip_engines=frozenset(d.get("skip_engines") or []),
        )


# ─────────── Postgres Docker lifecycle ───────────

def start_pg_container(cap_gb: int, image: str, host_port: int, name: str,
                        pg_tuning: Optional[dict[str, int]] = None,
                        container_cpus: float = 0,
                        ready_timeout: int = 60) -> str:
    """Start a fresh Postgres container with memory cap. Returns container id."""
    env_args = []
    for key, env_name in (
        ("shared_buffers_mb", "SHARED_BUFFERS_MB"),
        ("work_mem_mb", "WORK_MEM_MB"),
        ("maint_work_mem_mb", "MAINT_WORK_MEM_MB"),
        ("effective_cache_mb", "EFFECTIVE_CACHE_MB"),
        ("temp_file_limit_mb", "TEMP_FILE_LIMIT_MB"),
        ("max_worker_processes", "MAX_WORKER_PROCESSES"),
        ("max_parallel_workers", "MAX_PARALLEL_WORKERS"),
        ("max_parallel_workers_per_gather", "MAX_PARALLEL_WORKERS_PER_GATHER"),
    ):
        value = (pg_tuning or {}).get(key, 0)
        if key == "temp_file_limit_mb" and not value:
            value = cap_gb * 4096
        if value and int(value) > 0:
            env_args += ["-e", f"{env_name}={int(value)}"]
    cmd = [
        "docker", "run", "-d",  # no --rm: we need logs if it crashes before ready
        "--name", name,
        "--memory", f"{cap_gb}g", "--memory-swap", f"{cap_gb}g",
        "--memory-swappiness", "0",
        "-e", f"CAP_GB={cap_gb}",
        "-e", "POSTGRES_PASSWORD=postgres",
        *env_args,
        "-p", f"{host_port}:5432",
        image,
    ]
    if container_cpus and container_cpus > 0:
        cmd[2:2] = ["--cpus", str(container_cpus)]
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
    out_path: Path, cfg: dict, mode: str,
) -> list[str]:
    """Argv for `python -m scripts.ooc.worker ...` — runner-independent."""
    args = [
        "-m", WORKER_MODULE,
        "--engine", engine,
        "--cap-gb", str(cap_gb),
        "--circuit-qpy", str(circuit.qpy_path),
        "--circuit-hash", circuit.hash,
        "--bin", circuit.bin,
        "--mode", mode,
        "--out-path", str(out_path),
        "--n-runs", str(cfg["n_runs"]),
        "--warmup", str(cfg["warmup_runs"]),
        "--timeout-seconds", str(cfg["timeout_seconds"]),
        "--tmp-root", cfg["tmp_root"],
        "--container-cpus", str(cfg.get("container_cpus") or 0),
        "--duckdb-memory-mb", str(cfg["duckdb_memory_mb"]),
        "--duckdb-pad-mb", str(cfg["duckdb_pad_mb"]),
        "--sqlite-cache-mb", str(cfg["sqlite_cache_mb"]),
        "--pg-host", "127.0.0.1",
        "--pg-port", str(cfg["postgres_host_port"]),
    ]
    if engine == "duckdb":
        args += ["--threads", str(cfg["duckdb_threads"])]
    if engine == "aer" and aer_method:
        args += ["--aer-method", aer_method, "--aer-pad-mb", str(cfg["aer_max_memory_pad_mb"])]
    return args


def build_worker_cmd(
    engine: str, cap_gb: int, circuit: CircuitEntry, aer_method: Optional[str],
    out_path: Path, cfg: dict, container_name: str, runner: str, mode: str,
) -> list[str]:
    """Compose the full subprocess argv for one worker invocation.

    runner == "docker": wraps the worker in a memory-capped container.
    runner == "none":   direct exec, no cap (smoke test only — DO NOT use for
                        paper runs; results will not be memory-constrained).
    """
    worker_args = build_worker_args(engine, cap_gb, circuit, aer_method, out_path, cfg, mode)

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
    container_cpus = float(cfg.get("container_cpus") or 0)
    if container_cpus > 0:
        docker_cmd += ["--cpus", str(container_cpus)]
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


def _flatten_error(msg: str) -> str:
    """Collapse newlines/carriage returns so error_msg stays on one CSV line.

    Postgres startup logs (captured via `docker logs --tail=40`) contain
    literal newlines that, while valid in a quoted CSV field, make grep/cat
    treat each line of the log as a separate file line.
    """
    if not msg:
        return ""
    return (msg.replace("\\", "\\\\")
               .replace("\r\n", "\\n")
               .replace("\n", "\\n")
               .replace("\r", "\\n"))


def emit_rows(writer: csv.DictWriter, circuit: CircuitEntry, envelope: dict,
              engine: str, cap_gb: int, method: Optional[str], mode: str,
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
        "mode": envelope.get("mode", mode),
        "container_cpus": envelope.get("container_cpus", ""),
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
            "proc_io_read_bytes": None, "proc_io_write_bytes": None,
            "dbms_temp_bytes_written": None, "dbms_temp_bytes_read": None,
            "spill_proxy_bytes": None, "temp_dir_peak_bytes": None,
            "temp_dir_final_bytes": None, "spill_metric_kind": "",
            "status": envelope.get("status", "error"),
            "error_msg": _flatten_error(envelope.get("error", "")),
        })
        return
    for r in runs:
        writer.writerow({**base,
            "run_idx": r.get("run_idx"),
            "wall_time_s": r.get("wall_time_s"),
            "duckdb_memory_limit_mb": r.get("duckdb_memory_limit_mb", ""),
            "duckdb_threads": r.get("duckdb_threads", ""),
            "sqlite_cache_mb": r.get("sqlite_cache_mb", ""),
            "tracemalloc_peak_bytes": r.get("tracemalloc_peak_bytes"),
            "proc_vm_peak_bytes": r.get("proc_vm_peak_bytes"),
            "proc_io_read_bytes": r.get("proc_io_read_bytes"),
            "proc_io_write_bytes": r.get("proc_io_write_bytes"),
            "dbms_temp_bytes_written": r.get("spill_bytes_written"),
            "dbms_temp_bytes_read": r.get("spill_bytes_read"),
            "spill_proxy_bytes": r.get("spill_proxy_bytes"),
            "temp_dir_peak_bytes": r.get("temp_dir_peak_bytes"),
            "temp_dir_final_bytes": r.get("temp_dir_final_bytes"),
            "spill_metric_kind": r.get("spill_metric_kind", ""),
            "status": r.get("status", "unknown"),
            "error_msg": _flatten_error(r.get("error", "")),
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
    cfg: dict, writer: csv.DictWriter, dry_run: bool, runner: str, mode: str,
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
                {
                    "shared_buffers_mb": cfg.get("postgres_shared_buffers_mb", 0),
                    "work_mem_mb": cfg.get("postgres_work_mem_mb", 0),
                    "maint_work_mem_mb": cfg.get("postgres_maint_work_mem_mb", 0),
                    "effective_cache_mb": cfg.get("postgres_effective_cache_mb", 0),
                    "temp_file_limit_mb": cfg.get("postgres_temp_file_limit_mb", 0),
                    "max_worker_processes": cfg.get("postgres_max_worker_processes", 1),
                    "max_parallel_workers": cfg.get("postgres_max_parallel_workers", 1),
                    "max_parallel_workers_per_gather": cfg.get("postgres_max_parallel_workers_per_gather", 0),
                },
                container_cpus=float(cfg.get("container_cpus") or 0),
            )
        except Exception as e:
            print(f"    [pg] startup FAILED: {e}", file=sys.stderr)
            envelope = {"status": "pg_startup_failed", "error": str(e), "runs": []}
            emit_rows(writer, circuit, envelope, engine, cap_gb, method, mode,
                      None, worker_container_name, pg_container_id)
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
                               worker_container_name, runner, mode)
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
            if engine == "postgres":
                # The worker is a separate container from postgres. Only the
                # host-side read of the postgres container's cgroup is correct;
                # the worker's self-report and sampler measure the wrong cgroup.
                # If the host read failed (e.g. no sudo), prefer null cgroup
                # values over a wrong-container number.
                cg = host_cg
            else:
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
        emit_rows(writer, circuit, envelope, engine, cap_gb, method, mode, cg,
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
    ap.add_argument("--mode", choices=["monolithic", "monolithic_materialized", "split"],
                    default=os.getenv("OOC_QUERY_MODE", "split"),
                    help="Query execution mode (default from OOC_QUERY_MODE or 'split'). "
                         "Each row's mode is recorded; resume keys distinguish modes so "
                         "monolithic and split runs can share a CSV without colliding.")
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
    _migrate_results_header(args.results_csv)
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
                    seen.add((row["circuit_hash"], row["cap_gb"], row["engine"],
                              row["method"], row.get("mode") or "monolithic"))
            with args.results_csv.open("w", newline="") as wf:
                w = csv.DictWriter(wf, fieldnames=fields)
                w.writeheader()
                w.writerows(kept_rows)
            print(f"[run] stripped {stripped} rows with status in {rerun_statuses}",
                  file=sys.stderr)
        else:
            with args.results_csv.open() as rf:
                for row in csv.DictReader(rf):
                    seen.add((row["circuit_hash"], row["cap_gb"], row["engine"],
                              row["method"], row.get("mode") or "monolithic"))
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
                if engine in circuit.skip_engines:
                    skipped += 1
                    continue
                methods = aer_methods if engine == "aer" else [None]
                for method in methods:
                    key = (circuit.hash, str(cap_gb), engine, method or "", args.mode)
                    if key in seen:
                        skipped += 1
                        continue
                    total += 1
                    tag = f"[{ci}/{len(entries)}] {circuit.hash[:8]} cap={cap_gb}G {engine} mode={args.mode}"
                    if method:
                        tag += f"/{method}"
                    print(tag, file=sys.stderr)
                    run_one(circuit, engine, cap_gb, method, cfg, writer,
                            args.dry_run, runner, args.mode)
                    f.flush()
                if interrupted["flag"]:
                    break
            if interrupted["flag"]:
                break
        if interrupted["flag"]:
            break

    f.close()
    print(f"[run] done: {total} triples executed, {skipped} skipped", file=sys.stderr)


def _migrate_results_header(path: Path) -> None:
    """Rewrite an existing results CSV to the current schema before appending.

    The spill instrumentation evolved from a single overloaded temp-byte field
    to explicit process-I/O and temp-directory columns. Appending new rows under
    an old header would silently corrupt the CSV shape, so normalize once here.
    """
    if not path.exists():
        return
    with path.open(newline="") as rf:
        reader = csv.DictReader(rf)
        old_fields = reader.fieldnames or []
        if old_fields == CSV_FIELDS:
            return
        rows = list(reader)
    with path.open("w", newline="") as wf:
        writer = csv.DictWriter(wf, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[run] migrated results CSV schema: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
