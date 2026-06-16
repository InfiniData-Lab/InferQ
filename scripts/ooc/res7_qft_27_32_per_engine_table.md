# QFT q=27..32 — per-(qubits, engine, cap) results

Combined 311 rows from `res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.csv` and `res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.rerun_disk_full.csv`; rerun rows take precedence on `(circuit_hash, cap_gb, engine, method, run_idx, mode)`.

- Source mix: rerun=251, original=60
- Status totals: success=132, error=121, oom_internal=44, timeout=12, oom_kill=2

## Per-cell summary

| qubits | engine | cap_gb | runs | ok | wall_s (med) | wall_s (min-max) | outcome |
|---|---|---|---|---|---|---|---|
| 27 | aer | 4 | 6 | 6/6 | 96 | 94–96 | ok |
| 27 | aer | 8 | 6 | 6/6 | 94 | 91–96 | ok |
| 27 | aer | 16 | 6 | 6/6 | 92 | 91–94 | ok |
| 27 | duckdb | 4 | 1 | 0/1 | — | —–— | OOM-killed×1 |
| 27 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb OOM×2 |
| 27 | duckdb | 16 | 6 | 6/6 | 607 | 606–610 | ok |
| 27 | postgres | 4 | 6 | 6/6 | 529 | 526–530 | ok |
| 27 | postgres | 8 | 6 | 6/6 | 526 | 525–528 | ok |
| 27 | postgres | 16 | 6 | 6/6 | 515 | 514–517 | ok |
| 27 | sqlite | 4 | 6 | 6/6 | 1317 | 1316–1320 | ok |
| 27 | sqlite | 8 | 6 | 6/6 | 1299 | 1298–1300 | ok |
| 27 | sqlite | 16 | 6 | 6/6 | 1291 | 1287–1296 | ok |
| 28 | aer | 4 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 28 | aer | 8 | 6 | 2/6 | 185 | 185–186 | silent error×4 |
| 28 | aer | 16 | 6 | 4/6 | 184 | 183–187 | silent error×2 |
| 28 | duckdb | 4 | 1 | 0/1 | — | —–— | OOM-killed×1 |
| 28 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb OOM×2 |
| 28 | duckdb | 16 | 6 | 6/6 | 1496 | 1488–1503 | ok |
| 28 | postgres | 4 | 6 | 6/6 | 1013 | 1010–1020 | ok |
| 28 | postgres | 8 | 6 | 6/6 | 1384 | 1381–1387 | ok |
| 28 | postgres | 16 | 6 | 6/6 | 1011 | 1008–1013 | ok |
| 28 | sqlite | 4 | 6 | 6/6 | 2673 | 2669–2678 | ok |
| 28 | sqlite | 8 | 6 | 6/6 | 2694 | 2686–2697 | ok |
| 28 | sqlite | 16 | 6 | 6/6 | 2614 | 2613–2630 | ok |
| 29 | aer | 4 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 29 | aer | 8 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 29 | aer | 16 | 6 | 6/6 | 81 | 81–85 | ok |
| 29 | duckdb | 4 | 2 | 0/2 | — | —–— | duckdb OOM×2 |
| 29 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 29 | duckdb | 16 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 29 | postgres | 4 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 29 | postgres | 8 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 29 | postgres | 16 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 29 | sqlite | 4 | 6 | 6/6 | 5228 | 5222–5239 | ok |
| 29 | sqlite | 8 | 6 | 6/6 | 5165 | 5147–5196 | ok |
| 29 | sqlite | 16 | 6 | 6/6 | 5245 | 5240–5257 | ok |
| 30 | aer | 4 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 30 | aer | 8 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 30 | aer | 16 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 30 | duckdb | 4 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 30 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 30 | duckdb | 16 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 30 | postgres | 4 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 30 | postgres | 8 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 30 | postgres | 16 | 6 | 0/6 | — | —–— | pg temp_file_limit×6 |
| 30 | sqlite | 4 | 7 | 0/7 | — | —–— | sqlite disk full×6; error: worker rc=130; no output: \n    runner(q×1 |
| 30 | sqlite | 8 | 6 | 0/6 | — | —–— | wall-time >2h×6 |
| 30 | sqlite | 16 | 6 | 0/6 | — | —–— | wall-time >2h×6 |
| 31 | aer | 4 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 31 | aer | 8 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 31 | aer | 16 | 2 | 0/2 | — | —–— | aer needs >cap×2 |
| 31 | duckdb | 4 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 31 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 31 | duckdb | 16 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 31 | postgres | 4 | 6 | 0/6 | — | —–— | host disk full×6 |
| 31 | postgres | 8 | 6 | 0/6 | — | —–— | host disk full×6 |
| 31 | postgres | 16 | 6 | 0/6 | — | —–— | host disk full×6 |
| 31 | sqlite | 4 | 6 | 0/6 | — | —–— | sqlite disk full×6 |
| 31 | sqlite | 8 | 6 | 0/6 | — | —–— | sqlite disk full×6 |
| 31 | sqlite | 16 | 6 | 0/6 | — | —–— | sqlite disk full×6 |
| 32 | aer | 4 | 6 | 0/6 | — | —–— | Aer >31 qubits×6 |
| 32 | aer | 8 | 6 | 0/6 | — | —–— | Aer >31 qubits×6 |
| 32 | aer | 16 | 6 | 0/6 | — | —–— | Aer >31 qubits×6 |
| 32 | duckdb | 8 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 32 | duckdb | 16 | 2 | 0/2 | — | —–— | duckdb temp cap×2 |
| 32 | postgres | 8 | 6 | 0/6 | — | —–— | host disk full×6 |
| 32 | postgres | 16 | 6 | 0/6 | — | —–— | host disk full×6 |
| 32 | sqlite | 16 | 6 | 0/6 | — | —–— | sqlite disk full×6 |

## Notes

- `pg temp_file_limit` means PG aborted because a single query's spill exceeded `OOC_PG_TEMP_FILE_LIMIT_MB=65536` (64 GiB). This is a real engine ceiling — not host disk.
- `duckdb temp cap` rows reference DuckDB's `max_temp_directory_size`; if that is not being scaled with `cap_gb`, those small-cap results don't measure memory pressure.
- `wall-time >2h` = OOC_TIMEOUT (7200 s). Real ceiling for sqlite at q≥30 is wall-time, not disk.
- `Aer >31 qubits` is a Qiskit coupling-map limit at q=32, not a memory result.
- `silent error` rows (Aer, q=28, cap=8/16) are a worker bug — reproducible across runs.