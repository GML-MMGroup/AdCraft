#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../apps/web"
export BACKEND_ORIGIN="${BACKEND_ORIGIN:-http://127.0.0.1:8000}"
npm run dev -- --port 5189
