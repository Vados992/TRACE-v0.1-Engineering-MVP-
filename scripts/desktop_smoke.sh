#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Current minimal desktop/server runtime. Real sources are opt-in TRACE_LIVE_CHECK=1.
exec bash scripts/docker_smoke.sh "$@"
