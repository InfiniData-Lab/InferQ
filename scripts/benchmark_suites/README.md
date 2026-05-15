# Benchmark-suite algorithm support

InferQ supports ingesting benchmark circuits from SupermarQ, MQT Bench, and
QASMBench in addition to its randomly generated circuits.

The source-of-truth inventory is:

- `benchmark_algorithms_full.csv`: suite-specific benchmark entries.
- `benchmark_algorithms_deduplicated.csv`: normalized algorithm families after
  merging equivalent algorithms across suites and problem sizes.

Current counts:

| Inventory | Count |
| --- | ---: |
| Suite-specific entries in `benchmark_algorithms_full.csv` | 109 |
| Deduplicated algorithm families in `benchmark_algorithms_deduplicated.csv` | 85 |

The 109 suite-specific entries consist of 8 SupermarQ entries, 34 MQT Bench
entries, and 67 QASMBench entries. The deduplicated CSV has 85 rows, excluding
the header. In that deduplicated list, 8 families have SupermarQ coverage, 34
have MQT Bench coverage, and 52 have QASMBench coverage; these source-coverage
counts are not additive because some families appear in more than one suite.

The deduplicated total is smaller than the per-suite sum because some algorithm
families appear in multiple suites, such as `ghz`, `grover`, `hhl`, `qaoa`,
`qft`, `shor`, and `wstate`.
