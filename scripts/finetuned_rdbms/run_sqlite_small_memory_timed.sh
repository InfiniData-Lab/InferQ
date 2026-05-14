#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
INFERQ_ROOT="${REPO_ROOT}/InferQ"

OUT_DIR="${OUT_DIR:-${REPO_ROOT}/res/finetuned/sqlite_small_memory}"
OUT_CSV="${OUT_CSV:-${OUT_DIR}/results_sqlite_small_memory.csv}"
HASHES_FILE="${HASHES_FILE:-${REPO_ROOT}/res/finetuned_circuit_group_small_median_hashes.txt}"
QPY_DIR="${QPY_DIR:-${INFERQ_ROOT}/analysis/finetuned_rdbms_116/qpy}"
PROFILE_JSON="${PROFILE_JSON:-${SCRIPT_DIR}/profiles/sqlite_small_memory.json}"
TMP_ROOT="${TMP_ROOT:-${OUT_DIR}/tmp}"
N_RUNS="${N_RUNS:-1}"
WARMUP="${WARMUP:-1}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-300}"
FETCH_CHUNK_SIZE="${FETCH_CHUNK_SIZE:-8192}"

mkdir -p "${OUT_DIR}"

TIME_CMD=(/usr/bin/time -p)
if [[ "${NO_TIME:-0}" == "1" ]]; then
  TIME_CMD=()
elif [[ -n "${TIME_CMD_OVERRIDE:-}" ]]; then
  read -r -a TIME_CMD <<< "${TIME_CMD_OVERRIDE}"
elif [[ ! -x /usr/bin/time ]]; then
  TIME_CMD=()
fi

echo "Writing results to: ${OUT_CSV}" >&2
echo "Using hashes:       ${HASHES_FILE}" >&2
echo "Using qpy dir:      ${QPY_DIR}" >&2
echo "Using profile:      ${PROFILE_JSON}" >&2

RUN_CMD=(python3 "${INFERQ_ROOT}/scripts/finetuned_rdbms/run_finetuned_rdbms.py" \
  --circuits-dir "${QPY_DIR}" \
  --hashes-file "${HASHES_FILE}" \
  --out-csv "${OUT_CSV}" \
  --engines sqlite \
  --profile balanced \
  --tuning-json "${PROFILE_JSON}" \
  --tuning-label sqlite_small_memory \
  --n-runs "${N_RUNS}" \
  --warmup "${WARMUP}" \
  --timeout-seconds "${TIMEOUT_SECONDS}" \
  --query-timeout-seconds "${QUERY_TIMEOUT_SECONDS}" \
  --fetch-chunk-size "${FETCH_CHUNK_SIZE}" \
  --tmp-root "${TMP_ROOT}" \
  --resume \
  "$@")

if [[ ${#TIME_CMD[@]} -gt 0 ]]; then
  "${TIME_CMD[@]}" "${RUN_CMD[@]}"
else
  "${RUN_CMD[@]}"
fi
