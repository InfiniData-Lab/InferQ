
# InferQ

InferQ generates, simulates, and analyzes quantum circuits for benchmark and
dataset construction. It combines a configurable circuit generator, parallel
processing pipeline, Qiskit and InfiniQuantumSim simulation paths, feature
extractors, duplicate detection, local storage, and optional Azure upload.

## What Is In The Repo

- `generators/`: circuit generators for algorithms and state-preparation circuits.
- `generators/algorithms/*_queries/`: documented SQL query structures for algorithm generators.
- `generators/state_prep_circuits/sql/`: documented SQL query structures for state-preparation generators.
- `pipeline/`: multiprocessing orchestration and worker code.
- `simulators/`: simulation backends and simulation-result processing.
- `feature_extractors/`: static, graph, dynamic, and SQL feature extraction.
- `utils/`: storage, hashing, Azure, and duplicate-detection helpers.
- `scripts/`: operational scripts, out-of-core experiments, and benchmark utilities.
- `config.py`: the main control plane for generation, simulation, storage,
  database backend selection, synergies, and experiment defaults.
- `main.py`: the only top-level pipeline entry point. It supports `parallel`,
  `single`, and `interactive` pipeline modes.

## Setup

InferQ targets Python `>=3.12,<3.14`.

```bash
cd InferQ
uv sync
```

If you are not using `uv`, install the project with pip:

```bash
python -m pip install .
```

InfiniQuantumSim is configured as a local editable dependency in
`pyproject.toml`:

```toml
infiniquantumsim = { path = "../Infinidata-rdbms-simulator/", editable = true }
```

Keep that sibling checkout in place when running SQL-backed simulation or query
documentation tools.

## Configuration

`config.py` is the most important driver in the repo. Start there before
changing code: it controls pipeline batch sizes, worker counts, circuit size
limits, generator selection behavior, simulator limits, InfiniQuantumSim
database methods, local/remote storage, Azure settings, OOC defaults, and
finetuning paths. Many values can be overridden by environment variables, but
the source-of-truth defaults are in `PipelineConfig`.

Key sections:

- `PIPELINE_DEFAULTS`: worker count, batch size, upload cadence, iteration
  limit, and batch timeout.
- `CIRCUIT_GENERATION`: qubit/depth/repetition bounds, measurement setting,
  seed, max generator count, stopping probability, and max circuit size.
- `SYNERGY_RULES`: conditional generator-selection boosts used by the
  template-based generator system.
- `SIMULATION`: Qiskit simulator limits and InfiniQuantumSim backend selection.
- `OOC`: out-of-core memory caps, engine list, temp paths, Docker image names,
  and experiment defaults.

For Azure-backed runs, create a local `.env` file:

```bash
cp .env.example .env
```

Then set the Azure connection details expected by the storage helpers.

## Production Pipeline

This is the normal dataset-generation path. It generates circuits, skips known
duplicates, extracts features, runs configured simulators, writes local `.qpy`
artifacts and metadata, and optionally uploads new circuits to Azure. It is not
the same as the out-of-core RDBMS experiment harness described below.

Database-backed simulation is accepted in the production pipeline through the
InfiniQuantumSim configuration in `config.py`. The accepted method names are
`psql`, `sqlite`, `ducksql`, `umbra`, `eqc`, `np_mps`, and `np_one_shot`; set
`SIMULATION["infiniquantum"]["omit_methods"]` to skip methods for a run. The
default config currently omits the heavier database backends (`psql`,
`ducksql`, and `umbra`) unless explicitly enabled, while still allowing the
pipeline to record SQL-derived features and run the configured simulator set.
The SQL execution shape is selected by
`SIMULATION["infiniquantum"]["query_mode"]`, or by `IQ_QUERY_MODE` in the
environment. Accepted values are `monolithic` (default),
`monolithic_materialized`, and `split`.

`config.py` is the main driver for production behavior. It centralizes worker
counts, generator bounds, synergy rules, simulator limits, InfiniQuantumSim
database acceptance, SQL query mode, storage, Azure, and logging defaults. Use
environment variables for run-local overrides; edit `PipelineConfig` when a
default should become part of the repository configuration.

`main.py` supports three production pipeline modes:

| Mode | Command | Use when |
| --- | --- | --- |
| `parallel` | `python main.py` or `python main.py parallel` | Generating dataset batches with multiprocessing. |
| `single` | `python main.py single` | Running one generated circuit through extraction, simulation, and storage. |
| `interactive` | `python main.py interactive` | Manually composing a circuit from generator templates before optionally running the normal pipeline. |

Run the default parallel production pipeline:

```bash
python main.py
```

Useful options:

```bash
python main.py --workers 8 --batch-size 50 --iterations 10
python main.py --azure-interval 500
python main.py --profile
```

The shell wrapper adds environment checks, log-file naming, and basic monitoring
messages:

```bash
./scripts/run_parallel.sh --workers 8 --batch-size 50 --iterations 10
```

For a single generate/extract/simulate/store iteration, use:

```bash
python main.py single
```

For an interactive composition run, use:

```bash
python main.py interactive
```

Interactive mode is a guided pipeline entry point. It enumerates the templates
in `generators/`, accepts indexes, names, or ranges such as `1,13` or
`GHZ,QFTGenerator`, previews each template's generated default parameters, and
lets you override parameters. After the circuit is built, it can run the same
feature extraction, simulation, local storage, and optional Azure upload path as
the generated pipeline.

To only build the composed circuit without processing it:

```bash
python main.py interactive --generate-only
```

`main_parallel.py` has been removed; `main.py` is now the canonical entry point
for parallel, single-run, and interactive modes.

## Generator Templates And Synergies

InferQ uses a template-based circuit generation system under `generators/`.
Each generator implements a small interface: produce representative parameters,
then build a Qiskit circuit from those parameters. The available templates cover
algorithm circuits such as QFT, QPE, QAOA, Grover, QNN, VQE, and quantum walks,
plus state-preparation templates such as GHZ, W-state, graph states,
RealAmplitudes, TwoLocal, EfficientSU2, and random circuits.

`generators/circuit_merger.py` composes these templates into hierarchical
circuits. It does not choose each template independently: after one generator is
selected, the merger updates the probability distribution for the next choice.
The fixed type-level rules live in `config.py` as `SYNERGY_RULES`; for example,
QFT boosts QPE, variational algorithms boost ansatz templates, and entangling
state-preparation templates boost compatible algorithms. To define or tune
synergies, edit `SYNERGY_RULES` with:

```python
{"trigger": ["QFTGenerator"], "targets": ["QPE"], "multiplier": 2.5}
```

`trigger` names the selected generator class, `targets` names the generators to
boost, and `multiplier` controls how strongly their selection probabilities are
increased.

## SQL Query Structure Documentation

Representative InfiniQuantumSim SQL query structures are checked into the
generator folders. Each documented generator has:

- `query_structure.md`: circuit parameters, operation counts, CTE counts, and variant notes.
- `monolithic.sql`: the raw `WITH ... SELECT` query.
- `monolithic_materialized.sql`: the same query with `AS MATERIALIZED` CTE hints.
- `split.sql`: one materialized `K*` contraction table per step plus the final SELECT.

Regenerate algorithm query docs:

```bash
python generators/generate_query_structure_docs.py
```

Regenerate state-preparation query docs:

```bash
python generators/generate_state_prep_query_structure_docs.py
```

See `generators/sql-templates.md` for the recursive SQL file layout, the four
files in each query folder, and how the `K*` contraction chain maps to
monolithic, materialized, and split SQL.

## Existing Benchmarks

InferQ supports generated circuits and imported benchmark suites.

Checked-in benchmark inventory:

- `scripts/benchmark_suites/benchmark_algorithms_full.csv`: 109 suite-specific
  entries.
- `scripts/benchmark_suites/benchmark_algorithms_deduplicated.csv`: 85
  normalized algorithm families after merging equivalent algorithms.
- Source coverage: 8 SupermarQ entries, 34 MQT Bench entries, and 67 QASMBench
  entries. Some families appear in more than one suite, so these counts are not
  additive after deduplication.

Benchmark tooling:

- `scripts/benchmark_suites/`: loaders for SupermarQ, MQT Bench, and QASMBench.
- `scripts/benchmark_suites/qasmbench_qasm/`: vendored QASMBench QASM files and
  manifest metadata.
- `scripts/ingest_benchmarks.py`: ingestion path for suite circuits.
- `scripts/fetch_qasmbench.py`: refreshes vendored QASMBench inputs.
- `data/extremes/` and `data/ooc/`: selected circuit sets used by analysis and
  out-of-core experiments.

See `scripts/benchmark_suites/README.md` for the full benchmark table, per-file
folder inventory, algorithm descriptions, and duplicate-name markings.

## OOC And Fine-Tuning Experiments

InferQ can lower InfiniQuantumSim tensor contractions into SQL and run them
through relational engines for controlled database experiments. This is separate
from the production pipeline: these scripts benchmark specific circuits under
explicit engine settings, memory caps, SQL modes, and tuning profiles.

Experiment areas:

- `scripts/ooc/`: out-of-core and limited-memory experiments. These compare RDBMS
  spill behavior against Aer under explicit memory caps.
- `scripts/finetuned_rdbms/`: raw-monolithic RDBMS benchmark runs and MLOS-based
  tuning over selected circuit sets.
- `analysis/finetuned_rdbms_*`: local output folders for finetuning runs.

Supported database and benchmark engines:

- `postgres`: PostgreSQL 12.22 in a separate Docker container. The custom
  `inferq-ooc-postgres:12.22` image applies cap-aware settings before each run.
- `duckdb`: embedded DuckDB inside the worker container, with an explicit memory
  limit and spill directory.
- `sqlite`: Python stdlib SQLite inside the worker container. Split mode uses
  regular disk-backed tables rather than TEMP tables so intermediates do not
  stay in heap on SQLite builds where `PRAGMA temp_store` is ineffective.
- `umbra`: InfiniQuantumSim's Umbra backend. It is available as an RDBMS
  benchmark target and can be rerun over existing circuits with
  `scripts/rerun_umbra_to_azure.py`; it is omitted from the default simulator
  config unless explicitly enabled.
- `aer`: Qiskit Aer baseline methods, used for simulator comparison rather than
  SQL execution.

The SQL engines used by the OOC runner share these query modes:

- `monolithic`: runs the raw InfiniQuantumSim `WITH ... SELECT` query. This is
  the closest translation, but DuckDB and SQLite can inline the whole CTE
  cascade and exhaust memory on larger circuits.
- `monolithic_materialized`: keeps one query but adds `AS MATERIALIZED` CTE
  hints. PostgreSQL, DuckDB, and SQLite understand this form.
- `split`: decomposes every `K*` contraction CTE into a materialized table, then
  runs the final SELECT. This is the default for out-of-core experiments because
  it bounds peak memory to roughly one contraction step.

Typical database-only OOC runs use:

```bash
python -m scripts.ooc.run_experiment \
  --engines postgres,duckdb,sqlite \
  --mode split \
  --resume
```

Fine-tuned RDBMS runs use the finetuning scripts instead:

```bash
python scripts/finetuned_rdbms/run_all_116.py --prepare-only
python scripts/finetuned_rdbms/run_all_116.py \
  --engines duckdb,sqlite,postgres \
  --profile balanced \
  --n-runs 3 \
  --warmup 1
```

MLOS tuning is available through:

```bash
python scripts/finetuned_rdbms/mlos_tune_rdbms.py \
  --engines duckdb,sqlite,postgres \
  --pilot-size 12 \
  --trials 20 \
  --validate
```

See `scripts/ooc/README.md`, `scripts/ooc/DESIGN.md`, and
`scripts/finetuned_rdbms/README.md` for Docker setup, memory-cap accounting,
spill metrics, tuning profiles, and result schema details.

## Testing

Run the focused test suite with:

```bash
python -m pytest tests
```

Environment and integration checks live under `scripts/environment-test/`.
Those checks still import `run_extraction_pipeline` from `main.py`.

## Operational Notes

- Generated circuits are written under the local circuits directory from `config.py`.
- Duplicate detection uses local cache state and, when enabled, Azure metadata.
- The parallel pipeline intentionally logs mostly batch-level status; worker-level
  debug output is suppressed unless logging is configured more verbosely.
- Large experiment outputs and downloaded benchmark data should stay out of
  commits unless they are intentionally part of a reproducible artifact.
