#!/usr/bin/env bash
# Substitute CAP_GB-derived memory sizes into postgresql.conf, then hand off to
# the stock postgres entrypoint. Assumes CAP_GB is an integer GB value set by the
# orchestrator.
set -euo pipefail

: "${CAP_GB:?CAP_GB env var required (integer GB)}"

CAP_MB=$((CAP_GB * 1024))
SHARED_BUFFERS_MB=$((CAP_MB / 4))
WORK_MEM_MB=64
MAINT_WORK_MEM_MB=256
EFFECTIVE_CACHE_MB=$((CAP_MB / 2))
TEMP_FILE_LIMIT_KB=$((CAP_MB * 512))   # cap/2 expressed in KB

export SHARED_BUFFERS_MB WORK_MEM_MB MAINT_WORK_MEM_MB EFFECTIVE_CACHE_MB TEMP_FILE_LIMIT_KB

envsubst '${SHARED_BUFFERS_MB} ${WORK_MEM_MB} ${MAINT_WORK_MEM_MB} ${EFFECTIVE_CACHE_MB} ${TEMP_FILE_LIMIT_KB}' \
    < /etc/pg/postgresql.conf.template > /etc/pg/postgresql.conf

exec docker-entrypoint.sh "$@"
