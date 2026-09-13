#!/usr/bin/env bash
# Re-run OOC trials that failed because the host disk filled (the pg_ooc_*
# docker volume leak), writing results to a fresh CSV. Keeps legitimate
# results (success, oom_internal, oom_kill, and engine-real errors like
# Aer's coupling_map) intact by copying them into the new CSV first.
#
# Run from the repository root.
#
# Usage:
#   experiments/ooc/rerun_disk_full_failures.sh [SRC_CSV] [DST_CSV]
#
# Defaults to the q=27..32 statevector sweep.

set -euo pipefail

SRC_CSV="${1:-experiments/ooc/results/res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.csv}"
DST_CSV="${2:-experiments/ooc/results/res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.rerun_disk_full.csv}"
MANIFEST="${MANIFEST:-experiments/ooc/manifests/circuits_qft_27_32.jsonl}"

if [[ ! -f "$SRC_CSV" ]]; then
  echo "source CSV not found: $SRC_CSV" >&2
  exit 1
fi
if [[ -e "$DST_CSV" ]]; then
  echo "destination already exists: $DST_CSV (refusing to overwrite)" >&2
  exit 1
fi

echo "[rerun] src=$SRC_CSV"
echo "[rerun] dst=$DST_CSV"
echo "[rerun] manifest=$MANIFEST"

# 1) Refuse to run if a previous runner is still alive.
if pgrep -af "experiments.ooc.run_experiment|experiments.ooc.worker" >/dev/null; then
  echo "[rerun] another runner/worker is still running — kill it first:" >&2
  pgrep -af "experiments.ooc.run_experiment|experiments.ooc.worker" >&2
  exit 1
fi

# 2) Cleanup leaked docker state from the previous run.
echo "[rerun] cleaning up pg_ooc_* containers + dangling volumes..."
if docker ps -aq --filter "name=pg_ooc_" | grep -q .; then
  docker ps -aq --filter "name=pg_ooc_" | xargs docker rm -fv
fi
docker volume prune -f >/dev/null

# 3) Build the new CSV: copy every row from SRC except those whose status='error'
#    AND error_msg matches a disk-full pattern. The runner's --resume then
#    re-queues exactly the (circuit, cap, engine, method, mode) triples we drop.
python3 - "$SRC_CSV" "$DST_CSV" <<'PY'
import csv, re, sys
src, dst = sys.argv[1], sys.argv[2]
DISK_FULL = re.compile(
    r"No space left on device|database or disk is full|disk I/O error",
    re.IGNORECASE,
)
kept = dropped = 0
with open(src, newline="") as fi, open(dst, "w", newline="") as fo:
    r = csv.DictReader(fi)
    w = csv.DictWriter(fo, fieldnames=r.fieldnames)
    w.writeheader()
    for row in r:
        if row.get("status") == "error" and DISK_FULL.search(row.get("error_msg") or ""):
            dropped += 1
            continue
        w.writerow(row)
        kept += 1
print(f"[rerun] kept {kept} rows, dropped {dropped} disk-full rows -> {dst}")
PY

# 4) Re-run. --resume will re-queue only the triples missing from $DST_CSV
#    (i.e. the disk-full ones we just dropped). All other rows are skipped.
exec uv run python -m experiments.ooc.run_experiment \
  --manifest "$MANIFEST" \
  --results-csv "$DST_CSV" \
  --caps-gb 16,8,4 \
  --engines postgres,duckdb,sqlite,aer \
  --aer-methods statevector \
  --mode split \
  --resume
