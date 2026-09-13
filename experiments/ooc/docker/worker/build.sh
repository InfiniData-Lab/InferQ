#!/usr/bin/env bash
# Build the OOC worker image (DuckDB / SQLite / Aer runtime).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
docker build -t inferq-ooc-worker:latest "$HERE"
echo "Built inferq-ooc-worker:latest"
