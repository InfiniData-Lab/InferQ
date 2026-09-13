# InferQ

InferQ generates, simulates and analyzes quantum circuits for benchmark and
dataset construction. It combines a configurable circuit generator, a
multiprocessing pipeline, Qiskit/Aer and InfiniQuantumSim simulation paths,
static/graph/dynamic/SQL feature extraction, duplicate detection, a local
content-addressed circuit store and optional Azure Blob + Table upload.

## Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
with two members.

| Path | What it is |
| --- | --- |
| `src/inferq/` | The `inferq` distribution — the only thing that is published. |
| `experiments/` | Workspace member `inferq-experiments`. Research runners, figure scripts and the out-of-core harness. Never published. |
| `tests/` | The test suite, including the offline OOC fixtures under `tests/fixtures/`. |
| `docs/` | Prose docs plus the generated SQL query-structure reference. |
| `tools/` | Repository tooling: doc generation, shell helpers, environment probes. |

Inside `src/inferq/`:

| Package | Responsibility |
| --- | --- |
| `paths` | The one place a filesystem path is resolved. |
| `sql` | Query-mode lowering (`monolithic`, `monolithic_materialized`, `split`). Dependency-free leaf. |
| `config` | Settings: pipeline bounds, generator selection, simulator limits, storage and Azure defaults. |
| `generators` | `base`, `params`, `registry`, `merger`, `composer`, plus `algorithms/` and `state_prep/`. |
| `features` | Static, graph, dynamic and SQL feature extraction. |
| `simulation` | Simulation backends and result processing. |
| `storage` | QPY serialization, hashing, the local content-addressed store. |
| `remote` | Azure Blob and Table clients. |
| `transfer` | Bulk download/upload between the local store and Azure. |
| `datasets` | Third-party corpora: the registry, the fetcher and the SupermarQ/MQT Bench/QASMBench loaders. |
| `rerun` | Reprocessing a stage over circuits that already exist. |
| `pipeline` | Multiprocessing orchestration and worker code. |
| `cli` | The `inferq` console script. |

Nothing generated or fetched is stored inside the source tree. See
[Data locations](#data-locations).

## Setup

InferQ targets Python `>=3.12,<3.14`.

```bash
uv sync
```

That installs `inferq` in editable mode, installs the `experiments` member's
dependencies, and installs the `dev` group (pytest, ruff). `pyproject.toml` is
the single source of dependency truth; there is no `requirements.txt`.

Without uv:

```bash
python -m pip install -e .
```

### Extras and groups

The base install is deliberately small — it is what you need to generate,
simulate with Aer, extract features and write circuits locally.

| Install | Adds |
| --- | --- |
| `uv sync --extra azure` | Azure Blob + Table storage (`inferq.remote`, `inferq.transfer`). |
| `uv sync --extra datasets` | SupermarQ and MQT Bench loaders. |
| `uv sync --extra sql` | DuckDB, PostgreSQL and the einsum contraction planner. |
| `uv sync --all-extras` | All of the above. |
| `uv sync --group infiniquantum` | InfiniQuantumSim, the tensor-network-to-SQL lowering. |

InfiniQuantumSim is not on PyPI. PyPI rejects any distribution whose
`Requires-Dist` carries a direct URL — extras included — so it cannot be an
extra without blocking every release. It is a PEP 735 dependency group resolved
through `[tool.uv.sources]`, which is lockfile-local and never reaches the
wheel. Every SQL-backed path degrades gracefully when it is absent.

InfiniQuantumSim pulls in its own array-store dependencies (SciDB and TileDB).
InferQ never benchmarks those two backends — they expect servers this project
does not run — so they are omitted from every simulation request.

## The `inferq` command

One console script replaces every `python <path>` invocation.

```
inferq catalog    list circuits recorded in Azure Table Storage
inferq data       list, fetch and verify the registered benchmark datasets
inferq download   download circuits from Azure Blob Storage
inferq ingest     ingest circuits from an external benchmark suite
inferq paths      show the resolved data, cache, state and output directories
inferq rerun      reprocess stored circuits (simulations, SQL or dynamic features)
inferq run        generate, simulate and store circuits
inferq smoke      end-to-end check of the local install
inferq upload     upload local circuits to Azure Blob Storage
```

Sub-command modules are imported only once the command is selected, so
`inferq --help` does not pay for Qiskit, Aer or the Azure SDK.

## Data locations

No path is resolved anywhere but `inferq.paths`, and no default points inside
the checkout. Each root follows the XDG base directories and is overridable:

| Env var | Default | Holds |
| --- | --- | --- |
| `INFERQ_DATA_DIR` | `~/.local/share/inferq` | Fetched datasets and the local circuit store. |
| `INFERQ_CACHE_DIR` | `~/.cache/inferq` | Re-derivable scratch. |
| `INFERQ_STATE_DIR` | `~/.local/state/inferq` | Checkpoints and logs. |
| `INFERQ_OUT_DIR` | `<checkout>/out`, else `$PWD/out` | Experiment results and figures. |

```bash
inferq paths          # print the resolved roots and whether they exist
```

Directories are created by the writer that needs them, never at import time.

## Configuration

`src/inferq/config/` holds the defaults: pipeline batch sizes and worker counts,
circuit size limits, generator-selection behavior, synergy rules, simulator
limits, InfiniQuantumSim method selection, storage and Azure settings, and OOC
defaults. Many values accept an environment override; the source-of-truth
defaults live in `PipelineConfig`.

Key sections:

- `PIPELINE_DEFAULTS` — worker count, batch size, upload cadence, iteration
  limit, batch timeout.
- `CIRCUIT_GENERATION` — qubit/depth/repetition bounds, measurement setting,
  seed, max generator count, stopping probability, max circuit size.
- `SYNERGY_RULES` — conditional generator-selection boosts.
- `SIMULATION` — Aer limits and InfiniQuantumSim backend selection.
- `OOC` — memory caps, engine list, temp paths, Docker image names.

For Azure-backed runs, copy `.env.example` to `.env` and fill in the connection
details.

## Benchmark datasets

Third-party corpora are fetched and verified, never vendored. The registry lives
at `src/inferq/datasets/data/datasets.toml` and ships in the wheel: it records
the upstream URL, the pinned commit, an ordered mirror list, and a **sha256 per
file**, so a fetched copy is checkable rather than merely claimed to match.

```bash
inferq data list                 # what is registered, and what is present
inferq data fetch qasmbench      # download, verify, unpack
inferq data verify --all         # re-check an existing copy
```

A fetch stages into a temporary directory and verifies before it replaces
anything, so a failed fetch never damages the copy you already have. Files are
unpacked under `$INFERQ_DATA_DIR/datasets/<key>/`.

Loaders for SupermarQ, MQT Bench and QASMBench live in `inferq.datasets`. See
[`docs/benchmark-suites.md`](docs/benchmark-suites.md) for the full benchmark
table, per-suite inventory, algorithm descriptions and duplicate markings. The
curated inventory CSVs (109 suite-specific entries; 85 algorithm families after
deduplication) are wheel package data under `inferq/datasets/data/`.

Ingest suite circuits into the pipeline with:

```bash
inferq ingest --suites qasmbench
```

## Production pipeline

The normal dataset-generation path: generate circuits, skip known duplicates,
extract features, run the configured simulators, write local `.qpy` artifacts
and metadata, and optionally upload new circuits to Azure. This is not the
out-of-core RDBMS experiment harness described further down.

| Mode | Command | Use when |
| --- | --- | --- |
| `parallel` | `inferq run` or `inferq run parallel` | Generating dataset batches with multiprocessing. |
| `single` | `inferq run single` | Running one generated circuit through extraction, simulation and storage. |
| `interactive` | `inferq run interactive` | Composing a circuit from generator templates by hand first. |

```bash
inferq run --workers 8 --batch-size 50 --iterations 10
inferq run --azure-interval 500
inferq run --profile
inferq run interactive --generate-only
```

Interactive mode enumerates the generator templates, accepts indexes, names or
ranges such as `1,13` or `GHZ,QFTGenerator`, previews each template's default
parameters and lets you override them; the composed circuit can then go through
the same extraction/simulation/storage path. See
[`docs/interactive.md`](docs/interactive.md).

Database-backed simulation is configured through
`SIMULATION["infiniquantum"]`. Accepted method names are `psql`, `sqlite`,
`ducksql`, `umbra`, `eqc`, `np_mps` and `np_one_shot`; `omit_methods` skips
methods for a run. The default config omits the heavier database backends
(`psql`, `ducksql`, `umbra`) unless explicitly enabled, while still recording
SQL-derived features. The SQL execution shape comes from
`SIMULATION["infiniquantum"]["query_mode"]` or `IQ_QUERY_MODE`, one of
`monolithic` (default), `monolithic_materialized` or `split`.

The shell wrapper adds environment checks, log-file naming and basic monitoring:

```bash
./tools/run_parallel.sh --workers 8 --batch-size 50 --iterations 10
```

## Generator templates and synergies

Each generator implements a small interface: produce representative parameters,
then build a Qiskit circuit from them. Algorithm templates cover QFT, QPE, QAOA,
Grover, QNN, VQE, amplitude estimation, Deutsch-Jozsa and quantum walks;
state-preparation templates cover GHZ, W-state, graph states, RealAmplitudes,
TwoLocal, EfficientSU2 and random circuits. Every algorithm uses the same
one-module-per-algorithm layout.

`inferq.generators.merger` composes templates into hierarchical circuits. It
does not choose each template independently: after one generator is selected the
merger updates the probability distribution for the next choice. The type-level
rules are `SYNERGY_RULES` in the config:

```python
{"trigger": ["QFTGenerator"], "targets": ["QPE"], "multiplier": 2.5}
```

`trigger` names the selected generator class, `targets` the generators to boost,
`multiplier` how strongly.

## SQL query-structure reference

Representative InfiniQuantumSim query structures for all 17 generators are
generated into `docs/query-structures/<generator>/`:

- `query_structure.md` — circuit parameters, operation counts, CTE counts, variant notes.
- `monolithic.sql` — the raw `WITH ... SELECT` query.
- `monolithic_materialized.sql` — the same query with `AS MATERIALIZED` CTE hints.
- `split.sql` — one materialized `K*` contraction table per step plus the final SELECT.

Regenerate them with:

```bash
uv run python tools/gen_query_docs.py
```

`src/inferq/generators/sql-templates.md` explains the recursive SQL layout and
how the `K*` contraction chain maps to the three modes.
`tests/test_sql_query_modes.py` pins the lowering by re-deriving the
materialized and split forms from each committed monolithic query.

## OOC and fine-tuning experiments

`experiments/` lowers InfiniQuantumSim tensor contractions into SQL and runs them
through relational engines under explicit memory caps. It is a workspace member,
not part of the distribution: `uv sync` installs its dependencies but never
builds it, so research code cannot reach the wheel. Run its modules with `-m`
from the repository root.

| Package | What it does |
| --- | --- |
| `experiments/ooc/` | Out-of-core and limited-memory experiments; RDBMS spill behavior against Aer. |
| `experiments/finetuned_rdbms/` | Raw-monolithic RDBMS benchmark runs and MLOS-based tuning. |
| `experiments/analysis/` | Figure and dataset scripts. `plotting.py` holds the shared palette, byte-axis formatters and figure writer. |
| `experiments/misc/` | One-off runners kept for provenance. |
| `experiments/_common/` | Helpers shared across the above: qubit-count binning, cursors, the QPY-plus-manifest writer. |

```bash
uv run python -m experiments.ooc.run_experiment \
  --engines postgres,duckdb,sqlite \
  --mode split \
  --resume

uv run python -m experiments.finetuned_rdbms.run_all_116 --prepare-only
uv run python -m experiments.finetuned_rdbms.run_all_116 \
  --engines duckdb,sqlite,postgres --profile balanced --n-runs 3 --warmup 1

uv run python -m experiments.finetuned_rdbms.mlos_tune_rdbms \
  --engines duckdb,sqlite,postgres --pilot-size 12 --trials 20 --validate
```

MLOS tuning needs the `experiments` member's own extra:
`uv sync --all-packages --extra tuning`.

Engines:

- `postgres` — PostgreSQL 12.22 in a separate Docker container; the custom
  `inferq-ooc-postgres:12.22` image applies cap-aware settings before each run.
- `duckdb` — embedded in the worker container, with an explicit memory limit and
  spill directory.
- `sqlite` — stdlib SQLite in the worker container. Split mode uses disk-backed
  tables rather than TEMP tables, so intermediates do not stay in heap on builds
  where `PRAGMA temp_store` is ineffective.
- `umbra` — InfiniQuantumSim's Umbra backend; omitted from the default simulator
  config unless explicitly enabled.
- `aer` — Qiskit Aer baseline, for simulator comparison rather than SQL execution.

Query modes, as used by the runner:

- `monolithic` — the raw `WITH ... SELECT`. Closest translation, but DuckDB and
  SQLite can inline the whole CTE cascade and exhaust memory on larger circuits.
- `monolithic_materialized` — one query plus `AS MATERIALIZED` hints. PostgreSQL,
  DuckDB and SQLite all understand this form.
- `split` — every `K*` contraction CTE becomes a materialized table, then the
  final SELECT runs. Default for out-of-core work: it bounds peak memory to
  roughly one contraction step.

All three are implemented once in `inferq.sql`. The OOC worker, the fine-tuned
RDBMS runner, the simulator's SQL backend and the reference SQL generator all
lower through that module, so they cannot drift apart.

See [`experiments/ooc/README.md`](experiments/ooc/README.md),
[`experiments/ooc/DESIGN.md`](experiments/ooc/DESIGN.md) and
[`experiments/finetuned_rdbms/README.md`](experiments/finetuned_rdbms/README.md)
for Docker setup, memory-cap accounting, spill metrics, tuning profiles and
result schemas.

## Smoke test

`inferq smoke` answers one question: is this install set up to run the pipeline?
It drives the parallel pipeline over a handful of small circuits and then checks
that every artifact landed on disk.

```bash
inferq smoke                              # 3 circuits, local only
inferq smoke --circuits 5 --query-mode split
inferq smoke --azure                      # include the upload step
```

It first reports the interpreter and package versions, whether InfiniQuantumSim
is installed, and which SQL engines are reachable. SQLite and DuckDB run
in-process and always take part. PostgreSQL and Umbra are probed with the
variables they read (`POSTGRES_*`, `UMBRA_*`); an engine that does not answer is
named along with the reason and the variables that would configure it, then
omitted so the simulation never blocks on a connection that will not open. A
missing engine is reported, never fatal.

Azure upload is off unless `--azure` is passed, so a smoke run never writes
throwaway circuits into shared storage. Generation limits are pinned low and
each attempt uses a fresh seed, so repeat runs produce new circuits rather than
colliding with duplicate detection.

## Testing

```bash
uv sync
uv run pytest
```

`tests/test_import_integrity.py` imports every module under `src/` and
`experiments/`, skipping only those whose optional third-party dependencies are
absent. It is the guard against bare sibling imports and stale symbols that
static review misses. Environment and integration probes live under
`tools/environment-test/`; they talk to live services and are excluded from
collection.

Two structural guards run in CI and can be run by hand:

```bash
uv run python tools/check_repo_hygiene.py dist/*.whl
uv run --group infiniquantum python tools/gen_query_docs.py --check
```

The first rejects tracked-but-ignored files, `.gitignore` negations, any tracked
file over 1 MB, stored notebook outputs, path resolution outside `inferq.paths`,
and a wheel that carries data or research code. The second fails if the SQL
lowering changed without `docs/query-structures/` being regenerated.

## Operational notes

- Generated circuits are written one directory per circuit hash, holding
  `circuit.qpy` (or a fallback serialization), `meta.json`, and — whenever
  InfiniQuantumSim lowered the circuit — `circuit.sql`, the query that was
  actually executed. The mode that shaped it is recorded as `sql_query_mode` in
  `meta.json`. The query is a file rather than a metadata field because `split`
  runs to tens of kilobytes.
- Duplicate detection uses local cache state and, when enabled, Azure metadata.
- The parallel pipeline logs mostly batch-level status; worker-level debug output
  is suppressed unless logging is configured more verbosely.
- `docs/provenance/` records the sha256 of large generated artifacts that were
  deliberately left out of the repository.

## License

MIT. See [`LICENSE`](LICENSE).
