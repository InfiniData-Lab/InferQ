# OOC Experiment: Technical Design

This document explains how memory caps are enforced, what each metric
measures and where the number comes from, and how the orchestrator and
worker fit together.

---

## Architecture overview

```
run_experiment.py  (orchestrator, on host)
    │
    │  for each (circuit, cap, engine, method):
    │
    ├─ postgres ──► docker run --memory=CAP                ──► postgres container
    │                  inferq-ooc-postgres:12.22               (server)
    │                                                              ▲
    │               docker run --memory=60G                        │
    │                  inferq-ooc-worker  ──► worker.py ──── psycopg2:54320
    │                                                          (host network)
    │
    ├─ duckdb  ──► docker run --memory=CAP                 ──► worker.py
    ├─ sqlite       --memory-swap=CAP --memory-swappiness=0    DuckDB / SQLite query
    └─ aer          inferq-ooc-worker                          Aer simulation
                          │
                          └─► Docker cgroup enforces hard limit
                              (kernel OOM-kills container at cap)
```

There are two address spaces per run: the **orchestrator** (on the host)
and the **worker** (inside a Docker container). The orchestrator is
long-lived and coordinates the sweep. Each worker is a short-lived
container that runs exactly one engine on one circuit and exits. Crashes
and OOM-kills in the worker never take down the orchestrator.

For postgres, two containers are involved per triple: the postgres server
carries the memory cap (it's where memory is actually used), and a
separate worker container runs the psycopg2 client with a generous 60 GB
cap. They communicate over `host` networking on port 54320.

---

## Memory enforcement

### Every engine: Docker `--memory`

```bash
docker run --rm \
    --name <unit> \
    --memory <cap>g --memory-swap <cap>g --memory-swappiness 0 \
    --network host --cgroupns host \
    -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
    -v <REPO>:<REPO>:ro \
    -v <OOC_TMP_ROOT>:<OOC_TMP_ROOT> \
    -v /tmp:/tmp \
    -e PYTHONPATH=<IQS>:<INFERQ> -w <INFERQ> \
    inferq-ooc-worker:latest \
    -m experiments.ooc.worker ...
```

`--memory <cap>g --memory-swap <cap>g` sets the combined memory+swap
budget equal to memory, giving an effective swap of zero. Docker installs
this on the container's own cgroup; if the container exceeds it, the
kernel OOM-kills the worker process and the container exits with rc=137.

The worker itself does **not** set any memory limit. Enforcement is
entirely external — the same model a real server workload would face.

### PostgreSQL

The postgres server runs in its own container with the experiment cap.
The worker container is a separate process that connects via host
networking with a loose 60 GB cap (it does no memory-intensive work
itself):

```bash
docker run -d \
    --memory <cap>g --memory-swap <cap>g --memory-swappiness 0 \
    -e CAP_GB=<cap> -e POSTGRES_PASSWORD=postgres \
    -p 54320:5432 \
    inferq-ooc-postgres:12.22
```

The custom image (`inferq-ooc-postgres:12.22`) builds on `postgres:12.22` and
substitutes `CAP_GB`-scaled values into `postgresql.conf` at container
start via `pg_entrypoint.sh`:

```
shared_buffers   = CAP_GB / 4 MB       (e.g. 4 GB at cap=16)
work_mem         = 64 MB               (fixed; spill is measured, not prevented)
effective_cache  = CAP_GB / 2 MB
temp_file_limit  = CAP_GB * 4096 MB    (per-query spill budget)
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
the worker container (all warmup + timed runs combined).

**Source — embedded engines (worker container's own cgroup):** the worker
self-reports from inside the container by parsing `/proc/self/cgroup` and
reading `memory.peak` / `memory.current` (cgroup v2) or
`memory.max_usage_in_bytes` (v1) from the resolved cgroup directory.
Because the worker container is launched with `--cgroupns=host` and the
host's `/sys/fs/cgroup` bind-mounted read-only, the path resolves
identically inside and outside the container. The worker also runs a 100
ms polling sampler on `memory.current` while the engine executes — this
is an independent peak source that works on kernels < 5.19 (no
`memory.peak`). The orchestrator emits `max(self_report_peak,
sampled_peak)` as `cgroup_mem_peak_bytes`.

**Source — Postgres (postgres container's cgroup):** read on the host
side via `find_docker_cgroup(container_id)`, which resolves the full
container ID with `docker inspect` and then looks for the cgroup under
`system.slice/docker-<id>.scope` (systemd cgroup driver) or `docker/<id>`
(cgroupfs driver). The postgres container is still alive at read time,
so this is reliable.

**Fallback:** if the worker self-report is missing (cgroup files
inaccessible), the polling sampler still produces a peak. If both fail,
the field is empty.

### `cgroup_swap_peak_bytes`

Peak swap usage for the cgroup. Should be zero for all runs because swap
is disabled (`MemorySwapMax=0` / `--memory-swap=cap`). A non-zero value
indicates a configuration problem and the run should be discarded.

### `proc_io_read_bytes` / `proc_io_write_bytes`

Per-run physical I/O deltas for the worker process, read from
`/proc/self/io` immediately before and after each run. For embedded engines
(SQLite and DuckDB) this is the primary spill/workspace proxy requested by the
revision guide. It is per-run, unlike cgroup I/O, and it catches SQLite's main
database writes in split mode as well as temp-file writes.

Do not call this exact spill volume. It also includes non-spill writes such as
materialized intermediate tables and small profile files. In the paper, report
it as process write volume or spill proxy.

### `cgroup_io_read_bytes` / `cgroup_io_write_bytes`

Cumulative bytes read from and written to block devices by the cgroup,
read from cgroup v2 `io.stat`. This captures all disk I/O including temp
file spill, WAL, and data file access. For Postgres it covers the entire
container lifetime including startup I/O. For embedded engines it covers the
whole worker container lifetime, so one value is repeated across warmup/timed
rows. Use it as a coarse cross-check, not as the per-run spill metric.

These are engine-independent and useful for sanity checks, but they are not
exact spill bytes and should not drive the spill plots.

### `dbms_temp_bytes_written` / `dbms_temp_bytes_read`

Engine-reported spill to temporary files when the engine exposes such a
counter. These are diagnostics for embedded engines and exact temp accounting
for Postgres.

- **DuckDB:** parsed from the profiling JSON written to
  `<OOC_TMP_ROOT>/duckdb_<pid>_<run>/profile.json`. The worker sums
  the fields `temporary_storage_bytes`, `spilled_bytes`, and
  `bytes_spilled_to_disk` across the plan tree. DuckDB's profile schema
  has changed across versions, so this may return zero on some versions
  even when spill occurred. Cross-check with `proc_io_write_bytes` and
  `temp_dir_peak_bytes`.

- **PostgreSQL:** extracted from `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
  by recursively summing `"Temp Written Blocks"` and `"Temp Read Blocks"`
  across the plan tree, then multiplying by 8192 (Postgres block size).

- **SQLite:** SQLite has no query-level spill accounting exposed through
  Python's stdlib `sqlite3` wrapper. New runs leave
  `dbms_temp_bytes_written` empty for SQLite and use `proc_io_write_bytes` /
  `spill_proxy_bytes` instead. The worker still records
  `temp_dir_peak_bytes` and `temp_dir_final_bytes` as diagnostics, but those
  include the main on-disk DB in split mode and are not DBMS temp bytes.

### `spill_proxy_bytes`

The metric used by analysis scripts for spill-related summaries:

- Postgres: exact `EXPLAIN` temp written bytes.
- DuckDB and SQLite: per-run `proc_io_write_bytes`.

The `spill_metric_kind` column records which source was used.

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
