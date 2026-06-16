#!/usr/bin/env bash
# Re-run only the SQLite trials with the page cache scaled to the cgroup cap
# (OOC_SQLITE_CACHE_FRAC), so cap_gb actually affects SQLite's behavior.
# Postgres/DuckDB/Aer rows are copied through unchanged to the new CSV.
#
# Run on boxpc from ~/Documents/InferQ.
#
# Usage:
#   scripts/ooc/rerun_sqlite_cap_scaled.sh [SRC_CSV] [DST_CSV]

set -euo pipefail

SRC_CSV="${1:-scripts/ooc/results/res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.csv}"
DST_CSV="${2:-scripts/ooc/results/res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.sqlite_cap_scaled.csv}"
MANIFEST="${MANIFEST:-data/ooc/circuits_qft_27_32.jsonl}"
FRAC="${OOC_SQLITE_CACHE_FRAC:-0.5}"

if [[ ! -f "$SRC_CSV" ]]; then
  echo "source CSV not found: $SRC_CSV" >&2
  exit 1
fi
if [[ -e "$DST_CSV" ]]; then
  echo "destination already exists: $DST_CSV (refusing to overwrite)" >&2
  exit 1
fi

echo "[rerun-sqlite] src=$SRC_CSV"
echo "[rerun-sqlite] dst=$DST_CSV"
echo "[rerun-sqlite] manifest=$MANIFEST"
echo "[rerun-sqlite] OOC_SQLITE_CACHE_FRAC=$FRAC  (cap_gb * 1024 * frac MB cache)"

if pgrep -af "scripts.ooc.run_experiment|scripts.ooc.worker" >/dev/null; then
  echo "[rerun-sqlite] another runner/worker is still running — kill it first:" >&2
  pgrep -af "scripts.ooc.run_experiment|scripts.ooc.worker" >&2
  exit 1
fi

# Defensive cleanup — should be a no-op since we're not running postgres trials.
docker ps -aq --filter "name=pg_ooc_" | xargs -r docker rm -fv
docker volume prune -f >/dev/null

# Build the new CSV: drop every SQLite row (so they get re-queued); keep all
# postgres / duckdb / aer rows verbatim so the runner skips them via --resume.
python3 - "$SRC_CSV" "$DST_CSV" <<'PY'
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
kept = dropped = 0
with open(src, newline="") as fi, open(dst, "w", newline="") as fo:
    r = csv.DictReader(fi)
    w = csv.DictWriter(fo, fieldnames=r.fieldnames)
    w.writeheader()
    for row in r:
        if row.get("engine") == "sqlite":
            dropped += 1
            continue
        w.writerow(row)
        kept += 1
print(f"[rerun-sqlite] kept {kept} non-sqlite rows, dropped {dropped} sqlite rows -> {dst}")
PY

# Re-run sqlite only. OOC_SQLITE_CACHE_FRAC is read by config.py and applied
# per-trial inside build_worker_args in run_experiment.py.
export OOC_SQLITE_CACHE_FRAC="$FRAC"

exec uv run python -m scripts.ooc.run_experiment \
  --manifest "$MANIFEST" \
  --results-csv "$DST_CSV" \
  --caps-gb 16,8,4 \
  --engines sqlite \
  --mode split \
  --resume
