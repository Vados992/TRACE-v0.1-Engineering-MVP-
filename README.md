# TRACE-PIA 0.4

Provenance-first public-integrity reference implementation, extending the existing TRACE core. It stores source evidence, temporal relationships, procurement observations, ownership assertions, wealth reconciliation and reviewed cases. **It is not production-certified and is not an official integration with public authorities.** A path or risk signal is not proof of wrongdoing.

Русская инструкция: [START_HERE_RU.md](START_HERE_RU.md). Source code and operational documentation use English.

## Start locally with Docker

Requires Git, Docker Engine/Desktop with Compose v2, and Python 3.12+ for operator scripts. Ports 8000 and 5432 must be available.

```sh
git clone https://github.com/Vados992/TRACE-v0.1-Engineering-MVP-.git
cd TRACE-v0.1-Engineering-MVP-
cp .env.example .env
docker compose up --build -d --wait
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
python scripts/smoke.py
```

In PowerShell, use `Copy-Item .env.example .env` instead of `cp` if preferred. Open http://127.0.0.1:8000/ui/ and enter `trace-dev-analyst-only`. Reviewer, publisher and administrator use `trace-dev-reviewer-only`, `trace-dev-publisher-only`, `trace-dev-admin-only`. These public development keys are rejected in production.

Public portal: http://127.0.0.1:8000/public/. Local interactive API docs: http://127.0.0.1:8000/docs. OpenAPI: `/openapi.json` and [openapi/trace-pia.json](openapi/trace-pia.json). No remote JavaScript/CDN is needed.

The required stack is **PostgreSQL 17 + API + persistent Evidence Vault filesystem volume**. Migrations run automatically before API startup. Redis, Neo4j, external object storage and OpenSearch are not required. PostgreSQL is also the authoritative graph store and Path Finder query engine. See [DATABASES.md](DATABASES.md).

## Load real public data

The default startup creates schema and source definitions only. **It does not inject synthetic people or relationships.** Live connectors perform actual HTTPS requests; unavailable sources fail visibly, without fabricated fallback data.

```sh
python scripts/live_validation.py --sources gleif ted eurlex ocds
# Public ownership publisher snapshot; subject to publisher availability:
python scripts/live_validation.py --sources openownership
```

The first command imports bounded real GLEIF accounting-parent relationships, TED notices, EUR-Lex metadata and Find a Tender OCDS releases. Endpoint URLs are operator configuration, not arbitrary request input. The Open Ownership connector retrieves its published UK BODS 0.4 snapshot; it is **not a current Companies House API**. Verify publisher dates, license, legal basis and identity before relying on any result. See [CONNECTORS.md](CONNECTORS.md) for exact scope, pagination bounds and optional authenticated datasets.

OCDS/BODS imports remain `UNVERIFIED` until an independent reviewer checks evidence. Inherited GLEIF/TED/EUR-Lex extraction records `VERIFIED_PRIMARY` as source-backed assertions; that label does not mean human investigation or an official corruption finding. Native TED awards distinguish `AWARDED` from actual payments. Missing amounts and ownership ranges are not invented.

Use the analyst console to import sources, search loaded entities, select two endpoints for Path Finder, inspect provenance, upload a wealth declaration request, scan conflicts and create a case. Only independently reviewed, explicitly redacted case text reaches the public API. See [API.md](API.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Run without Docker

Install PostgreSQL 17 with `pgcrypto` and `pg_trgm`, create a development database/user, and set `DATABASE_URL` in `.env`. Set `EVIDENCE_BACKEND=filesystem` and a writable `EVIDENCE_DIRECTORY`.

```sh
python -m pip install -r requirements-dev.lock
python scripts/migrate.py
python scripts/serve.py
```

`scripts/serve.py` supports `TRACE_HOST` and `TRACE_PORT`; it fixes Windows asyncio compatibility for psycopg. PostgreSQL must already be running. Do not use the public dev database account on a server.

## Server / production-like setup

```sh
python scripts/bootstrap_production.py
docker compose --env-file .env.production -f compose.production.yml up --build -d --wait
python scripts/production_smoke.py
```

This creates random scoped keys, separates database owner/runtime roles, starts non-root containers and exposes a read-only public gateway on loopback port 8080. `.env.production` and `.production-keys.json` are private, ignored files. Assign roles to separate people and install a TLS reverse proxy for public access. Keep port 8000 behind an internal network/VPN. Follow [DEPLOYMENT.md](DEPLOYMENT.md), [SECURITY.md](SECURITY.md), [THREAT_MODEL.md](THREAT_MODEL.md), [LEGAL_PRIVACY.md](LEGAL_PRIVACY.md) before handling personal data.

## Verify

```sh
python -m pytest -q -m "not integration"
# Disposable migrated PostgreSQL database only:
TRACE_INTEGRATION=1 python -m pytest -q tests/integration
python scripts/export_openapi.py
```

PowerShell: `$env:TRACE_INTEGRATION='1'` before the integration command. Integration tests cover PostgreSQL, evidence storage, atomic imports, provenance, time-aware paths, reconciliation, independent review, public boundaries and audit integrity. Fixtures in `fixtures/demo` are explicitly synthetic **test inputs only**, isolated from live identity identifiers. `python scripts/demo.py` is an opt-in offline acceptance scenario; it never proves an external connection. It should run only on a disposable test installation.

GitHub Actions runs unit/integration tests, development and production-like containers, gateway smoke tests and browser controls. Live checks are deliberately separate from deterministic CI because public publishers can be unavailable. Current execution evidence and limitations are in [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## Repository map

| Path | Purpose |
|---|---|
| `services/api/app` | FastAPI, connectors, graph, engines, cases, authorization and audit |
| `services/api/static` | Working analyst/admin MVP and separate public portal |
| `db/migrations` | Ordered, locked, checksum-verified PostgreSQL migrations |
| `openapi/trace-pia.json` | Generated current API contract; older YAMLs are historical core contracts |
| `scripts` | Migrations, launch, credentials, smoke checks and real imports |
| `fixtures/demo` | Synthetic fixtures exclusively for tests / opt-in offline verification |
| `tests/integration`, `tests/ui` | Database workflows and browser tests |
| `deploy`, `compose.production.yml` | Public boundary and server configuration |
| `.github/workflows` | Automated validation |

Further documentation: [ARCHITECTURE.md](ARCHITECTURE.md), [OPERATIONS.md](OPERATIONS.md), [DATA_DICTIONARY.md](DATA_DICTIONARY.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Historical architecture material remains in `docs/`, the original migrations and core modules. The referenced 66-page Spanish specification was not available in the supplied project or referenced conversation attachments; this implementation preserves the stated architectural principles and existing core, without claiming a page-by-page conformance audit.

## Two independent time axes

Migration 009 adds immutable bitemporal versions and actual PostgreSQL commit receipts. Use `known_at` independently of fact validity dates; the analyst console exposes both. Earlier snapshots exclude later ingestion, reviews, corrections and evidence. Exact history starts at migration 009 and earlier requests fail explicitly. PostgreSQL requires `track_commit_timestamp=on` (configured in Compose). See [TEMPORAL.md](TEMPORAL.md) for querying and upgrading.
