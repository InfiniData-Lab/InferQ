#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERQ_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROJECT_ROOT="$(cd "${INFERQ_ROOT}/.." && pwd)"

OUT_DIR="${OUT_DIR:-${PROJECT_ROOT}/res/finetuned/sqlite_small_memory}"
OUT_CSV="${OUT_CSV:-${OUT_DIR}/results_sqlite_small_memory.csv}"
HASHES_FILE="${HASHES_FILE:-${SCRIPT_DIR}/profiles/small_median_hashes.txt}"
QPY_ROOTS="${QPY_ROOTS:-${INFERQ_ROOT}/analysis/finetuned_rdbms_116/qpy:${INFERQ_ROOT}/analysis/finetuned_rdbms_162/qpy:${INFERQ_ROOT}/circuits:${INFERQ_ROOT}/data/extremes}"
QPY_LIST="${QPY_LIST:-${SCRIPT_DIR}/profiles/small_median_qpy_paths.txt}"
PROFILE_JSON="${PROFILE_JSON:-${SCRIPT_DIR}/profiles/sqlite_small_memory.json}"
TMP_ROOT="${TMP_ROOT:-${OUT_DIR}/tmp}"
N_RUNS="${N_RUNS:-1}"
WARMUP="${WARMUP:-1}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-300}"
FETCH_CHUNK_SIZE="${FETCH_CHUNK_SIZE:-8192}"

mkdir -p "${OUT_DIR}"

IFS=":" read -r -a qpy_roots <<< "${QPY_ROOTS}"
python3 - "${HASHES_FILE}" "${QPY_LIST}" "${qpy_roots[@]}" <<'PY'
from pathlib import Path
import sys

hashes_file = Path(sys.argv[1])
qpy_list = Path(sys.argv[2])
roots = [Path(p) for p in sys.argv[3:] if p]
wanted = {
    line.split(",", 1)[0].strip()
    for line in hashes_file.read_text().splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
found = {}
for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*.qpy"):
        if path.stem in wanted and path.stem not in found:
            found[path.stem] = path.resolve()
qpy_list.parent.mkdir(parents=True, exist_ok=True)
qpy_list.write_text("".join(f"{found[h]}\n" for h in sorted(found)))
missing = len(wanted) - len(found)
print(
    f"Discovered {len(found)} matching QPY files"
    f" across {sum(1 for r in roots if r.exists())} existing roots"
    f" ({missing} missing).",
    file=sys.stderr,
)
if not found:
    print("Searched roots:", file=sys.stderr)
    for root in roots:
        print(f"  {root}", file=sys.stderr)
    raise SystemExit(1)
PY

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
echo "Using qpy roots:    ${QPY_ROOTS}" >&2
echo "Using qpy list:     ${QPY_LIST}" >&2
echo "Using profile:      ${PROFILE_JSON}" >&2

RUN_CMD=(python3 "${INFERQ_ROOT}/scripts/finetuned_rdbms/run_finetuned_rdbms.py" \
  --qpy-list "${QPY_LIST}" \
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
