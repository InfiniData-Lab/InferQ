# InferQ demo circuits (SQL)

Three quantum circuits compiled by **InferQ** into a single SQL query each, spanning
sparse → dense. Every query simulates the circuit by contracting its tensor network
in SQL and returns the resulting statevector. All three run in well under a second on
a laptop (timings below are DuckDB on an M-series Mac).

"Sparse vs dense" here is the overall contraction weight — gate count, two-qubit-gate
content, query size, and how dense the output statevector is. They increase together
across the three examples.

| file | qubits | gates | 2-qubit gates | SQL CTEs | SQL size | nonzero amplitudes | DuckDB runtime |
|------|:------:|:-----:|:-------------:|:--------:|:--------:|:------------------:|:--------------:|
| `sparse_28cc090e.sql` | 10 | 1  | 0  | 11 | 2.4 KB | 2 (sparse state)        | ~0.004 s |
| `middle_bbef2eb0.sql` | 10 | 31 | 10 | 45 | 12 KB  | 1024 (full 10-qubit state) | ~0.016 s |
| `dense_744d3b5c.sql`  | 11 | 61 | 23 | 76 | 20 KB  | 2048 (full 11-qubit state) | ~0.17 s  |

Each `*.sql` has a matching `*.qpy` (the original Qiskit circuit) for reference.

## Result format

Each query returns the statevector in sparse form — **one row per nonzero amplitude**:

- one integer column per qubit (`i, j, k, …`), each `0`/`1`, giving the basis state;
- `re`, `im` — the real and imaginary parts of the complex amplitude.

Example (the sparse circuit is a Hadamard-like superposition on the first qubit):

```
 i  j  k  l  m  n  o  p  q  r        re                       im
 0  0  0  0  0  0  0  0  0  0   0.7071067811865475   0.0
 0  0  0  0  0  0  0  0  0  1  -0.7071067811865476  -8.66e-17
```

## How to run

The queries are plain SQL and are portable across **DuckDB, SQLite, and PostgreSQL**
(this is InferQ's point — the same query runs on any of them).

DuckDB (recommended, fastest):
```bash
duckdb -c ".read dense_744d3b5c.sql"
# or in Python:  import duckdb; print(duckdb.sql(open('dense_744d3b5c.sql').read()))
```

SQLite:
```bash
sqlite3 :memory: < dense_744d3b5c.sql
```

PostgreSQL:
```bash
psql -d postgres -f dense_744d3b5c.sql
```

To verify a result, sum `re*re + im*im` over all rows — it should equal 1 (the
statevector is normalized).
