#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Dedicated project, never normal application volumes. Does not overwrite existing configuration.
export COMPOSE_PROJECT_NAME="trace-pia-smoke-${GITHUB_RUN_ID:-$$}"
export TRACE_PORT="${TRACE_SMOKE_PORT:-18000}"
export POSTGRES_PORT="${TRACE_SMOKE_DB_PORT:-15432}"
export COMPOSE_FILE=docker-compose.yml
if [ ! -f .env ]; then cp .env.example .env; fi
trap 'docker compose down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
docker compose exec -T api python scripts/smoke.py
if [ "${TRACE_OFFLINE_TEST:-0}" = 1 ]; then
  docker compose exec -T api python scripts/demo.py
fi
if [ "${TRACE_LIVE_CHECK:-0}" = 1 ]; then
  docker compose exec -T api python scripts/live_validation.py --sources gleif ted eurlex ocds openownership
fi
docker compose down
docker compose up -d --wait --wait-timeout 180
docker compose exec -T api python scripts/smoke.py
echo 'Passed isolated stack startup, authentication, portals and container recreation.'
