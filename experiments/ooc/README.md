# Out-of-Core / Limited-Memory RDBMS Experiments

SIGMOD paper 160 revision **E1 / R1.O1 / R2.Q2**. Runs PostgreSQL, SQLite,
DuckDB, and Qiskit Aer on a stratified sample of circuits under explicit
memory caps (16 GB / 8 GB / 4 GB) and captures spill behaviour + the
headline Aer-vs-RDBMS failure case.

---

## Experimental design

### Goal

Show that RDBMS-based simulation succeeds under memory constraints where
Aer fails outright. The key claim is that for large circuits (≥ 31 qubits,
≥ 32 GB statevector), Aer OOMs at every cap we test while DuckDB / SQLite
succeed by spilling to disk.

### Why memory caps matter

Aer's statevector simulator allocates `2^N × 16 B` contiguously. At 28 q
that is 4 GB; at 30 q it is 16 GB; at 31 q it is 32 GB. There is no
incremental growth — if the allocation fails, the simulation fails
immediately. RDBMS engines handle memory pressure by spilling intermediate
results to temporary files on disk, so their success rate degrades
gracefully with the cap rather than cliff-dropping.

### Circuit bins

Circuits are stratified by qubit count, which directly predicts Aer
statevector memory. The prior tracemalloc-based RDBMS memory figures in
the metadata underestimate true footprint by 10–100× (they only see Python
heap), so qubit count is the only reliable OOM-threshold proxy.

| Bin | Qubits | Aer statevector | Story |
|-----|--------|-----------------|-------|
| `B0_trivial`         | < 25  | ≤ 512 MB | Baseline — Aer + RDBMS succeed everywhere |
| `B1_aer_ok_all_caps` | 25–27 | 0.5–2 GB | Aer fits at every cap; RDBMS may spill at 4 GB |
| `B2_aer_fails_at_4`  | 28–29 | 4–8 GB   | Aer OOMs at cap=4; RDBMS must spill |
| `B3_aer_fails_at_8`  | 30    | 16 GB    | Aer OOMs at caps 4 and 8; RDBMS spills |
| `B4_aer_impossible`  | ≥ 31  | ≥ 32 GB  | **Headline** — Aer OOMs at every cap; RDBMS succeeds |

### Memory enforcement

Every engine runs inside a Docker container with `--memory=X --memory-swap=X
--memory-swappiness=0`. The kernel kills the container if it exceeds the cap;
swap is fully disabled, so any non-zero `cgroup_swap_peak_bytes` in the
results indicates a configuration problem.

- **PostgreSQL**: the postgres server runs in `inferq-ooc-postgres:12.22` with
  `--memory=cap`. A separate worker container (`inferq-ooc-worker:latest`)
  with a generous 60 GB cap connects via host networking on port 54320.
- **DuckDB / SQLite / Aer**: a single `inferq-ooc-worker:latest` container
  per triple, capped at the experiment cap. The repo and `OOC_TMP_ROOT` are
  bind-mounted so the worker code, circuit qpy files, and DuckDB / SQLite
  spill directories live on the host filesystem.
- Aer additionally receives `max_memory_mb = cap_gb × 1024 − 512` so it
  raises an internal `InsufficientMemoryError` before the kernel OOM-kills
  the container (cleaner error path).

The worker self-reports its cgroup peak from inside the container via
`/proc/self/cgroup` (cgroupns=host + cgroup bind-mount), with a 100 ms
polling sampler on `memory.current` as an independent peak source for
kernels that lack `memory.peak` (< 5.19).

### What is measured per run

Each `(circuit, cap, engine, method)` triple produces:

- `wall_time_s` — end-to-end query/simulation time
- `cgroup_mem_peak_bytes` — peak RSS of the entire cgroup (most reliable)
- `proc_io_write_bytes` — per-run process write volume from `/proc/self/io`
- `spill_proxy_bytes` — analysis-facing spill proxy: Postgres temp bytes;
  DuckDB/SQLite process writes
- `cgroup_io_write_bytes` — coarse container-lifetime disk write cross-check
- `dbms_temp_bytes_written` — engine-reported spill where available
  (Postgres EXPLAIN BUFFERS; DuckDB profile JSON when populated; empty for
  SQLite in new runs)
- `status` — `success | oom_internal | timeout | oom_kill | error`

Each triple runs once as a warm-up (discarded) and then three timed runs.
Aer aborts after the first `oom_internal` result to avoid wasting time.

---

## Target machine

Linux host running Docker. Memory enforcement is delegated entirely to
Docker (cgroup-driver-agnostic), so cgroup v1, v2, hybrid, or unified all
work — no host-side cgroup configuration required. Reference box:

- **Alienware Aurora R13** — 64 GB DDR5, Intel i9-12900KF (16c/24t),
  Micron 3400 NVMe 2 TB on ext4. Ubuntu 22.04, kernel 5.15+.

The experiments can run on macOS / Windows with `--runner none` but
memory caps are **not enforced** — use only for smoke tests.

---

## One-time setup

```bash
# 1. Install Docker Engine and add your user to the docker group.
#    https://docs.docker.com/engine/install/ubuntu/

# 2. Build BOTH images (tuned Postgres + worker runtime):
cd InferQ
./experiments/ooc/docker/build.sh
#   → inferq-ooc-postgres:12.22
#   → inferq-ooc-worker:latest

# 3. (optional) Override images via env if you tag them differently:
export OOC_PG_IMAGE=inferq-ooc-postgres:12.22
export OOC_WORKER_IMAGE=inferq-ooc-worker:latest

# 4. NOPASSWD sudoers entry for dropping the page cache between runs.
#    Add to /etc/sudoers.d/inferq-ooc (replace USER with your username):
#       USER ALL=(root) NOPASSWD: /usr/bin/tee /proc/sys/vm/drop_caches
#    Verify:
sync && echo 3 | sudo -n tee /proc/sys/vm/drop_caches >/dev/null && echo ok

# 5. NVMe-backed temp dir for engine spill files. /tmp on most distros is
#    tmpfs (RAM-backed) — spill writes would be invisible to spill metrics.
sudo mkdir -p /data/inferq_ooc && sudo chown "$USER:$USER" /data/inferq_ooc
findmnt -no FSTYPE -T /data/inferq_ooc   # must NOT print 'tmpfs'
export OOC_TMP_ROOT=/data/inferq_ooc

# 6. Python dependencies on the host (only the orchestrator runs here):
uv pip install .
```

Verify Docker enforces a memory cap:

```bash
docker run --rm --memory 512m --memory-swap 512m inferq-ooc-worker:latest \
    -c 'a=bytearray(2_000_000_000); print("NO_ENFORCEMENT")'; echo "rc=$?"
```
Expect `rc=137` (kernel OOM-killed it).

---

## Running the full experiment

### Step 1 — select circuits

Reads the InferQ metadata parquet shards, filters to circuits with at least
one prior successful RDBMS run, assigns each to a bin by qubit count, and
samples a fixed quota per bin with qubit sub-stratification. Emits a JSONL
manifest consumed by `run_experiment.py`.

```bash
cd InferQ

# Pilot run (5 circuits / bin, ~25 circuits total):
python -m experiments.ooc.select_circuits --pilot

# Full run (20 circuits / bin, ~73 circuits total):
python -m experiments.ooc.select_circuits
```

Output: `data/ooc/circuits.jsonl`

### Step 2 — run the experiment

```bash
python -m experiments.ooc.run_experiment --resume
```

The orchestrator iterates over every `(circuit, cap, engine, method)` triple,
enforces the memory cap via cgroup / Docker, runs the worker subprocess, reads
cgroup counters, and appends one CSV row per timed run to
`experiments/ooc/results/results.csv`.

`--resume` skips triples already present in the CSV, so the experiment can
be interrupted and restarted safely.

Estimated runtime: a few hours (pilot) to a full day (full run), depending
on how many B3 / B4 circuits are selected.

### Optional — run fine-tuned RDBMS profiles

To run only the three database engines with cap-aware engine settings, use the
fine-tuned wrapper. It reuses `run_experiment.py`, but executes one
`(cap, engine)` slice at a time with explicit tuning overrides and writes to a
separate CSV by default:

```bash
python -m experiments.ooc.run_finetuned_experiment --resume
```

Profiles:

- `balanced` (default): larger memory budgets while leaving cgroup headroom.
- `spill_friendly`: small DBMS memory budgets, optimized for spill visibility.
- `memory_aggressive`: uses most of the cap, useful for best-case latency
  comparisons but more likely to hit cgroup OOM.

Useful variants:

```bash
# Inspect exact per-engine settings without launching the experiment:
python -m experiments.ooc.run_finetuned_experiment --dry-run --caps-gb 4

# Run the spill manifest with aggressive settings:
python -m experiments.ooc.run_finetuned_experiment \
    --manifest data/ooc/circuits_spill.jsonl \
    --profile memory_aggressive --mode split --resume
```

### Step 3 — verify sanity

```bash
python -m experiments.ooc.analyze
python -m experiments.ooc.plot_ooc
```

Sanity checks to make in `results/summary_by_engine_cap.csv`:

- **B0** circuits: `spill = 0` on every RDBMS at every cap; `aer` rows all
  `success`.
- **B2** circuits: `aer/statevector` shows `oom_internal` at cap=4; succeeds
  at cap=8 and 16.
- **B3** circuits: same, but Aer also OOMs at cap=8.
- **B4** circuits: `aer/statevector` is `oom_internal` at every cap; RDBMS
  row shows `success` — this is the headline case.
- Every row: `cgroup_swap_peak_bytes = 0`. If not, swap enforcement is broken.

---

## Re-running after the spill / cgroup fixes

The first full run produced two systematic measurement bugs that have since
been fixed in code. To collect paper-ready numbers, the affected rows must
be re-run:

1. **Move `OOC_TMP_ROOT` to NVMe** — confirm the path is not tmpfs:
   ```bash
   findmnt -no FSTYPE -T "$OOC_TMP_ROOT"   # must NOT be tmpfs
   ```
   The default has been changed from `/tmp/inferq_ooc` to `/data/inferq_ooc`.
   If your NVMe is mounted elsewhere, set `OOC_TMP_ROOT` accordingly.

2. **Confirm the cgroup peak fix is reading the right cgroup**: launch one
   triple, then verify the resulting `cgroup_mem_peak_bytes` value is
   bounded by the cap, not a fixed large number.

3. **Strip and rerun**: the simplest path is to discard the old CSV (it has
   bogus memory and zero spill) and re-run the full sweep:
   ```bash
   mv experiments/ooc/results/results.csv experiments/ooc/results/results.pre_fix.csv
   python -m experiments.ooc.run_experiment
   ```
   To rerun only the rows that landed `success` (preserving error rows) and
   re-measure them with the corrected metrics:
   ```bash
   python -m experiments.ooc.run_experiment --resume --rerun-statuses success
   ```

---

## Re-running missing or failed results

Use `--resume --rerun-statuses` to strip rows with a given status from the
CSV and re-queue those triples. The stripped rows are removed before new
results are appended, so there are no duplicates.

```bash
# Re-run everything that errored (wrong method name, connection refused, etc.):
python -m experiments.ooc.run_experiment --resume --rerun-statuses error

# Re-run postgres startup failures too:
python -m experiments.ooc.run_experiment --engines postgres \
    --resume --rerun-statuses "error,pg_startup_failed"

# Re-run a single engine / method combination:
python -m experiments.ooc.run_experiment \
    --engines aer --aer-methods matrix_product_state \
    --resume --rerun-statuses error
```

Available status values: `success`, `timeout`, `oom_internal`, `oom_kill`,
`error`, `pg_startup_failed`, `query_gen_timeout`.

---

## Configuration reference

All knobs live in `InferQ/config.py::PipelineConfig.OOC` and can be
overridden with environment variables:

| Env var | Default | Meaning |
|---------|---------|---------|
| `OOC_CAPS_GB`    | `16,8,4`                     | Memory caps to sweep |
| `OOC_ENGINES`    | `postgres,duckdb,sqlite`     | Engines to run |
| `OOC_N_RUNS`     | `1`                          | Timed runs per triple |
| `OOC_WARMUP`     | `1`                          | Warm-up runs (discarded) |
| `OOC_TIMEOUT`    | `1800`                       | Per-run timeout (seconds) |
| `OOC_DROP_CACHE` | `True`                       | Drop page cache between runs |
| `OOC_TMP_ROOT`   | `/data/inferq_ooc`           | DuckDB / SQLite temp dir. **Must be on a real block device (NVMe).** `/tmp` is tmpfs on most distros — writes go to RAM, count against the cgroup cap, and don't appear in `cgroup_io_write_bytes`. The worker logs a warning if it detects tmpfs. |
| `OOC_PG_IMAGE`     | `inferq-ooc-postgres:12.22`  | Tuned PostgreSQL 12.22 Docker image |
| `OOC_PG_PORT`      | `54320`                      | Host port for Postgres container |
| `OOC_WORKER_IMAGE` | `inferq-ooc-worker:latest`   | Worker runtime image (DuckDB / SQLite / Aer) |
| `OOC_RUNNER`       | `docker`                     | `docker` (cap-enforced) or `none` (smoke test, no cap) |
| `OOC_DUCKDB_MEMORY_MB` | `512`                   | DuckDB `memory_limit` inside the cgroup cap |
| `OOC_DUCKDB_PAD_MB`    | `1024`                  | Headroom kept outside DuckDB `memory_limit` for planner/runtime allocations |
| `OOC_SQLITE_CACHE_MB`  | `64`                    | SQLite `PRAGMA cache_size` budget |
| `OOC_PG_SHARED_BUFFERS_MB` | cap-derived          | Override PostgreSQL `shared_buffers` in the tuned image |
| `OOC_PG_WORK_MEM_MB`       | `64`                 | Override PostgreSQL `work_mem` in the tuned image |
| `OOC_PG_MAINT_WORK_MEM_MB` | `256`                | Override PostgreSQL `maintenance_work_mem` in the tuned image |
| `OOC_PG_EFFECTIVE_CACHE_MB` | cap-derived         | Override PostgreSQL `effective_cache_size` in the tuned image |
| `OOC_PG_TEMP_FILE_LIMIT_MB` | `cap_gb * 4096`     | Override PostgreSQL `temp_file_limit` in the tuned image |

**Use `inferq-ooc-postgres:12.22` for the Postgres image** (built in step 2
above). The stock `postgres` image works but skips the tuned `postgresql.conf`
(shared_buffers, work_mem, temp_file_limit are not scaled to the cap).

### Aer methods

The full sweep is `automatic`, `statevector`, `matrix_product_state`,
`density_matrix`, `stabilizer`. Notes:

- `matrix_product_state` — the correct Qiskit Aer name (not `MPS`).
- `density_matrix` — requires `coupling_map=None` on the simulator and the
  transpile call; otherwise Aer rejects circuits with > 15 qubits.
- `stabilizer` — only valid for Clifford circuits; returns
  `"invalid parameters"` for general circuits, which is expected.

---

## Output schema

`experiments/ooc/results/results.csv` — one row per `(circuit, cap, engine, method, run_idx)`:

```
circuit_hash, num_qubits, num_gates, prior_peak_mem_gb, bin,
engine, method, cap_gb, run_idx,
wall_time_s, tracemalloc_peak_bytes, proc_vm_peak_bytes,
proc_io_read_bytes, proc_io_write_bytes,
cgroup_mem_peak_bytes, cgroup_swap_peak_bytes,
cgroup_io_read_bytes, cgroup_io_write_bytes,
dbms_temp_bytes_written, dbms_temp_bytes_read,
spill_proxy_bytes, temp_dir_peak_bytes, temp_dir_final_bytes, spill_metric_kind,
status, error_msg, scope_unit, container_id, host_timestamp
```

`run_idx` is `warmup`, `0`, `1`, or `2`. `cgroup_*` counters cover the
entire subprocess (all runs combined) and are repeated on every row for
that triple.

---

## Troubleshooting

**`envsubst: command not found` in Postgres container**
The custom image was not built with `gettext-base`. Rebuild:
```bash
./experiments/ooc/docker/build.sh
```

**`Postgres did not become ready in 60s`**
The container crashed before Postgres finished initialising. Check logs:
```bash
docker logs <container_name>
```
Common causes: port 54320 already in use (`ss -tlnp | grep 54320`); or a
previous container was not cleaned up (`docker rm -f $(docker ps -aq
--filter "name=pg_ooc")`).

**`connection to server ... failed: Connection refused` in worker**
The readiness check in `start_pg_container` passed but Postgres died before
the worker connected. This was a bug in earlier versions of the code (TCP
check only, no psycopg2 handshake). Ensure the latest code is pulled.

**Worker dies with rc=137**
OOM-killed by the kernel cgroup. Expected for Aer on B4 circuits; recorded
as `status=oom_kill`.

**`docker: Error response from daemon: Conflict. The container name ... is already in use`**
Stale worker container from a crashed orchestrator. Sweep:
```bash
docker ps -a --filter "name=ooc_worker_" -q | xargs -r docker rm -f
docker ps -a --filter "name=pg_ooc_" -q | xargs -r docker rm -f
```

**`cgroup_mem_peak_bytes = 0`**
The orchestrator could not find the cgroup after the scope exited. The
worker self-reports cgroup counters as a fallback — if both are zero the
cgroup v2 unified hierarchy is not mounted. Check: `mount | grep cgroup2`.

**`dbms_temp_bytes_written = 0` for DuckDB under a tight cap**
DuckDB's profile JSON schema varies by version. The parser in
`_duckdb_sum_spill` is conservative. New runs still emit
`proc_io_write_bytes`, `spill_proxy_bytes`, and temp-directory diagnostics, so
do not interpret a zero DuckDB profile counter as no spill by itself.

**`cgroup_mem_peak_bytes` is the same large value (~system memory) on every row**
Pre-Docker bug — the orchestrator was reading a parent cgroup slice (typically
`user.slice`) instead of the intended per-run cgroup.
The current code runs every engine inside a Docker container with
`--memory=cap`, so this should not happen. If it does, verify the runner:
```bash
docker ps -a --filter "name=ooc_worker_" --filter "name=pg_ooc_"
docker inspect <container_name> | grep -E '"Memory"|"MemorySwap"'
```
Expect non-zero `Memory` ≈ cap × 1 GiB. If `Memory: 0`, the orchestrator
fell back to `--runner=none` — re-run with `--runner=docker` explicitly.

**`SQLITE_TMPDIR` ignored**
Newer SQLite versions deprecate the `temp_store_directory` pragma. The
worker falls back to the `SQLITE_TMPDIR` / `TMPDIR` environment variables.
Verify temp files appear under `/tmp/inferq_ooc/sqlite_*/` during a run.
For SQLite, use `spill_proxy_bytes` / `proc_io_write_bytes` in summaries and
figures; the DBMS temp-byte columns are intentionally empty because Python's
SQLite wrapper does not expose reliable query-level spill bytes.
