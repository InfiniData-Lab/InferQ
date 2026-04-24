# OOC Experiment: Technical Design

This document explains how memory caps are enforced, what each metric
measures and where the number comes from, and how the orchestrator and
worker fit together.

---

## Architecture overview

```
run_experiment.py  (orchestrator)
    │
    │  for each (circuit, cap, engine, method):
    │
    ├─ postgres ──► docker run --memory=CAP  ──► postgres container
    │                                              │
    │               systemd-run --scope           worker.py
    │               MemoryMax=60G ─────────────► psycopg2 → SQL query
    │
    ├─ duckdb  ──► systemd-run --scope ──────► worker.py
    ├─ sqlite       MemoryMax=CAP               DuckDB / SQLite query
    └─ aer          MemorySwapMax=0             Aer simulation
                         │
                         └─► kernel cgroup v2 enforces hard limit
```

There are two separate processes for each run: the **orchestrator** and
the **worker**. The orchestrator is long-lived and coordinates the sweep.
The worker is a short-lived subprocess that runs exactly one engine on one
circuit and exits. This isolation means a crash or OOM-kill in the worker
never takes down the orchestrator.

---

## Memory enforcement

### Embedded engines (DuckDB, SQLite, Aer)

The orchestrator launches the worker via `systemd-run`:

```bash
systemd-run --user --scope --quiet \
    --unit ooc-<hash>-<engine>-<cap>-<id>.scope \
    --property MemoryMax=<cap>G \
    --property MemorySwapMax=0 \
    --property IOAccounting=yes \
    --property MemoryAccounting=yes \
    -- python -m scripts.ooc.worker ...
```

`systemd-run --scope` creates a **cgroup v2 scope** around the worker
process. The kernel enforces `MemoryMax` as a hard limit: if the process
(and its children) exceeds it, the kernel OOM-kills the process and the
worker exits with rc=137. `MemorySwapMax=0` disables swap entirely for
the scope, so there is no silent extension of the effective memory budget.

The worker itself does **not** set any memory limit — enforcement is
entirely external. This matches how a real server workload would behave.

### PostgreSQL

For Postgres the memory limit is set on the Docker container rather than
the worker process, because Postgres is a separate process that the worker
connects to over TCP:

```bash
docker run -d \
    --memory <cap>G \
    --memory-swap <cap>G \
    --memory-swappiness 0 \
    -e CAP_GB=<cap> \
    -e POSTGRES_PASSWORD=postgres \
    -p 54320:5432 \
    inferq-ooc-postgres:16
```

`--memory-swap <cap>G` sets the combined memory+swap limit equal to
`--memory`, giving an effective swap budget of zero. Docker enforces this
via the container's own cgroup, which is separate from the worker's scope.
The worker runs with a loose scope cap (60 GB) so the enforcement is
entirely on the container.

The custom image (`inferq-ooc-postgres:16`) builds on `postgres:16` and
substitutes `CAP_GB`-scaled values into `postgresql.conf` at container
start via `pg_entrypoint.sh`:

```
shared_buffers   = CAP_GB / 4 MB       (e.g. 4 GB at cap=16)
work_mem         = 64 MB               (fixed; spill is measured, not prevented)
effective_cache  = CAP_GB / 2 MB
temp_file_limit  = CAP_GB * 512 MB     (per-query spill budget)
```

---

## Metrics: what they are and where they come from

### `wall_time_s`

Wall-clock seconds from just before the engine call to just after, measured
with `time.perf_counter()` inside the worker. For Postgres this wraps the
`EXPLAIN (ANALYZE, BUFFERS)` call; for DuckDB/SQLite it wraps `execute +
fetchall`; for Aer it wraps `backend.run + job.result`.

This is the primary performance metric.

### `cgroup_mem_peak_bytes`

Peak resident memory in bytes for the entire cgroup over the lifetime of
the worker process (all warmup + timed runs combined).

**Source — embedded engines:** read from the cgroup v2 scope created by
`systemd-run`. The orchestrator calls `find_systemd_scope_cgroup(unit_name)`
to locate the cgroup directory, then reads:
- `memory.peak` (kernel ≥ 5.19) — true high-water mark
- `memory.current` (fallback) — instantaneous; less accurate

On hybrid cgroup systems (v1 memory controller + v2 unified), the v1
path `memory.max_usage_in_bytes` is preferred because it is a true peak.

**Source — Postgres:** read from the Docker container's cgroup via
`find_docker_cgroup(container_id)`, which resolves the full container ID
with `docker inspect` and then looks for the cgroup under
`system.slice/docker-<id>.scope` (systemd cgroup driver) or `docker/<id>`
(cgroupfs driver).

**Fallback:** if the orchestrator cannot find the cgroup after the scope
exits (the directory is deleted when the scope ends), the worker
self-reports its own cgroup counters just before exiting, while the
directory still exists. These are stored in the `cgroup` key of the
worker's JSON output and used as a fallback.

### `cgroup_swap_peak_bytes`

Peak swap usage for the cgroup. Should be zero for all runs because swap
is disabled (`MemorySwapMax=0` / `--memory-swap=cap`). A non-zero value
indicates a configuration problem and the run should be discarded.

### `cgroup_io_read_bytes` / `cgroup_io_write_bytes`

Cumulative bytes read from and written to block devices by the cgroup,
read from cgroup v2 `io.stat`. This captures all disk I/O including temp
file spill, WAL, and data file access. For Postgres it covers the entire
container lifetime including startup I/O.

These are coarser than the DBMS-reported spill figures but are
engine-independent and harder to game.

### `dbms_temp_bytes_written` / `dbms_temp_bytes_read`

Engine-reported spill to temporary files. More precise than the cgroup I/O
counters because they exclude startup I/O and background writes.

- **DuckDB:** parsed from the profiling JSON written to
  `/tmp/inferq_ooc/duckdb_<pid>_<run>/profile.json`. The worker sums
  the fields `temporary_storage_bytes`, `spilled_bytes`, and
  `bytes_spilled_to_disk` across the plan tree. DuckDB's profile schema
  has changed across versions, so this may return zero on some versions
  even when spill occurred — cross-check with `cgroup_io_write_bytes`.

- **PostgreSQL:** extracted from `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
  by recursively summing `"Temp Written Blocks"` and `"Temp Read Blocks"`
  across the plan tree, then multiplying by 8192 (Postgres block size).

- **SQLite:** SQLite has no query-level spill accounting. The worker
  samples the size of the temp directory (`/tmp/inferq_ooc/sqlite_<pid>_<run>/`)
  every 250 ms and reports the peak observed size as `dbms_temp_bytes_written`.
  This is approximate but captures disk usage.

- **Aer:** no spill concept — always zero.

### `tracemalloc_peak_bytes`

Python heap peak during the run, measured with `tracemalloc`. For
DuckDB / SQLite this mostly captures query-generation overhead (SQL string
construction, opt_einsum path-finding) rather than the engine's own
memory use. For Aer it captures Python-side bookkeeping; the actual
statevector lives in a C++ allocation not visible to tracemalloc.

Use `cgroup_mem_peak_bytes` as the primary memory metric; `tracemalloc`
is a secondary diagnostic.

### `proc_vm_peak_bytes`

Peak virtual memory size of the worker process (`VmPeak` from
`/proc/self/status`). Virtual memory includes memory-mapped files and
shared libraries that may never be faulted in. Use `cgroup_mem_peak_bytes`
(RSS-based) as the primary metric; `proc_vm_peak_bytes` is informational.

### `status`

Outcome of the run:

| Value | Meaning |
|-------|---------|
| `success` | Engine returned a result within the timeout |
| `oom_internal` | Engine raised an out-of-memory error internally (e.g. Aer `InsufficientMemoryError`, DuckDB `OutOfMemoryException`) |
| `oom_kill` | Worker process killed by kernel OOM killer (rc=137) |
| `timeout` | Run exceeded `timeout_seconds` (default 1800 s) |
| `error` | Any other failure (wrong method name, connection refused, etc.) |
| `pg_startup_failed` | Postgres container did not become ready within 60 s |
| `query_gen_timeout` | SQL generation (opt_einsum path-finding) timed out |

`oom_internal` is the most useful status for the paper: it means the
engine detected the constraint and reported it cleanly, as opposed to
`oom_kill` where the kernel intervened.

---

## Page cache between runs

Before each `(circuit, cap, engine)` triple the orchestrator runs:

```bash
sync && echo 3 | sudo tee /proc/sys/vm/drop_caches
```

This flushes the OS page cache so each run starts cold with respect to
temp files and data files. Without this, later runs of the same circuit
would read spilled data from cache, understating the I/O cost.

---

## Early abort

For Aer, the worker aborts after the first non-warmup run that returns
`oom_internal`. Retrying after an OOM makes no sense (the circuit size and
cap are fixed) and would waste hours on large circuits. Only one data point
is recorded for those triples; this is reflected in the CSV by the absence
of `run_idx` 1 and 2.

---

## Data flow summary

```
worker exits
    │
    ├─ writes JSON to tmp file (envelope with all run results)
    │
orchestrator reads JSON
    │
    ├─ reads cgroup snapshot (or uses worker self-report fallback)
    │
    ├─ for each run in envelope["runs"]:
    │       emit one CSV row with all fields merged
    │
    └─ appends to results.csv (flushed after each triple)
```

The CSV has one row per `(circuit, cap, engine, method, run_idx)`. The
`cgroup_*` columns are repeated on every row for the triple because they
cover the entire subprocess lifetime, not individual runs.
