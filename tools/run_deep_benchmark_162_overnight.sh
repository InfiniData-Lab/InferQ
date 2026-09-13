#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR="${OUT_DIR:-out/deep_benchmark_162}"
CIRCUIT_TIMEOUT_SECONDS="${CIRCUIT_TIMEOUT_SECONDS:-1800}"
AER_METHODS="${AER_METHODS:-statevector,stabilizer,density_matrix,matrix_product_state,extended_stabilizer,unitary,automatic}"

mkdir -p "$OUT_DIR"

RUN_LOG="$OUT_DIR/overnight.log"
PID_FILE="$OUT_DIR/overnight.pid"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Benchmark already running with PID $old_pid"
    echo "Log: $RUN_LOG"
    exit 0
  fi
fi

nohup uv run python -m experiments.analysis.deep_benchmark_dataset \
  --resume \
  --out-dir "$OUT_DIR" \
  --circuit-timeout-seconds "$CIRCUIT_TIMEOUT_SECONDS" \
  --aer-methods "$AER_METHODS" \
  > "$RUN_LOG" 2>&1 &

pid="$!"
echo "$pid" > "$PID_FILE"

echo "Started deep benchmark PID $pid"
echo "Run log: $RUN_LOG"
echo "Summary CSV: $OUT_DIR/sqlite_vs_qiskit_summary.csv"
echo "Results JSONL: $OUT_DIR/sqlite_vs_qiskit_results.jsonl"
echo "Missing hashes: $OUT_DIR/missing_hashes.txt"
