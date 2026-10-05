# TRACE-PIA 0.6

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

## Verify published claims against official UN SDG data

TRACE can now fetch complete bounded snapshots from the official United Nations Statistics Division SDG API, persist the exact snapshot in the Evidence Vault, normalize observations, and independently recalculate numeric assertions. The engine supports observation counts, distinct geography counts, sums, means and explicit baseline/comparison percent change. Qualified values such as `<0.1` are preserved as source text and are not silently coerced into numbers.

Internal endpoints (intentionally excluded from the public OpenAPI surface) are:

- `POST /api/internal/sdg/import` — capture a complete immutable UNSD snapshot.
- `POST /api/internal/sdg/recalculate` — reproduce a calculation from a stored snapshot without network access.
- `POST /api/internal/sdg/verify` — fetch official data, persist evidence, recalculate and compare an asserted value within an explicit tolerance.

Every import, recalculation and verification is audit-chained. A VERIFIED result means that the stated arithmetic matches the captured official dataset and filters; it is not a legal or policy conclusion. See [docs/UN_SDG_VERIFICATION.md](docs/UN_SDG_VERIFICATION.md).

## Cross-source statistical verification

TRACE now exposes one provider-agnostic statistical verification protocol across:

- United Nations SDG (`UN_SDG`)
- Eurostat (`EUROSTAT`)
- World Bank Indicators API v2 (`WORLD_BANK`)
- OECD Data Explorer SDMX (`OECD`)
- IMF DataMapper v2 (`IMF`)
- Spain INEbase JSON API (`INE_ES`)
- UK Office for National Statistics v1 API (`ONS_UK`)

The shared internal routes are:

- `POST /api/internal/statistics/import` — capture an immutable official-provider snapshot.
- `POST /api/internal/statistics/recalculate` — reproduce deterministic arithmetic from stored evidence.
- `POST /api/internal/statistics/verify` — verify one numeric assertion against one provider.
- `POST /api/internal/statistics/cross-verify` — compare the same operator-declared semantic contract across two or more independent providers.

Cross-source comparison is deliberately conservative. TRACE does **not** infer that similarly named indicators are equivalent. A request must supply an explicit semantic contract covering concept, unit, frequency, geography, period and transformation, plus a mapping note for every source. If a requested source fails, the cross-source result is `INSUFFICIENT`; if successful sources differ beyond the declared spread tolerance, the result is `SOURCE_CONFLICT`.

All new providers write to the canonical `statistical_observations` layer while the existing UN/SDG routes remain backwards-compatible. Raw upstream responses, normalized observations, query parameters and SHA-256 evidence remain in the Evidence Vault. See [docs/MULTISOURCE_STATISTICAL_VERIFICATION.md](docs/MULTISOURCE_STATISTICAL_VERIFICATION.md).

## Load real public data

The default startup creates schema and source definitions only. **It does not inject synthetic people or relationships.** Live connectors perform actual HTTPS requests; unavailable sources fail visibly, without fabricated fallback data.

```sh
python scripts/live_validation.py --sources unsdg eurostat worldbank imf ine_es ons_uk
python scripts/live_validation.py --sources oecd
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

## Institutional identity and operations

Local development keeps scoped API keys. Institutional deployments can set `AUTH_MODE=oidc` and configure an HTTPS issuer, audience, JWKS endpoint, subject/roles claims and an explicit external-group-to-TRACE-role map. TRACE accepts only signed RS256 JWTs, validates issuer/audience/time claims and never treats an external role name as a TRACE privilege unless it is explicitly mapped.

The runtime emits bounded structured request telemetry and exposes Prometheus text at `/api/internal/metrics` to the admin role. Database pool size and statement timeout are configurable.

Production backup/restore uses `compose.ops.yml`: a custom-format PostgreSQL dump plus a hash-verified Evidence Vault archive. The CI production job performs an actual restore into a disposable PostgreSQL 17 instance and checks migrations and the restored audit-chain linkage.

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


## License

**Proprietary — All Rights Reserved.** Copyright © 2026 Vadym Tsinderhoz.

No permission is granted to copy, modify, distribute, deploy, sublicense,
commercialize, or otherwise reuse this repository or its contents without
prior express written permission from Vadym Tsinderhoz, except for rights that
cannot lawfully be excluded and the limited rights necessarily arising from
GitHub's own Terms of Service for use of GitHub functionality.

Use for AI/ML training, fine-tuning, dataset creation, embeddings, retrieval
corpora, model evaluation, or code-generation systems is not authorized by the
repository license except where independently permitted by mandatory law or by
rights separately granted under GitHub's Terms of Service.

See [LICENSE](LICENSE) for the complete terms.

> Historical note: earlier distributions of this repository were published
> with Apache License 2.0. Rights already validly granted for those earlier
> distributions are not retroactively revoked by this licensing change.
