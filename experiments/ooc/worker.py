"""Single-engine OOC worker.

Runs one engine (postgres, duckdb, sqlite, or aer) on one circuit N times under
an already-established memory cap. In normal experiment runs the orchestrator
places embedded engines in a memory-capped Docker worker container and places
Postgres in a memory-capped server container.

The process does NOT set its own memory cap — enforcement is external. It just
runs the work and records what happened.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

# or `python -m experiments.ooc.worker`.
# Imported after the sys.path bootstrap above, which is what makes InferQ
# importable when this file is run directly as `python worker.py`.
from experiments._common import drain_cursor
from inferq.sql.query_modes import (
    count_iqs_ctes,
    materialize_iqs_ctes,
    split_iqs_query_per_step,
)


def _resolve_own_cgroup_paths() -> tuple[Path | None, Path | None]:
    """Parse /proc/self/cgroup → (v2_path, v1_mem_path).

    Handles three runtime contexts:
      1. Direct host process — paths in /proc/self/cgroup map straight to
         /sys/fs/cgroup{,/unified} or /sys/fs/cgroup/memory.
      2. Docker with cgroupns=host + cgroup mount — same as case 1; the
         container sees the host's cgroup tree at the host's paths.
      3. Docker with cgroupns=private — /proc/self/cgroup says `0::/`
         and the cgroup files are at the root of /sys/fs/cgroup.

    On hybrid v1+v2 hosts, v1 controllers may point to a parent slice
    (user.slice) rather than the per-container cgroup. Reading
    memory.max_usage_in_bytes from there yields a session-wide peak, not
    the worker's. Callers MUST prefer the v2 path.
    """
    v1_mem_path: Path | None = None
    v2_path: Path | None = None

    def _looks_like_cgroup_dir(p: Path, marker: str) -> bool:
        return (p / marker).exists()

    try:
        with open("/proc/self/cgroup") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except Exception:
        lines = []

    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hier_id, controllers, rel_raw = parts
        rel = rel_raw.lstrip("/")
        if hier_id == "0":
            for v2_root in (Path("/sys/fs/cgroup/unified"), Path("/sys/fs/cgroup")):
                candidate = v2_root / rel if rel else v2_root
                if candidate.exists() and _looks_like_cgroup_dir(
                    candidate, "cgroup.controllers"
                ):
                    v2_path = candidate
                    break
        elif "memory" in controllers.split(","):
            candidate = Path("/sys/fs/cgroup/memory") / rel if rel else Path("/sys/fs/cgroup/memory")
            if candidate.exists() and _looks_like_cgroup_dir(
                candidate, "memory.limit_in_bytes"
            ):
                v1_mem_path = candidate

    # Container-with-private-cgroupns fallback: /proc/self/cgroup may report
    # `0::/` and the cgroup files live at the root of /sys/fs/cgroup.
    if v2_path is None:
        root = Path("/sys/fs/cgroup")
        if _looks_like_cgroup_dir(root, "cgroup.controllers") or (
            root / "memory.current"
        ).exists():
            v2_path = root
    if v1_mem_path is None:
        v1_root = Path("/sys/fs/cgroup/memory")
        if _looks_like_cgroup_dir(v1_root, "memory.limit_in_bytes"):
            v1_mem_path = v1_root
    return v2_path, v1_mem_path


def _v2_has_memory_accounting(v2_path: Path) -> bool:
    """True iff the v2 cgroup actually carries the memory controller.

    On hybrid v1+v2 hosts the v2 unified hierarchy is often a pure tracking
    hierarchy with no controllers attached (Docker on cgroupfs/v1 keeps
    memory accounting in /sys/fs/cgroup/memory/). In that case neither
    memory.peak nor memory.current exist on the v2 path; the caller must
    fall back to v1.
    """
    return (v2_path / "memory.current").exists() or (v2_path / "memory.peak").exists()


def _read_own_cgroup_v2() -> dict:
    """Read cgroup memory/IO counters for this process from inside the scope.

    Prefers v2 *only if it carries the memory controller*; otherwise reads
    v1 memory. /proc/self/cgroup may list both hierarchies for the same
    process; the one with live memory accounting is authoritative.

    Called just before the worker exits so the cgroup directory still exists.
    """
    result: dict = {}
    v2_path, v1_mem_path = _resolve_own_cgroup_paths()
    v2_active = v2_path is not None and _v2_has_memory_accounting(v2_path)

    if v2_active:
        result["cgroup_path"] = str(v2_path)
        peak = _read_int_file(v2_path / "memory.peak")
        if peak <= 0:
            peak = _read_int_file(v2_path / "memory.current")
        if peak > 0:
            result["cgroup_mem_peak_bytes"] = peak
        swap = _read_int_file(v2_path / "memory.swap.peak")
        if swap <= 0:
            swap = _read_int_file(v2_path / "memory.swap.current")
        result["cgroup_swap_peak_bytes"] = swap
        rb, wb = _parse_io_stat_file(v2_path / "io.stat")
        result["cgroup_io_read_bytes"] = rb
        result["cgroup_io_write_bytes"] = wb
    elif v1_mem_path is not None:
        result["cgroup_path"] = str(v1_mem_path)
        mem_peak = _read_int_file(v1_mem_path / "memory.max_usage_in_bytes")
        if mem_peak > 0:
            result["cgroup_mem_peak_bytes"] = mem_peak
        # memory.memsw.max_usage_in_bytes is the COMBINED mem+swap peak.
        # Pure swap peak = memsw_peak - mem_peak (clamped at 0). With
        # --memory-swap=cap (== --memory) this should always be 0.
        memsw_peak = _read_int_file(v1_mem_path / "memory.memsw.max_usage_in_bytes")
        if memsw_peak > 0 and mem_peak > 0:
            result["cgroup_swap_peak_bytes"] = max(0, memsw_peak - mem_peak)
        # I/O on v1 is on the blkio controller, separate from the memory
        # cgroup. Locate via /proc/self/cgroup -> /sys/fs/cgroup/blkio/<rel>.
        v1_blkio = _resolve_own_v1_path("blkio")
        if v1_blkio is not None:
            for name in ("blkio.throttle.io_service_bytes", "blkio.io_service_bytes"):
                rb, wb = _parse_v1_blkio_io_service_bytes(v1_blkio / name)
                if rb or wb:
                    result["cgroup_io_read_bytes"] = rb
                    result["cgroup_io_write_bytes"] = wb
                    break
    return result


def _read_int_file(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def _parse_io_stat_file(path: Path) -> tuple[int, int]:
    """Parse cgroup v2 io.stat: lines of `<major:minor> rbytes=… wbytes=…`."""
    rb = wb = 0
    try:
        for line in path.read_text().splitlines():
            for field in line.split()[1:]:
                if "=" not in field:
                    continue
                k, v = field.split("=", 1)
                if k == "rbytes":
                    rb += int(v)
                elif k == "wbytes":
                    wb += int(v)
    except Exception:
        pass
    return rb, wb


def _parse_v1_blkio_io_service_bytes(path: Path) -> tuple[int, int]:
    """Parse cgroup v1 blkio.io_service_bytes (or blkio.throttle.io_service_bytes).

    Format: `<major:minor> <Read|Write|Sync|Async|Discard|Total> <bytes>`
    plus a final `Total <total bytes>` line. We only sum Read/Write to avoid
    double-counting against Sync/Async/Total.
    """
    rb = wb = 0
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            kind = parts[1] if ":" in parts[0] else parts[0]
            try:
                value = int(parts[-1])
            except ValueError:
                continue
            if kind == "Read":
                rb += value
            elif kind == "Write":
                wb += value
    except Exception:
        pass
    return rb, wb


def _resolve_own_v1_path(controller: str) -> Path | None:
    """Find the v1 cgroup path for a specific controller (e.g. 'blkio')."""
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                parts = line.strip().split(":", 2)
                if len(parts) != 3:
                    continue
                if controller in parts[1].split(","):
                    candidate = Path(f"/sys/fs/cgroup/{controller}") / parts[2].lstrip("/")
                    return candidate if candidate.exists() else None
    except Exception:
        pass
    return None


class _CgroupMemSampler(threading.Thread):
    """Polls the cgroup's "current memory" counter and records the peak.

    Independent cross-check against memory.peak / max_usage_in_bytes — also
    gives a peak on kernels < 5.19 where memory.peak is unavailable.
    Auto-detects whether to read v2 `memory.current` or v1 `memory.usage_in_bytes`
    based on which file exists at the supplied path.
    """
    def __init__(self, cgroup_path: Path, interval_s: float = 0.1):
        super().__init__(daemon=True)
        self.cgroup_path = cgroup_path
        self.interval = interval_s
        self.peak_bytes = 0
        # NOTE: do NOT name this `_stop` — `threading.Thread._stop` is an
        # internal method called during thread cleanup. Shadowing it with an
        # Event instance causes `TypeError: 'Event' object is not callable`
        # when the runtime tries to invoke `self._stop()`.
        self._stop_event = threading.Event()
        # Pick the correct file ONCE at start time. v2 vs v1 is determined by
        # which name exists in the supplied directory.
        v2_current = cgroup_path / "memory.current"
        v1_current = cgroup_path / "memory.usage_in_bytes"
        self.sample_path = v2_current if v2_current.exists() else v1_current

    def run(self):
        while not self._stop_event.is_set():
            v = _read_int_file(self.sample_path)
            if v > self.peak_bytes:
                self.peak_bytes = v
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
        self.join(timeout=2)


def _warn_if_tmpfs(path: Path) -> None:
    """Print a loud warning if the tmp_root resolves to a tmpfs mount.

    tmpfs writes are RAM-backed: they count against the cgroup memory cap and
    do not appear in cgroup_io_write_bytes, breaking spill measurement entirely.
    """
    try:
        out = subprocess.run(
            ["findmnt", "-no", "FSTYPE", "-T", str(path)],
            text=True, capture_output=True, timeout=2,
        )
        fstype = (out.stdout or "").strip()
        if fstype in ("tmpfs", "ramfs"):
            print(
                f"\n!!! tmp_root={path} is on {fstype} — spill writes will be "
                f"RAM-backed and invisible to cgroup_io_write_bytes. Set "
                f"OOC_TMP_ROOT to a real block-device path (NVMe).\n",
                file=sys.stderr, flush=True,
            )
    except Exception:
        pass


def _read_vm_peak_bytes() -> int:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmPeak:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError):
        pass
    return 0


def _read_proc_io_bytes() -> tuple[int | None, int | None]:
    """Return this process's physical read/write byte counters from /proc/self/io.

    Linux reports `read_bytes` and `write_bytes` as storage-layer I/O caused by
    the process. These are not DBMS-native spill counters, but they are the
    cleanest per-run spill proxy for embedded SQLite/DuckDB because cgroup I/O is
    cumulative over the whole worker container and SQLite has no query-level
    temp-byte API in Python's stdlib wrapper.
    """
    vals: dict[str, int] = {}
    try:
        with open("/proc/self/io") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                if k in {"read_bytes", "write_bytes"}:
                    vals[k] = int(v.strip())
    except (FileNotFoundError, OSError, ValueError):
        return None, None
    return vals.get("read_bytes"), vals.get("write_bytes")


def _counter_delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return max(0, after - before)


def _load_qiskit_circuit(qpy_path: str):
    from qiskit.qpy import load

    with open(qpy_path, "rb") as f:
        circuits = load(f)
    if not circuits:
        raise RuntimeError(f"no circuit found in {qpy_path}")
    return circuits[0]


def _build_iqs_query(qc) -> tuple[str, int, int]:
    """Transpile to IQS-supported basis, build the IQS circuit, emit SQL.

    Returns (query, num_qubits, num_gates). Query generation itself is expensive
    (opt_einsum path finding) but is NOT counted in the timed runs.
    """
    from InfiniQuantumSim.TLtensor import Gate as IQSGate
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit
    from InfiniQuantumSim.utils import INDICES
    from qiskit import transpile

    transpiled = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)
    num_qubits = transpiled.num_qubits
    estimated = num_qubits + 3 * len(transpiled.data)
    if estimated >= len(INDICES):
        raise RuntimeError(f"circuit exceeds IQS index budget: {estimated} >= {len(INDICES)}")

    iqs = IQSQuantumCircuit(num_qubits=num_qubits)
    for instr in transpiled.data:
        op = instr.operation
        if op.name in ("barrier", "measure"):
            continue
        qubits = [transpiled.find_bit(q).index for q in instr.qubits]
        mat = op.to_matrix()
        if len(qubits) == 1:
            tensor = mat
        elif len(qubits) == 2:
            tensor = mat.reshape(2, 2, 2, 2)
        else:
            raise RuntimeError(f"unsupported {op.name} on {len(qubits)} qubits")
        gate_name = f"{op.name}_{id(op)}" if op.params else op.name
        iqs.add_gate(IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2)))

    return iqs.to_query(complex=True), num_qubits, len(iqs.gates)


def _build_iqs_query_with_timeout(qc, timeout_seconds: int) -> tuple[str, int, int]:
    """Run _build_iqs_query in a daemon thread with a wall-clock deadline.

    opt_einsum path-finding inside to_query() has no internal timeout and can
    hang for hours on certain circuit structures. The daemon thread is abandoned
    if it exceeds the deadline (Python threads are not killable), but it will be
    reaped when the worker process exits.
    """
    result: dict = {}
    exc_holder: dict = {}

    def _run():
        try:
            result["out"] = _build_iqs_query(qc)
        except Exception as e:
            exc_holder["exc"] = e
            exc_holder["tb"] = traceback.format_exc()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)

    if t.is_alive():
        raise TimeoutError(
            f"query generation timed out after {timeout_seconds}s (opt_einsum path-finding)"
        )
    if "exc" in exc_holder:
        raise exc_holder["exc"]
    return result["out"]


# ─────────────────── Per-engine run wrappers ────────────────────

class _PgTempDirSampler(threading.Thread):
    """Poll postgres's `base/pgsql_tmp` total bytes via a side connection.

    Uses pg_ls_dir + pg_stat_file (both available since PG 12, both require
    superuser — which the `postgres` role is). Top-level only: per-backend
    spill files are flat names like `pgsql_tmp<pid>.<seq>`. Parallel-worker
    shared filesets would land in subdirectories, but the orchestrator pins
    `max_parallel_workers_per_gather=0` so they shouldn't appear.
    """
    _SQL = (
        "SELECT COALESCE(SUM((pg_stat_file('base/pgsql_tmp/' || name, true)).size), 0)::bigint "
        "FROM pg_ls_dir('base/pgsql_tmp', true, false) AS name"
    )

    def __init__(self, *, interval_s: float = 0.25, **conn_kwargs):
        super().__init__(daemon=True)
        self.conn_kwargs = conn_kwargs
        self.interval = interval_s
        self.peak_bytes = 0
        # See _CgroupMemSampler for why this is _stop_event, not _stop.
        self._stop_event = threading.Event()

    def run(self):
        try:
            import psycopg2
            con = psycopg2.connect(**self.conn_kwargs)
            con.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        except Exception:
            return
        cur = con.cursor()
        while not self._stop_event.is_set():
            try:
                cur.execute(self._SQL)
                row = cur.fetchone()
                v = int(row[0]) if row and row[0] is not None else 0
                if v > self.peak_bytes:
                    self.peak_bytes = v
            except Exception:
                pass
            self._stop_event.wait(self.interval)
        try:
            cur.close()
            con.close()
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()
        if self.ident is not None:
            self.join(timeout=2)


def _run_postgres(query: str, args, run_idx: str, result: dict) -> None:
    import psycopg2

    con = psycopg2.connect(
        host=args.pg_host, port=args.pg_port,
        user=args.pg_user, password=args.pg_password, dbname=args.pg_db,
    )
    con.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sampler = _PgTempDirSampler(
        host=args.pg_host, port=args.pg_port,
        user=args.pg_user, password=args.pg_password, dbname=args.pg_db,
        interval_s=0.25,
    )
    try:
        cur.execute("SET statement_timeout = %s", (args.timeout_seconds * 1000,))
        cur.execute("SET log_temp_files = 0")

        if args.mode == "split":
            statements = split_iqs_query_per_step(query)
        elif args.mode == "monolithic_materialized":
            statements = [materialize_iqs_ctes(query)]
        else:
            statements = [query]

        sampler.start()
        tic = time.perf_counter()
        total_temp_written = 0
        total_temp_read = 0
        total_exec_ms = 0.0
        total_plan_ms = 0.0
        largest_cte_bytes = 0
        total_cte_bytes = 0
        for stmt in statements:
            explain_q = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {stmt}"
            cur.execute(explain_q)
            plan = cur.fetchone()[0]
            total_temp_written += _pg_sum_plan(plan, "Temp Written Blocks")
            total_temp_read += _pg_sum_plan(plan, "Temp Read Blocks")
            if isinstance(plan, list) and plan:
                total_exec_ms += plan[0].get("Execution Time") or 0
                total_plan_ms += plan[0].get("Planning Time") or 0
            m = _CREATE_TABLE_KX.search(stmt)
            if m:
                try:
                    cur.execute("SELECT pg_total_relation_size(%s::regclass)", (m.group(1),))
                    sz = int(cur.fetchone()[0] or 0)
                    largest_cte_bytes = max(largest_cte_bytes, sz)
                    total_cte_bytes += sz
                except Exception:
                    pass
        toc = time.perf_counter()

        result.update({
            "status": "success",
            "wall_time_s": toc - tic,
            "pg_execution_time_ms": total_exec_ms,
            "pg_planning_time_ms": total_plan_ms,
            "spill_bytes_written": total_temp_written * 8192,
            "spill_bytes_read": total_temp_read * 8192,
            "pg_n_steps": len(statements),
            "largest_cte_bytes": largest_cte_bytes or None,
            "total_cte_bytes": total_cte_bytes or None,
        })
    except psycopg2.errors.QueryCanceled as e:
        result.update({"status": "timeout", "error": str(e)})
    except psycopg2.errors.OutOfMemory as e:
        result.update({"status": "oom_internal", "error": str(e)})
    except Exception as e:
        result.update({"status": "error", "error": str(e), "traceback": traceback.format_exc()})
    finally:
        sampler.stop()
        result["temp_dir_peak_bytes"] = sampler.peak_bytes
        try:
            cur.close()
            con.close()
        except Exception:
            pass


def _pg_sum_plan(plan: Any, key: str) -> int:
    """Recursively sum a numeric field across a Postgres EXPLAIN JSON plan tree."""
    total = 0
    if isinstance(plan, list):
        for item in plan:
            total += _pg_sum_plan(item, key)
    elif isinstance(plan, dict):
        if key in plan and isinstance(plan[key], (int, float)):
            total += int(plan[key])
        for v in plan.values():
            total += _pg_sum_plan(v, key)
    return total


def _run_duckdb(query: str, args, run_idx: str, result: dict) -> None:
    import duckdb

    _GRACE_S = 30  # seconds to wait after interrupt before giving up

    tmp_dir = Path(args.tmp_root) / f"duckdb_{os.getpid()}_{run_idx}"
    # Wipe any leftovers from a prior worker that crashed at the same pid;
    # see _run_sqlite for the rationale.
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    profile_path = tmp_dir / "profile.json"
    sampler = _TempDirSampler(tmp_dir, interval_s=0.25)

    con = duckdb.connect()
    try:
        # DuckDB's memory_limit only governs the buffer pool. Parser, planner,
        # profiler, per-thread vector buffers, and the result set all live
        # outside it, so setting memory_limit == cgroup cap reliably triggers
        # cgroup OOM-kill before DuckDB's own spill machinery engages.
        # Leave a pad for those external allocations.
        cap_mb = args.cap_gb * 1024
        cgroup_safe_mb = max(256, cap_mb - args.duckdb_pad_mb)
        eff_mb = min(cgroup_safe_mb, args.duckdb_memory_mb) if args.duckdb_memory_mb > 0 else cgroup_safe_mb
        con.execute(f"SET memory_limit='{eff_mb}MB'")
        con.execute(f"SET threads={args.threads}")
        con.execute(f"SET temp_directory='{tmp_dir}'")
        # preserve_insertion_order=true (the default) prevents hash-aggregate
        # and several other operators from spilling. Disable to allow spill.
        try:
            con.execute("SET preserve_insertion_order=false")
        except Exception:
            pass
        con.execute("PRAGMA enable_profiling='json'")
        con.execute(f"PRAGMA profile_output='{profile_path}'")
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        result.update({"status": "error", "error": str(e)})
        return

    # In split mode, run one CREATE TEMP TABLE per K# CTE so the planner
    # can't inline the whole cascade into one heap-bound join. In monolithic
    # mode, run the original IQS query unmodified (reproduces the OOM
    # behavior we saw before the fix — useful for the comparison study).
    if args.mode == "split":
        statements = split_iqs_query_per_step(query)
    elif args.mode == "monolithic_materialized":
        statements = [materialize_iqs_ctes(query)]
    else:
        statements = [query]

    run_result: dict = {}
    tic_holder: list = []

    def _execute():
        tic = time.perf_counter()
        tic_holder.append(tic)
        total_spill = 0
        total_rows = 0
        largest_cte_bytes = 0
        total_cte_bytes = 0
        try:
            for stmt in statements:
                cur = con.execute(stmt)
                if not stmt.lstrip().upper().startswith("CREATE"):
                    total_rows += drain_cursor(cur, chunk_size=args.fetch_chunk_size)
                # profile_output is overwritten per statement; sum across.
                try:
                    profile = json.loads(profile_path.read_text())
                    total_spill += _duckdb_sum_spill(profile)
                except Exception:
                    pass
                m = _CREATE_TABLE_KX.search(stmt)
                if m:
                    sz = _duckdb_table_bytes(con, m.group(1))
                    if sz is not None:
                        largest_cte_bytes = max(largest_cte_bytes, sz)
                        total_cte_bytes += sz
            toc = time.perf_counter()
            run_result.update({
                "status": "success",
                "wall_time_s": toc - tic,
                "spill_bytes_written": total_spill if total_spill else None,
                "duckdb_profile_temp_bytes": total_spill,
                "duckdb_n_steps": len(statements),
                "rows_consumed": total_rows,
                "largest_cte_bytes": largest_cte_bytes or None,
                "total_cte_bytes": total_cte_bytes or None,
            })
        except duckdb.OutOfMemoryException as e:
            run_result.update({"status": "oom_internal", "error": str(e),
                               "wall_time_s": time.perf_counter() - tic})
        except duckdb.InterruptException as e:
            run_result.update({"status": "timeout", "error": str(e),
                               "wall_time_s": time.perf_counter() - tic})
        except Exception as e:
            run_result.update({"status": "error", "error": str(e),
                               "traceback": traceback.format_exc(),
                               "wall_time_s": time.perf_counter() - tic})
        finally:
            try:
                con.close()
            except Exception:
                pass

    t = threading.Thread(target=_execute, daemon=True)
    sampler.start()
    t.start()
    t.join(timeout=args.timeout_seconds)

    if t.is_alive():
        # Query exceeded per-run timeout. Interrupt, then give a grace period.
        # con.interrupt() is asynchronous; _GRACE_S lets DuckDB honour it cleanly.
        # If the thread is still alive after the grace period we record a synthetic
        # timeout and return — the daemon thread will be reaped on process exit.
        try:
            con.interrupt()
        except Exception:
            pass
        t.join(timeout=_GRACE_S)
        elapsed = time.perf_counter() - (tic_holder[0] if tic_holder else time.perf_counter())
        if t.is_alive():
            result.update({"status": "timeout", "wall_time_s": elapsed})
        else:
            result.update(run_result or {"status": "timeout", "wall_time_s": elapsed})
        sampler.stop()
        result["temp_dir_peak_bytes"] = sampler.peak_bytes
        result["temp_dir_final_bytes"] = _dir_size_bytes(tmp_dir)
        return

    result.update(run_result)
    sampler.stop()
    result["temp_dir_peak_bytes"] = sampler.peak_bytes
    result["temp_dir_final_bytes"] = _dir_size_bytes(tmp_dir)
    result["duckdb_memory_limit_mb"] = eff_mb
    result["duckdb_threads"] = args.threads


def _duckdb_table_bytes(con, name: str) -> int | None:
    """Best-effort byte size for a (TEMP) table just created in DuckDB.

    Order of preference:
      1. pragma_storage_info — only populated for tables backed by storage
         blocks. For in-memory temp tables this often returns empty/zero,
         which we treat as "unknown" and fall through.
      2. COUNT(*) * sum-of-column-widths — gives an in-memory footprint
         estimate. DOUBLE = 8, BIGINT = 8, INTEGER = 4, BOOLEAN = 1; anything
         else falls back to 8.
    Returns None when neither yields a value.
    """
    for qualified in (name, f"temp.{name}", f"main.{name}"):
        try:
            sz = con.execute(
                f"SELECT COALESCE(SUM(compressed_size), 0)::BIGINT FROM pragma_storage_info('{qualified}')"
            ).fetchone()[0]
            if sz and sz > 0:
                return int(sz)
        except Exception:
            continue
    try:
        n_rows = int(con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    except Exception:
        return None
    width = 0
    try:
        for row in con.execute(f"DESCRIBE {name}").fetchall():
            t = (row[1] or "").upper()
            if "DOUBLE" in t or "BIGINT" in t:
                width += 8
            elif "INTEGER" in t or "INT4" in t:
                width += 4
            elif "BOOLEAN" in t or "BOOL" in t:
                width += 1
            else:
                width += 8
    except Exception:
        return None
    return n_rows * width if width else None


def _duckdb_sum_spill(profile: Any) -> int:
    """Walk DuckDB profile JSON and sum spill/temp_storage byte counters."""
    if isinstance(profile, dict):
        total = 0
        for k, v in profile.items():
            if k in (
                "temporary_storage_bytes",
                "spilled_bytes",
                "bytes_spilled_to_disk",
                "disk_spill",
                "system_peak_temp_dir_size",
                "temp_dir_size",
                "peak_temp_dir_size",
            ) and isinstance(v, (int, float)):
                total += int(v)
            else:
                total += _duckdb_sum_spill(v)
        return total
    if isinstance(profile, list):
        return sum(_duckdb_sum_spill(x) for x in profile)
    return 0


_CREATE_TABLE_KX = re.compile(
    r"CREATE\s+(?:TEMP\s+)?TABLE\s+(K\w+)\s+AS\b", re.IGNORECASE
)


def _run_sqlite(query: str, args, run_idx: str, result: dict) -> None:
    import sqlite3

    tmp_dir = Path(args.tmp_root) / f"sqlite_{os.getpid()}_{run_idx}"
    # Wipe any leftovers from a prior worker that crashed at the same pid:
    # CREATE TABLE Kk would otherwise hit "table already exists".
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_dir / "ooc.db"
    # SQLite honors SQLITE_TMPDIR / TMPDIR for temp files
    os.environ["SQLITE_TMPDIR"] = str(tmp_dir)
    os.environ["TMPDIR"] = str(tmp_dir)

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    try:
        cur.execute("PRAGMA temp_store = FILE")
        cur.execute(f"PRAGMA temp_store_directory = '{tmp_dir}'")
    except sqlite3.OperationalError:
        pass  # temp_store_directory deprecated on newer SQLite
    # Negative cache_size is kibibytes. Apply it to both main and temp schemas:
    # transient CTE materializations and temp B-trees have their own cache.
    for schema in ("main", "temp"):
        try:
            cur.execute(f"PRAGMA {schema}.cache_size = -{args.sqlite_cache_mb * 1024}")
            cur.execute(f"PRAGMA {schema}.cache_spill = ON")
        except sqlite3.OperationalError:
            pass
    try:
        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("PRAGMA journal_mode = OFF")
    except sqlite3.OperationalError:
        pass
    # mmap is uncapped and bypasses cache_size; disable it so the cap is real.
    try:
        cur.execute("PRAGMA mmap_size = 0")
    except sqlite3.OperationalError:
        pass

    sampler = _TempDirSampler(tmp_dir, interval_s=0.25)
    sampler.start()

    timed_out = {"flag": False}
    def watchdog():
        time.sleep(args.timeout_seconds)
        try:
            con.interrupt()
            timed_out["flag"] = True
        except Exception:
            pass
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    # See _run_duckdb for why split mode exists. For sqlite we pass temp=False
    # so the K# intermediates land in the main (disk-backed) DB rather than in
    # the temp schema — the temp schema's backing is controlled by PRAGMA
    # temp_store, which silently no-ops when sqlite was compiled with
    # SQLITE_TEMP_STORE=2. CREATE TABLE in the main DB always hits disk.
    if args.mode == "split":
        statements = split_iqs_query_per_step(query, temp=False)
    elif args.mode == "monolithic_materialized":
        statements = [materialize_iqs_ctes(query)]
    else:
        statements = [query]
    tic = time.perf_counter()
    try:
        total_rows = 0
        largest_cte_bytes = 0
        total_cte_bytes = 0
        for stmt in statements:
            m = _CREATE_TABLE_KX.search(stmt)
            sz_before = db_path.stat().st_size if (m and db_path.exists()) else 0
            cur.execute(stmt)
            if not stmt.lstrip().upper().startswith("CREATE"):
                total_rows += drain_cursor(cur, chunk_size=args.fetch_chunk_size)
            elif m:
                # journal_mode=OFF + synchronous=OFF means each CREATE TABLE
                # writes straight to db_path. Delta = K# table bytes.
                con.commit()
                sz_after = db_path.stat().st_size if db_path.exists() else 0
                delta = max(0, sz_after - sz_before)
                largest_cte_bytes = max(largest_cte_bytes, delta)
                total_cte_bytes += delta
        con.commit()
        toc = time.perf_counter()
        sampler.stop()
        if timed_out["flag"]:
            result.update({
                "status": "timeout",
                "wall_time_s": toc - tic,
                "temp_dir_peak_bytes": sampler.peak_bytes,
                "temp_dir_final_bytes": _dir_size_bytes(tmp_dir),
            })
            return
        # SQLite has no query-level temp-byte counter exposed through Python's
        # stdlib sqlite3 module. Directory walking also confounds temp files
        # with the main on-disk DB used by split mode, and may miss anonymous
        # temp files. The per-run /proc/self/io write delta recorded by main()
        # is the spill/workspace proxy for SQLite.
        result.update({
            "status": "success",
            "wall_time_s": toc - tic,
            "spill_bytes_written": None,
            "temp_dir_peak_bytes": sampler.peak_bytes,
            "temp_dir_final_bytes": _dir_size_bytes(tmp_dir),
            "sqlite_cache_mb": args.sqlite_cache_mb,
            "sqlite_n_steps": len(statements),
            "rows_consumed": total_rows,
            "largest_cte_bytes": largest_cte_bytes or None,
            "total_cte_bytes": total_cte_bytes or None,
        })
    except sqlite3.OperationalError as e:
        sampler.stop()
        msg = str(e).lower()
        result.update({
            "temp_dir_peak_bytes": sampler.peak_bytes,
            "temp_dir_final_bytes": _dir_size_bytes(tmp_dir),
        })
        if "interrupted" in msg:
            result.update({"status": "timeout", "error": str(e)})
        elif "out of memory" in msg:
            result.update({"status": "oom_internal", "error": str(e)})
        else:
            result.update({"status": "error", "error": str(e)})
    except Exception as e:
        sampler.stop()
        result.update({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "temp_dir_peak_bytes": sampler.peak_bytes,
            "temp_dir_final_bytes": _dir_size_bytes(tmp_dir),
        })
    finally:
        try:
            cur.close()
            con.close()
        except Exception:
            pass


class _TempDirSampler(threading.Thread):
    def __init__(self, path: Path, interval_s: float = 0.5):
        super().__init__(daemon=True)
        self.path = path
        self.interval = interval_s
        self.peak_bytes = 0
        # See _CgroupMemSampler for why this is _stop_event, not _stop.
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                total = _dir_size_bytes(self.path)
                if total > self.peak_bytes:
                    self.peak_bytes = total
            except FileNotFoundError:
                pass
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
        self.join(timeout=2)


def _dir_size_bytes(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except FileNotFoundError:
        return 0


def _run_aer(qc, args, run_idx: str, result: dict) -> None:
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    max_mem_mb = max(1, args.cap_gb * 1024 - args.aer_pad_mb)
    backend = AerSimulator(
        method=args.aer_method,
        max_memory_mb=max_mem_mb,
        max_parallel_threads=args.threads,
    )
    # Remove any coupling-map restriction so circuits with >15 qubits are not
    # rejected by Aer's internal validation (the default AerSimulator config can
    # carry a 15-qubit fake-device coupling map, especially for density_matrix).
    backend.set_options(coupling_map=None)
    try:
        qc_saved = qc.copy()
        # Save the state appropriate for the method so the full simulation runs.
        if args.aer_method in ("density_matrix",):
            qc_saved.save_density_matrix()
        elif args.aer_method in ("stabilizer",):
            qc_saved.save_stabilizer()
        else:
            qc_saved.save_statevector()

        transpiled = transpile(qc_saved, backend, coupling_map=None)

        tic = time.perf_counter()
        job = backend.run(transpiled, shots=1)
        res = job.result(timeout=args.timeout_seconds)
        toc = time.perf_counter()
        if res.success:
            result.update({
                "status": "success",
                "wall_time_s": toc - tic,
                "aer_method_used": args.aer_method,
                "aer_max_memory_mb": max_mem_mb,
            })
        else:
            status = "oom_internal" if "memory" in (res.status or "").lower() else "error"
            result.update({
                "status": status,
                "error": res.status,
                "wall_time_s": toc - tic,
                "aer_method_used": args.aer_method,
                "aer_max_memory_mb": max_mem_mb,
            })
    except Exception as e:
        msg = str(e).lower()
        status = "oom_internal" if any(k in msg for k in ("memory", "insufficient")) else "error"
        result.update({
            "status": status,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "aer_max_memory_mb": max_mem_mb,
            "aer_method_used": args.aer_method,
        })


# ─────────────────── Main driver ────────────────────

ENGINE_DISPATCH: dict[str, Callable] = {
    "postgres": _run_postgres,
    "duckdb": _run_duckdb,
    "sqlite": _run_sqlite,
    "aer": _run_aer,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=list(ENGINE_DISPATCH), required=True)
    ap.add_argument("--cap-gb", type=int, required=True)
    ap.add_argument("--circuit-qpy", type=str, required=True)
    ap.add_argument("--circuit-hash", type=str, required=True)
    ap.add_argument("--bin", type=str, default="")
    ap.add_argument("--out-path", type=str, required=True)
    ap.add_argument("--n-runs", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--timeout-seconds", type=int, default=1800)
    ap.add_argument("--tmp-root", type=str, default="/data/inferq_ooc")
    ap.add_argument("--container-cpus", type=float, default=0,
                    help="Docker --cpus quota applied by the orchestrator; "
                         "recorded for reproducibility only.")
    ap.add_argument("--threads", type=int, default=16)
    # Postgres-specific
    ap.add_argument("--pg-host", default=os.getenv("POSTGRES_HOST", "localhost"))
    ap.add_argument("--pg-port", type=int, default=int(os.getenv("POSTGRES_PORT", "54320")))
    ap.add_argument("--pg-user", default=os.getenv("POSTGRES_USER", "postgres"))
    ap.add_argument("--pg-password", default=os.getenv("POSTGRES_PASSWORD", "postgres"))
    ap.add_argument("--pg-db", default=os.getenv("POSTGRES_DB", "postgres"))
    # Aer-specific
    ap.add_argument("--aer-method", default="statevector")
    ap.add_argument("--aer-pad-mb", type=int, default=512)
    # DuckDB-specific: pad below cgroup cap for non-bufferpool allocations
    ap.add_argument("--duckdb-pad-mb", type=int, default=1024,
                    help="Subtract this many MB from the cgroup cap when setting "
                         "DuckDB's memory_limit, to leave headroom for parser, "
                         "planner, profiler, and per-thread vector buffers.")
    ap.add_argument("--duckdb-memory-mb", type=int, default=512,
                    help="DuckDB memory_limit in MB. Values <=0 fall back to "
                         "cap minus --duckdb-pad-mb.")
    ap.add_argument("--sqlite-cache-mb", type=int, default=64,
                    help="SQLite PRAGMA cache_size budget in MB.")
    ap.add_argument("--fetch-chunk-size", type=int, default=8192,
                    help="Rows to fetch at once when draining embedded-engine "
                         "results. Prevents Python from materializing the full "
                         "result set in memory.")
    ap.add_argument("--mode", choices=["monolithic", "monolithic_materialized", "split"], default="split",
                    help="Query execution mode: 'monolithic' runs the IQS query "
                         "as a single WITH ... SELECT (prone to OOM in sqlite/"
                         "duckdb); 'monolithic_materialized' keeps one query but "
                         "adds AS MATERIALIZED CTE hints; 'split' decomposes into "
                         "per-step CREATE TEMP TABLE statements. Default: split.")
    args = ap.parse_args()

    Path(args.tmp_root).mkdir(parents=True, exist_ok=True)
    _warn_if_tmpfs(Path(args.tmp_root))

    envelope: dict = {
        "engine": args.engine,
        "cap_gb": args.cap_gb,
        "circuit_hash": args.circuit_hash,
        "circuit_qpy": args.circuit_qpy,
        "bin": args.bin,
        "mode": args.mode,
        "container_cpus": args.container_cpus,
        "aer_method": args.aer_method if args.engine == "aer" else None,
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "pid": os.getpid(),
        "started_at": time.time(),
        "runs": [],
    }

    try:
        qc = _load_qiskit_circuit(args.circuit_qpy)
        envelope["num_qubits"] = qc.num_qubits
        envelope["num_gates"] = qc.size()

        query = None
        if args.engine in ("postgres", "duckdb", "sqlite"):
            qgen_tic = time.perf_counter()
            query, num_q, num_g = _build_iqs_query_with_timeout(qc, args.timeout_seconds)
            envelope["query_gen_time_s"] = time.perf_counter() - qgen_tic
            envelope["num_qubits"] = num_q
            envelope["num_gates"] = num_g
            envelope["query_bytes"] = len(query)
            envelope.update(count_iqs_ctes(query))

        runner = ENGINE_DISPATCH[args.engine]

        labels = ["warmup"] * args.warmup + [str(i) for i in range(args.n_runs)]
        # Start cgroup memory sampler — independent peak source that works on
        # kernels < 5.19 (no memory.peak) and cross-checks the primary reading.
        # On hybrid v1+v2 hosts the v2 unified hierarchy may have no memory
        # controller (Docker on cgroupfs/v1 puts memory accounting under
        # /sys/fs/cgroup/memory/...). Pick whichever path actually carries it.
        v2_path, v1_mem_path = _resolve_own_cgroup_paths()
        sampler_cgroup = None
        if v2_path is not None and _v2_has_memory_accounting(v2_path):
            sampler_cgroup = v2_path
        elif v1_mem_path is not None:
            sampler_cgroup = v1_mem_path
        cg_sampler = _CgroupMemSampler(sampler_cgroup, interval_s=0.1) if sampler_cgroup else None
        if cg_sampler is not None:
            cg_sampler.start()
        tracemalloc.start()
        for run_idx in labels:
            gc.collect()
            tracemalloc.clear_traces()
            run_result: dict = {"run_idx": run_idx}
            mem_tic, _ = tracemalloc.get_traced_memory()
            proc_read_before, proc_write_before = _read_proc_io_bytes()
            if args.engine == "aer":
                runner(qc, args, run_idx, run_result)
            else:
                runner(query, args, run_idx, run_result)
            proc_read_after, proc_write_after = _read_proc_io_bytes()
            proc_read_delta = _counter_delta(proc_read_before, proc_read_after)
            proc_write_delta = _counter_delta(proc_write_before, proc_write_after)
            run_result["proc_io_read_bytes"] = proc_read_delta
            run_result["proc_io_write_bytes"] = proc_write_delta
            if args.engine in ("duckdb", "sqlite"):
                run_result["spill_proxy_bytes"] = proc_write_delta
                run_result["spill_metric_kind"] = "proc_io_write_bytes"
            elif args.engine == "postgres":
                run_result["spill_proxy_bytes"] = run_result.get("spill_bytes_written")
                run_result["spill_metric_kind"] = "postgres_explain_temp_written"
            _, mem_toc = tracemalloc.get_traced_memory()
            run_result["tracemalloc_peak_bytes"] = mem_toc - mem_tic
            run_result["proc_vm_peak_bytes"] = _read_vm_peak_bytes()
            envelope["runs"].append(run_result)

            # Abort early if warm-up and first run both failed hard.
            if run_idx != "warmup" and run_result.get("status") in ("oom_internal",):
                # Don't keep trying an engine the OS/DB already said it can't do.
                break
        tracemalloc.stop()
        if cg_sampler is not None:
            cg_sampler.stop()
            envelope["cgroup_sampled_peak_bytes"] = cg_sampler.peak_bytes

        envelope["status"] = _summarize_status(envelope["runs"])
    except TimeoutError as e:
        envelope["status"] = "query_gen_timeout"
        envelope["error"] = str(e)
    except Exception as e:
        envelope["status"] = "error"
        envelope["error"] = str(e)
        envelope["traceback"] = traceback.format_exc()
    finally:
        envelope["finished_at"] = time.time()
        envelope["cgroup"] = _read_own_cgroup_v2()

    Path(args.out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_path).write_text(json.dumps(envelope, default=str))


def _summarize_status(runs: list[dict]) -> str:
    timed = [r for r in runs if r["run_idx"] != "warmup"]
    if not timed:
        return "no_runs"
    statuses = {r.get("status") for r in timed}
    if statuses == {"success"}:
        return "success"
    if "oom_internal" in statuses:
        return "oom_internal"
    if "timeout" in statuses:
        return "timeout"
    return "error"


if __name__ == "__main__":
    main()
