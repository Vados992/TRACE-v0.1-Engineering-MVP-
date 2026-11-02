# TRACE-ACCOUNT v0.1 — engineering, provenance and validation

Copyright © 2026 Vadym Tsinderhoz. All rights reserved.

## Implemented

- Deterministic Pydantic/Decimal financial screening with source-linked, period-scoped inputs.
- Distinct measures for **approved budget**, **revised budget**, **awards**, **payments**, **operating cost**, **operating revenue**, **investment** and **EU funding**. Missing fields remain unknown.
- No corruption scores, crime classifiers, accusations, public disclosure or automatic sanctions.
- Read-only metadata mapping from EVIDENCE-X `GET /sources` rows; imported metadata is **not** upgraded to independently verified status.
- TRACE source-record ID foreign-key checks on submission. A permissioned read-only HTTPS metadata endpoint can call EVIDENCE-X GET /sources with a scoped x-evidence-key; no cross-database writes.
- Protected TRACE endpoints `/api/internal/accountability/preview`, `/submit`, `/assessments/{uuid}`, `/assessments/{uuid}/review`.
- PostgreSQL append-only assessments and reviews, idempotent submit by canonical SHA-256, independent reviewer, TRACE chained audit events.

## Install in the existing TRACE repo

Add the supplied files in their relative locations. In `services/api/app/main.py`, add:

```python
from .account_api import router as accountability_router
```

and after `app.include_router(public)` add:

```python
# Internal-only v0.1; public release requires separate legal and evidence review.
app.include_router(accountability_router, include_in_schema=False)
```

Install existing TRACE requirements and apply `python scripts/migrate.py` against a **backed-up staging database**, then run the existing TRACE stack. No existing migration is modified. Ensure `TRACE_ENV=production` has real credential hashes/OIDC.

### EVIDENCE-X connector configuration

Add ACCOUNT_EVIDENCE_X_BASE_URL (HTTPS origin only) and ACCOUNT_EVIDENCE_X_KEY (a scoped service key) to your secret manager or .env. The connector is disabled when these values are absent. GET /api/internal/accountability/evidence-x/sources is restricted to reviewer/admin. This endpoint checks transport and schema, but cannot verify the raw evidence bytes without a separate provenance capture.

### Protected API

Send `Authorization: Bearer <TRACE scoped credential>` and JSON shaped like `fixtures/accountability/kastoria_eca2014.json`. An `analyst` may preview/submit; a different `reviewer` may review; reviewer/admin may fetch the submitted assessment. Review judgments do not publish any person-level finding.

## Reproducible tests

```bash
PYTHONPATH=services/api python -m pytest -q services/api/tests/test_accountability.py
PYTHONPATH=services/api python scripts/accountability_case.py fixtures/accountability/kastoria_eca2014.json
# PostgreSQL TEST database with migrations and development credentials only:
TRACE_INTEGRATION=1 PYTHONPATH=services/api python -m pytest -q -m integration services/api/tests/test_accountability_integration.py
```

### Real published audit case, not live API test

European Court of Auditors, Special Report 21/2014, Box 5 (printed p.27):
https://www.eca.europa.eu/lists/ecadocuments/sr14_21/qjab14021enc.pdf

Historical figures (2005–2012): airport operating costs **€7,700,000**, revenues **€176,000**; investment in runway extension **€16,500,000**, including EU funds **€5,600,000**. Screening engine calculates an operating gap of **€7,524,000**. No budget baseline, actual paid investment total, documented decision chain or independently reviewed original evidence is available in this fixture, so the module **does not** compute budget variance or individual accountability.

**Evidence caveat:** This fixture was manually transcribed from the official published audit; the software did not live-fetch, cryptographically capture or independently verify the PDF. This is a replay of published numbers, not a certified case investigation.

## Remaining before deployment

1. Run PostgreSQL migrations, API integration smoke and full existing TRACE test suites in controlled staging.
2. Check mapped EVIDENCE-X source IDs with permissioned service-to-service API; currently metadata-only bridge.
3. Build authorized BASE/TED/OC4IDS connectors with source-specific schema mapping, licensing, rate limits and provenance capture. BASE Portugal API may require access token.
4. Implement temporal versioning for updated public records, project/contract identity resolution, independent legal review and GDPR rights workflow.
5. Refresh OpenAPI reference when endpoints graduate from private experimental status; expose no new public routes by default.

## Known operational constraint

GitHub Actions may be blocked by repository/account billing limits. Local `pytest` success is not evidence of a successful GitHub-hosted CI run.


## v0.2 add-on: Portugal BASE/IMPIC official data collector (branch-only)

- `account_portugal.py`: fixed official dados.gov.pt dataset metadata discovery, allowlisted HTTPS resource hostnames, redirects disabled, strict byte and record caps, JSON/CSV raw record capture. This is not a generic URL-fetch API.
- `account_portugal_store.py`: append-only source snapshots plus raw records and SHA-256, linked to existing TRACE `source_records`, with atomic hash-chain audit; no implied payment/contract settlement equivalence.
- `db/migrations/012a_accountability_portugal.sql`: staging PostgreSQL migration; **run after a backup** via existing `scripts/migrate.py`.
- `GET /api/internal/accountability/portugal/catalog`: discovers source catalog metadata (protected).
- `POST /api/internal/accountability/portugal/refresh`: captures catalog and first explicitly allowlisted bounded source JSON/CSV resource if available (analyst/admin). If resource is unavailable, the API truthfully reports catalog-only status.
- `GET /api/internal/accountability/portugal/snapshots/{id}/verify`: recomputes original stored byte digest (reviewer/admin).
- `scripts/accountability_portugal_sync.py`: CLI for scheduled isolated ingests, requiring explicit `DATABASE_URL` (does not use demo database).
- `.github/workflows/account-pt-ingest.yml`: scheduled/manual job **disabled by default**, requires `TRACE_ACCOUNT_PT_SYNC_ENABLED=true`, `TRACE_ACCOUNT_DATABASE_URL` secret and operational runner/network/billing. Never auto-runs on an unconfigured account.
- `tests/integration/test_account_portugal_postgres.py`: migrated real PostgreSQL API workflow with mock HTTP government and EVIDENCE-X services; proves TRACE source refs + app submission and independent review **only when run with PostgreSQL**. External services in this test are mocked.

Primary public source: https://www.base.gov.pt/Base4/pt/documentacao/formas-de-obter-dados-sobre-os-contratos-publicos/ ; Portuguese dataset metadata: https://dados.gov.pt/pt/datasets/contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/ . IMPIC's **direct** higher-frequency API requires authorized token, and is not claimed to be integrated. Publisher-controlled files can be too large or corrupt; the collector will refuse and report unsafe/unavailable content, not fabricate success. Claims of live feed coverage require actual runner logs and database evidence.

**Operational limitations:** live database migrations and production EVIDENCE-X service-to-service auth were not executed in the local isolated environment. Data source metadata was externally reviewed; there is no claim that official bytes were retrieved locally. No public disclosure or automatic legal verdict.
