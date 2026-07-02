#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DATA_DIR="${DATA_DIR:-$(pwd)/data}"

docker build -t lofi-radio:dev . && docker run --rm -p 8000:8000 -v ./data:/data lofi-radio:dev
