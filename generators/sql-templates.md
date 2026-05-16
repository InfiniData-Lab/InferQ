# SQL Template Artifacts

InferQ stores representative InfiniQuantumSim SQL templates next to the
generator code that produced them. These files are documentation artifacts, not
the primary execution path. They make the SQL shape inspectable without
regenerating a circuit or running a database engine.

## Directory Layout

Algorithm generators use one query folder per algorithm:

```text
generators/algorithms/
  amplitude_estimation/
    query_structure.md
    monolithic.sql
    monolithic_materialized.sql
    split.sql
  deutsch_jozsa/
    ...
  grover_no_ancilla/
    ...
  grover_v_chain/
    ...
  qaoa_queries/
    ...
  qft_queries/
    ...
```

State-preparation generators are grouped under a single `sql/` folder:

```text
generators/state_prep_circuits/sql/
  ghz_queries/
    query_structure.md
    monolithic.sql
    monolithic_materialized.sql
    split.sql
  graph_state_queries/
    ...
  two_local_queries/
    ...
```

The layout is intentionally recursive:

```text
generator family -> generator query folder -> query structure files
```

That keeps algorithm SQL, state-preparation SQL, and source generator code close
enough to compare, while still avoiding a single large shared SQL directory.

## Files In Each Query Folder

Every query folder has the same four-file structure.

- `query_structure.md`: human-readable summary of the representative circuit,
  generator parameters, Qiskit/transpiled operation counts, IQS gate count,
  helper CTEs, `K*` contraction CTEs, and split statement count.
- `monolithic.sql`: the raw InfiniQuantumSim `WITH ... SELECT` query.
- `monolithic_materialized.sql`: the same single SQL statement, but each CTE is
  emitted as `AS MATERIALIZED (...)`.
- `split.sql`: a sequence of materializing statements, one per `K*` contraction
  step, followed by the final SELECT.

## Recursive SQL Shape

InfiniQuantumSim lowers a quantum circuit to an einsum expression and then to a
recursive SQL CTE chain:

1. Tensor/helper CTEs define input state tensors and gate tensors.
2. `K1` contracts the first pair or group of tensors selected by the optimizer.
3. `K2` consumes prior tensors or `K1`.
4. The chain continues through `K3`, `K4`, and so on.
5. The final SELECT reads the last contraction result.

In the monolithic form, the whole recursive contraction chain lives inside one
large `WITH` statement:

```sql
WITH T0(...) AS (...),
     gate_tensor(...) AS (...),
     K1 AS (...),
     K2 AS (...),
     ...
SELECT ...
```

This form is compact and closest to the original InfiniQuantumSim query, but
some engines may inline the entire CTE cascade and plan it as one heap-heavy
join.

The materialized form keeps the same recursion but requests materialization:

```sql
WITH T0(...) AS MATERIALIZED (...),
     gate_tensor(...) AS MATERIALIZED (...),
     K1 AS MATERIALIZED (...),
     K2 AS MATERIALIZED (...),
     ...
SELECT ...
```

The split form turns the recursive `K*` chain into explicit storage boundaries:

```sql
CREATE TEMP TABLE K1 AS WITH T0(...) AS (...), gate_tensor(...) AS (...) SELECT ...;
CREATE TEMP TABLE K2 AS WITH T0(...) AS (...), gate_tensor(...) AS (...) SELECT ...;
...
WITH T0(...) AS (...), gate_tensor(...) AS (...) SELECT ...;
```

For SQLite generation in the OOC worker, split mode can emit regular
disk-backed tables instead of TEMP tables. The checked-in templates use the
generic temp-table representation because they document the SQL structure rather
than one engine's exact execution wrapper.

## Regeneration

Regenerate algorithm templates:

```bash
python generators/generate_query_structure_docs.py
```

Regenerate state-preparation templates:

```bash
python generators/generate_state_prep_query_structure_docs.py
```

The scripts use deterministic representative circuits, deterministic parameter
assignment, and deterministic opt-einsum path selection so checked-in SQL
templates stay stable across reruns.

## Relationship To Database Engines

The checked-in SQL files document query shape. Engine execution is handled by
the production InfiniQuantumSim integration or by the out-of-core workers under
`scripts/ooc/`.

- Production pipeline database-method acceptance is controlled by
  `config.py::PipelineConfig.SIMULATION["infiniquantum"]["omit_methods"]`.
- OOC query mode is controlled by the worker `--mode` option:
  `monolithic`, `monolithic_materialized`, or `split`.
- Fine-tuned RDBMS runs in `scripts/finetuned_rdbms/` benchmark selected circuit
  sets with explicit engine tuning profiles.
