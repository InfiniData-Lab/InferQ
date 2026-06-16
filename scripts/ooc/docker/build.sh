#!/usr/bin/env bash
# Build all OOC Docker images: tuned Postgres + worker runtime.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

echo ">>> Building inferq-ooc-postgres:12.22"
docker build -t inferq-ooc-postgres:12.22 "$HERE"

echo ">>> Building inferq-ooc-worker:latest"
docker build -t inferq-ooc-worker:latest "$HERE/worker"

echo "Built inferq-ooc-postgres:12.22 and inferq-ooc-worker:latest"
