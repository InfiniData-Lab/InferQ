# Out-of-Core / Limited-Memory RDBMS Experiments

SIGMOD paper 160 revision **E1 / R1.O1 / R2.Q2**. Runs PostgreSQL, SQLite,
DuckDB, and Qiskit Aer on a stratified sample of circuits under explicit memory
caps (16 GB / 8 GB / 4 GB) and captures spill behavior + Aer-vs-RDBMS failure
cases.

## Target machine

Linux with cgroup v2 (Ubuntu 22.04+, RHEL 9+). Reference box:

- Alienware Aurora R13 — 64 GB DDR5, Intel i9-12900KF (16c/24t), Micron 3400
  NVMe 2 TB on ext4. NVMe root (`/`) is used for DBMS temp files.

The experiments will still run on macOS / Windows with `--no-systemd-run` but
the memory caps are not enforced — use only for smoke tests.

## One-time setup

```bash
# 1. Install Docker Engine + enable user service + add user to docker group.
#    See https://docs.docker.com/engine/install/ubuntu/.

# 2. Build the tuned Postgres image.
./scripts/ooc/docker/build.sh                      # → inferq-ooc-postgres:16
# If you'd rather use stock postgres:16, set OOC_PG_IMAGE=postgres:16 — but
# then the temp_file_limit / work_mem config won't be applied.

# 3. NOPASSWD sudoers entry so the orchestrator can drop page cache between
#    runs. Add to /etc/sudoers.d/inferq-ooc (replace USER):
#       USER ALL=(root) NOPASSWD: /usr/bin/tee /proc/sys/vm/drop_caches
#    Then verify:
sync && echo 3 | sudo -n tee /proc/sys/vm/drop_caches >/dev/null && echo ok

# 4. Enable systemd-run --user (only needed if the box has no interactive login
#    session):
loginctl enable-linger "$USER"

# 5. Python deps (inside the InferQ venv):
uv pip install -r InferQ/requirements.txt        # or: pip install -e InferQ/
```

Verify systemd-run works before starting real experiments:

```bash
systemd-run --user --scope --property=MemoryMax=1G --property=MemorySwapMax=0 -- \
    python -c "import os; print('pid', os.getpid())"
```

## Running

### Step 1 — pick circuits

```bash
cd InferQ
python -m scripts.ooc.select_circuits \
    --metadata-dir data/metadata \
    --circuits-dir circuits \
    --pilot                                # drop for the full 100-circuit sample
```

Produces `InferQ/data/ooc/circuits.jsonl` with one JSON entry per selected
circuit: hash, qpy path, prior unconstrained peak, bin assignment.

Bins are by **qubit count**, which directly predicts Aer statevector memory
(`2^N · 16 B`). The prior tracemalloc-based RDBMS memory numbers in the
metadata only see Python heap — they're off by 10–100× on real footprint, so
qubit count is the best OOM-threshold proxy available:

| bin | qubits | Aer statevector | story |
| --- | --- | --- | --- |
| `B0_trivial`            | < 25   | ≤ 512 MB  | baseline; Aer + RDBMS succeed everywhere |
| `B1_aer_ok_all_caps`    | 25–27  | 0.5–2 GB  | Aer fits at every cap; RDBMS maybe spills at 4 GB |
| `B2_aer_fails_at_4`     | 28–29  | 4–8 GB    | Aer OOMs at cap=4, fine at 8/16; RDBMS must spill |
| `B3_aer_fails_at_8`     | 30     | 16 GB     | Aer OOMs at caps 4 and 8, fine at 16 |
| `B4_aer_impossible`     | ≥ 31   | ≥ 32 GB   | **headline** — Aer OOMs at every cap we test |

Pool sizes in the current metadata (RDBMS-successful circuits): B0≈10k, B1=34,
B2=29, B3=9, B4=1. For the full run, expect ~73 circuits total (B3/B4 capped
by availability).

### Step 2 — pilot run

```bash
python -m scripts.ooc.run_experiment --resume
```

For a pilot (25 circuits × 3 caps × 4 engines × 4 runs ≈ 1200 runs), expect
anywhere from a few hours to a full day depending on how many circuits fall
into B3/B4. `--resume` reads the existing CSV and skips
`(circuit, cap, engine, method)` triples already executed.

### Step 3 — verify pilot sanity

```bash
python -m scripts.ooc.analyze
python -m scripts.ooc.plot_ooc
```

Then eyeball:

- `results/summary_by_engine_cap.csv` — per (bin, engine, cap): completion
  rate, median wall time, median spill. Sanity checks:
  - **B0** circuits: `spill = 0` on every RDBMS at every cap; `aer` rows all
    `success`.
  - **B2** circuits: `aer` with `method=statevector` shows `oom_internal` at
    cap=4; succeeds at cap=8 and 16.
  - **B3** circuits: same as B2 but Aer also OOMs at cap=8; RDBMS spill > 0.
  - **B4** circuits: `aer` with `method=statevector` is `oom_internal` at every
    cap; RDBMS row shows `success` — this is the headline case.
  - Every row: `cgroup_swap_peak_bytes = 0` (swap was disabled). If not,
    enforcement is broken.
- `results/aer_failures.csv` — the `headline_case=True` rows are the paper's
  direct evidence.

### Step 4 — full run

```bash
python -m scripts.ooc.select_circuits          # full 20/bin (no --pilot)
python -m scripts.ooc.run_experiment --resume  # resumes on top of pilot
python -m scripts.ooc.analyze
python -m scripts.ooc.plot_ooc
```

Figures land in `scripts/ooc/results/figures/`:

- `completion_rate_vs_cap.pdf`
- `wall_time_vs_cap.pdf`
- `spill_bytes_vs_cap.pdf`
- `aer_failure_table.tex`

## Configuration

Most things live in `InferQ/config.py::PipelineConfig.OOC`; also overridable
via env vars (prefix `OOC_`) — see `get_ooc_config()`. Common knobs:

| env var | default | meaning |
| --- | --- | --- |
| `OOC_CAPS_GB`          | `16,8,4`                    | Comma-separated caps |
| `OOC_ENGINES`          | `postgres,duckdb,sqlite,aer`| Engines to run |
| `OOC_N_RUNS`           | `3`                         | Timed runs per triple |
| `OOC_WARMUP`           | `1`                         | Warm-up runs |
| `OOC_TIMEOUT`          | `1800`                      | Per-run seconds |
| `OOC_DROP_CACHE`       | `True`                      | sudo drop_caches between runs |
| `OOC_TMP_ROOT`         | `/tmp/inferq_ooc`           | DuckDB/SQLite temp dir (NVMe) |
| `OOC_PG_IMAGE`         | `postgres:16`               | Image to run (use `inferq-ooc-postgres:16`) |
| `OOC_PG_PORT`          | `54320`                     | Host port for PG container |

## Output schema

`scripts/ooc/results/results.csv` — one row per `(circuit, cap, engine, method, run_idx)`:

```
circuit_hash, num_qubits, num_gates, prior_peak_mem_gb, bin,
engine, method, cap_gb, run_idx,            # run_idx ∈ {warmup, 0, 1, 2}
wall_time_s, tracemalloc_peak_bytes, proc_vm_peak_bytes,
cgroup_mem_peak_bytes, cgroup_swap_peak_bytes,
cgroup_io_read_bytes, cgroup_io_write_bytes,
dbms_temp_bytes_written, dbms_temp_bytes_read,
status,          # success | timeout | oom_internal | oom_kill | error | pg_startup_failed
error_msg, scope_unit, container_id, host_timestamp
```

`cgroup_mem_peak_bytes` / `io_*_bytes` are for the whole subprocess (all runs +
warmup combined) — they're repeated on every run row. Per-run wall time comes
from the worker JSON.

## Troubleshooting

- **Worker dies with rc=137**: cgroup OOM-killed it. Expected for Aer on B4
  circuits; recorded as `status=oom_kill`.
- **`systemd-run: Unit already exists`**: stale scope — `systemctl --user
  reset-failed`.
- **PG container immediately exits**: check `docker logs pg_ooc_*`. The
  entrypoint refuses to start without `CAP_GB`; the orchestrator sets it.
- **`cgroup_mem_peak_bytes = 0`**: the orchestrator couldn't find the cgroup.
  Verify with `systemctl --user status $SCOPE_UNIT` while the worker is
  running. Usually means cgroup v1 is still mounted — check `mount | grep
  cgroup2`.
- **`dbms_temp_bytes_written = 0` for DuckDB under a tight cap**: DuckDB's
  profile JSON schema varies by version; `_duckdb_sum_spill` in `worker.py` is
  conservative. Grep the profile file under `/tmp/inferq_ooc/duckdb_*/` to
  confirm.
- **`SQLITE_TMPDIR` ignored**: newer SQLite versions deprecate
  `temp_store_directory` pragma. The env-var fallback in the worker covers it
  but double-check the temp dir under `/tmp/inferq_ooc/sqlite_*/` during a run.
