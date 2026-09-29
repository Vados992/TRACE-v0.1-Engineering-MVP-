#!/usr/bin/env bash
set -euo pipefail

# Never remove the normal application project volumes.
export COMPOSE_PROJECT_NAME="trace-legacy-smoke-${GITHUB_RUN_ID:-$$}"
trap 'docker compose down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

API_URL="${TRACE_API_URL:-http://127.0.0.1:8000}"
TEST_LEI="${TRACE_TEST_LEI:-529900T8BM49AURSDO55}"
TARGET_ENTITY_ID="00000000-0000-0000-0000-00000000c001"
RELATIONSHIP_ID="00000000-0000-0000-0000-00000000c201"

wait_for() {
  local name="$1"
  local attempts="$2"
  shift 2
  for i in $(seq 1 "$attempts"); do
    if "$@" >/dev/null 2>&1; then
      echo "[ok] $name"
      return 0
    fi
    sleep 2
  done
  echo "[error] timed out waiting for $name" >&2
  return 1
}

echo "==> Starting TRACE infrastructure"
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --build postgres minio neo4j opensearch redis

wait_for "PostgreSQL" 60 docker compose exec -T postgres pg_isready -U trace -d trace
wait_for "Redis" 60 docker compose exec -T redis redis-cli ping
wait_for "MinIO" 60 curl -fsS http://127.0.0.1:9000/_localstack/health
wait_for "Neo4j HTTP" 60 curl -fsS http://127.0.0.1:7474
wait_for "OpenSearch" 90 curl -fsS http://127.0.0.1:9200

echo "==> Applying migrations"
docker compose run --rm migrate

MIGRATION_COUNT="$(
  docker compose exec -T postgres     psql -U trace -d trace -Atc "SELECT count(*) FROM schema_migrations;"
)"
echo "Applied migrations: $MIGRATION_COUNT"
if [ "$MIGRATION_COUNT" -lt 5 ]; then
  echo "[error] expected at least 5 migrations" >&2
  exit 1
fi

echo "==> Starting TRACE API"
docker compose up -d api
wait_for "TRACE /health" 90 curl -fsS "$API_URL/health"

curl -fsS "$API_URL/health" | python -c '
import json,sys
d=json.load(sys.stdin)
assert d["status"]=="ok", d
assert d["version"]=="0.3.0", d
print("health:", d)
'

echo "==> Running real GLEIF ingestion: $TEST_LEI"
INGEST_FILE="$(mktemp)"
for attempt in 1 2 3 4; do
  if curl -fsS --max-time 90 -X POST       "$API_URL/api/v1/ingest/gleif/$TEST_LEI" >"$INGEST_FILE"; then
    break
  fi
  if [ "$attempt" -eq 4 ]; then
    echo "[error] live GLEIF ingestion failed after retries" >&2
    exit 1
  fi
  sleep $((attempt * 3))
done

SOURCE_ENTITY_ID="$(
  python - "$INGEST_FILE" "$TEST_LEI" <<'PY'
import json,sys
path, expected_lei = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data=json.load(fh)
assert data["status"]=="SUCCEEDED", data
assert data["source"]=="GLEIF", data
assert data["external_id"]==expected_lei, data
assert data.get("sha256") and len(data["sha256"])==64, data
assert data.get("source_record_id"), data
assert data.get("raw_artifact_id"), data
assert len(data.get("entity_ids", []))==1, data
print(data["entity_ids"][0])
PY
)"
echo "Canonical entity from live ingestion: $SOURCE_ENTITY_ID"

echo "==> Verifying evidence persistence and canonical LEI"
RAW_COUNT="$(
  docker compose exec -T postgres psql -U trace -d trace -Atc     "SELECT count(*) FROM raw_artifacts ra JOIN sources s ON s.id=ra.source_id WHERE s.code='GLEIF' AND ra.external_id='$TEST_LEI';"
)"
ID_COUNT="$(
  docker compose exec -T postgres psql -U trace -d trace -Atc     "SELECT count(*) FROM entity_identifiers WHERE entity_id='$SOURCE_ENTITY_ID'::uuid AND scheme='LEI' AND identifier_value='$TEST_LEI' AND verified=TRUE;"
)"
if [ "$RAW_COUNT" -lt 1 ] || [ "$ID_COUNT" -lt 1 ]; then
  echo "[error] GLEIF ingestion did not persist expected evidence/entity state" >&2
  exit 1
fi

echo "==> Seeding deterministic verified relationship from the real ingested entity"
docker compose exec -T postgres   psql -U trace -d trace     -v source_entity_id="$SOURCE_ENTITY_ID"     -v test_lei="$TEST_LEI"   < tests/integration/smoke_seed.sql

echo "==> Exercising authoritative Path Finder"
PATH_FILE="$(mktemp)"
curl -fsS -X POST "$API_URL/api/v1/graph/path"   -H 'content-type: application/json'   -d "{
    \"source_entity_id\": \"$SOURCE_ENTITY_ID\",
    \"target_entity_id\": \"$TARGET_ENTITY_ID\",
    \"max_depth\": 3,
    \"limit\": 10,
    \"verified_only\": true
  }" >"$PATH_FILE"

python - "$PATH_FILE" "$RELATIONSHIP_ID" "$SOURCE_ENTITY_ID" "$TARGET_ENTITY_ID" <<'PY'
import json,sys
path, rel_id, source_id, target_id = sys.argv[1:]
with open(path, encoding="utf-8") as fh:
    data=json.load(fh)
paths=data.get("paths", [])
assert paths, data
match=None
for p in paths:
    if p.get("nodes")==[source_id, target_id]:
        match=p
        break
assert match is not None, data
assert match["hops"]==1, match
assert match["edges"][0]["id"]==rel_id, match
assert match["edges"][0]["verification_status"]=="VERIFIED_PRIMARY", match
print("pathfinder:", match)
PY

echo "==> Exercising relationship provenance endpoint"
WHY_FILE="$(mktemp)"
curl -fsS "$API_URL/api/v1/relationships/$RELATIONSHIP_ID/why" >"$WHY_FILE"
python - "$WHY_FILE" "$RELATIONSHIP_ID" <<'PY'
import json,sys
path, rel_id = sys.argv[1:]
with open(path, encoding="utf-8") as fh:
    data=json.load(fh)
assert str(data["relationship"]["id"])==rel_id, data
assert data.get("canonical_claim_evidence"), data
assert data.get("source_observations"), data
print("why: evidence and source observations present")
PY

echo "==> Final service checks"
docker compose exec -T redis redis-cli ping | grep -q PONG
curl -fsS http://127.0.0.1:9000/_localstack/health >/dev/null
curl -fsS http://127.0.0.1:7474 >/dev/null
curl -fsS http://127.0.0.1:9200 >/dev/null

echo "TRACE Docker integration smoke test PASSED"
