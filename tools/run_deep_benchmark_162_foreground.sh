#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR="${OUT_DIR:-out/deep_benchmark_162}"
CIRCUIT_TIMEOUT_SECONDS="${CIRCUIT_TIMEOUT_SECONDS:-300}"
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-30}"
AER_METHODS="${AER_METHODS:-statevector,stabilizer,density_matrix,matrix_product_state,extended_stabilizer,unitary,automatic}"

mkdir -p "$OUT_DIR"

caffeinate -dimsu uv run python -m experiments.analysis.deep_benchmark_dataset \
  --resume \
  --out-dir "$OUT_DIR" \
  --circuit-timeout-seconds "$CIRCUIT_TIMEOUT_SECONDS" \
  --heartbeat-seconds "$HEARTBEAT_SECONDS" \
  --aer-methods "$AER_METHODS"
