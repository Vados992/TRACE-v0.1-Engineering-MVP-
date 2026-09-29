#!/usr/bin/env bash
# Run on a server you administer. Access the loopback API through SSH.
set -euo pipefail
cd "$(dirname "$0")/../.."
command -v docker >/dev/null || { echo 'Docker Engine + Compose v2 are required.' >&2; exit 1; }
if [ ! -f .env ]; then
  command -v python3 >/dev/null
  umask 077
  python3 - <<'PY'
import secrets
from pathlib import Path
p=secrets.token_hex(24)
g=secrets.token_hex(24)
Path('.env').write_text(f'''POSTGRES_PASSWORD={p}
DATABASE_URL=postgresql://trace:{p}@postgres:5432/trace
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD={g}
REDIS_URL=redis://redis:6379/0
OPENSEARCH_URL=http://opensearch:9200
EVIDENCE_BACKEND=filesystem
EVIDENCE_DIRECTORY=/var/lib/trace/evidence
TRACE_ENV=desktop
TRACE_PORT=8000
''')
PY
fi
docker compose -p trace-desktop -f compose.desktop.yml up -d --build
echo 'TRACE is starting on server loopback port 8000. Use the Windows SSH launcher; no public ports are opened.'
