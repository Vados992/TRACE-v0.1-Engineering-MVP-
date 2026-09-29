#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# An isolated, disposable project. Never run the legacy destructive smoke against user volumes.
export COMPOSE_PROJECT_NAME="trace-desktop-ci-${GITHUB_RUN_ID:-$$}"
export COMPOSE_FILE=compose.desktop.yml
mkdir -p logs
cleanup() { docker compose down -v --remove-orphans; }
trap cleanup EXIT
python3 - <<'PY'
from pathlib import Path
import secrets
p=secrets.token_hex(24)
g=secrets.token_hex(24)
Path('.env').write_text(f'POSTGRES_PASSWORD={p}\nDATABASE_URL=postgresql://trace:{p}@postgres:5432/trace\nNEO4J_URI=bolt://neo4j:7687\nNEO4J_USER=neo4j\nNEO4J_PASSWORD={g}\nEVIDENCE_BACKEND=filesystem\nEVIDENCE_DIRECTORY=/var/lib/trace/evidence\nTRACE_ENV=desktop\n')
PY
wait_ready() {
  for attempt in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:8000/api/v1/system/status | python3 -c 'import json,sys; d=json.load(sys.stdin); assert all(x["status"]=="ok" for x in d["components"].values())' 2>/dev/null; then return; fi
    sleep 3
  done
  docker compose logs --tail 80
  return 1
}
docker compose up -d --build
wait_ready
docker compose exec -T api python /app/scripts/desktop_check.py --live --strict-sources | tee logs/desktop-before-restart.json
docker compose down
# Recreate all containers while preserving named volumes.
docker compose up -d
wait_ready
docker compose exec -T api python /app/scripts/desktop_check.py | tee logs/desktop-after-restart.json
python3 - <<'PY'
import json
from pathlib import Path
before=json.loads(Path('logs/desktop-before-restart.json').read_text())
after=json.loads(Path('logs/desktop-after-restart.json').read_text())
assert before['evidence_set_sha256']==after['evidence_set_sha256']
assert before['checks']['evidence_objects_verified']==after['checks']['evidence_objects_verified']>0
assert after['checks']['real_relationship_path_and_provenance']=='ok'
print('PASS: live connectors, canonical path, evidence hashes, persistence after full container recreation')
PY
