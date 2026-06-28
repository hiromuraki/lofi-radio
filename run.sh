#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "🚀 Starting Lo-Fi Radio on http://0.0.0.0:8000"
exec uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
