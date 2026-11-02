# TRACE-ACCOUNT — Official Portuguese BASE/IMPIC intake (experimental)

Author: Vadym Tsinderhoz · 2026 · All rights reserved.

## Scope

Collector reads public contracts data published by **IMPIC** through the
`dados.gov.pt` dataset catalog, not the private IMPIC API. The catalog has
JSON/XLSX resources and IMPIC describes weekly dataset updates. API access
from IMPIC requires a separate authorization and token. The JSON adapter is
**schema-gated**: unexpected formats or untrusted hosts fail closed.

The importer only stores the **declared contractual price**, never assumes
this amount has been paid, wasted or embezzled. It creates **no politician
score, criminal allegation, or automatic finding**. EVIDENCE-X remains a
separate authenticated, read-only metadata bridge, subject to independent
human verification.

Official catalog: https://dados.gov.pt/api/1/datasets/contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/
IMPIC source instructions: https://www.base.gov.pt/Base4/pt/documentacao/formas-de-obter-dados-sobre-os-contratos-publicos/

## Deployment (disposable PostgreSQL FIRST)

```bash
export TRACE_ENV=dev
export DATABASE_URL='postgresql://<isolated_test_user>:<password>@127.0.0.1:5432/trace_account_test'
# Use disposable PG database with track_commit_timestamp=on, and no production data.
python scripts/migrate.py
PYTHONPATH=services/api pytest -q -m integration tests/integration/test_impic_persistence.py
# Only after PostgreSQL integration passes, optionally fetch 2026 data:
PYTHONPATH=services/api python scripts/sync_impic.py --year 2026 --artifacts .artifacts/impic
```

The importer requires network connectivity from the deployment host.
`psycopg` and a PostgreSQL service are mandatory for persistence. The
source URL must resolve to a vetted HTTPS host; no redirects are followed.
ZIPs are unpacked with size/expansion constraints and only one JSON entry
is accepted. Raw files are kept in a content-addressed operator-controlled
local artifact directory. Restrict access to that directory, back it up
and consider encrypted object storage before production deployment.

## Scheduling (only after the first supervised live run)

The official publication is generally weekly. To run a weekly 2026 sync
on a host with working network, database and audit infrastructure, configure
an operations-managed cron entry (or its equivalent), for example:

```cron
30 5 * * 1 cd /opt/trace && /opt/trace/.venv/bin/python scripts/sync_impic.py --year 2026 >> /var/log/trace/impic-sync.log 2>&1
```

The example assumes `PYTHONPATH=services/api` is set by the service account
and that its environment provides the database connection. Do **not** use
this schedule before verifying storage, quotas, disk space, alerting and
readiness. It is **not** activated automatically in GitHub Actions, given
existing GitHub Actions billing/runner restrictions.

## Provenance, limitations and incident behavior

- A catalog entry demonstrates publication, not that each contract is genuine.
- Source files are hashed with SHA-256 before any transformation. Each imported
  contract has a separate canonical JSON SHA-256; raw snapshots are archived.
- A repeated identical source file is idempotent by SHA-256. Revised source
  files create a new immutable snapshot with a new hash.
- Unknown fields are never guessed; invalid rows are counted. The importer
  must not be presented as complete when rows fail mapping.
- Imported contracts are **candidates for analysis**, not reconciled payment
  records or trusted evidence of wrongdoing.
- The importer has been locally tested with mocked HTTP and synthetic JSON.
  Production schema and live provider connectivity require validation on
  actual downloaded IMPIC files; no such validation is claimed here.
- The DB test requires a real disposable PostgreSQL server and cannot be
  considered passed merely because the Python unit tests passed.

## Post-import verification

```sql
SELECT id,year,retrieved_at,raw_sha256,rows_total,imported_count,invalid_count
FROM account_impic_snapshots ORDER BY retrieved_at DESC LIMIT 5;
SELECT contract_id,title,contract_price_eur,snapshot_id
FROM account_impic_latest ORDER BY contract_id LIMIT 10;
```

Do not publish individual accountability conclusions without source
cross-checking, independent review, and a right of response.
