#!/usr/bin/env bash
# Build the OOC-tuned Postgres image. Run once before starting experiments.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
docker build -t inferq-ooc-postgres:16 "$HERE"
echo "Built inferq-ooc-postgres:16"
