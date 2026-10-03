# TRACE-PIA execution evidence

Checked on 2026-10-03. This report describes executed checks, not production certification or an official government integration.

## Native local stack

Windows workstation: Python 3.12, PostgreSQL 17.11, persistent filesystem Evidence Vault, FastAPI and nginx 1.28.3. All eight migrations applied successfully to separate development, disposable integration-test and production-like databases. Re-running migrations verifies checksums without reapplying them. Docker/WSL was not available locally; container execution is a separate GitHub Actions check.

* **44 tests passed**: 39 unit tests and five PostgreSQL integration workflows. These cover atomic/replayed imports, identifier separation, evidence integrity and tamper rejection, temporal graph queries, Decimal wealth calculations, conflict review, independent case publication/appeal and the append-only audit chain.
* Ruff and Python compilation passed; generated OpenAPI includes **39 paths**.
* Development health/readiness, portals, OpenAPI and authenticated/private API smoke passed.
* Native production-like API uses random scoped keys and a non-superuser database runtime role. Public nginx permits only public portal assets and public read APIs. Private routes/docs/OpenAPI and public writes are denied. Production smoke passed.
* Browser controls passed on desktop/mobile layouts with isolated API fixtures. A second browser check used the actual running API/PostgreSQL, without mocked routes: login, case listing, public portal, API docs, layout and forgetting credentials on reload passed.
* Twelve repeated concurrent filesystem-write checks passed after fixing Windows extended-path comparison during simultaneous evidence creation.

One non-failing upstream Starlette warning concerns its deprecated httpx-based TestClient integration. The runtime API and HTTP client requests passed.

## Actual HTTPS ingestion

These are bounded requests to publishers, not synthetic fixture results. Counts describe the requested subset and do not establish complete registry coverage. Source assertions and machine extraction do not establish wrongdoing.

| Source | HTTP | Entities returned | Relationships returned | Award flows | Path Finder paths |
|---|---:|---:|---:|---:|---:|
| GLEIF accounting parents | 200 | 2 | 2 | 0 | 2 |
| TED published award notices | 200 | 9 | 9 | 3 | 2 |
| Find a Tender OCDS | 200 | 8 | 6 | 0 | 2 |
| Open Ownership UK BODS 0.4 publisher archive | 200 | 53 | 21 | 0 | 1 |
| EUR-Lex / Cellar, subject-scoped parser | 200 | 256 | 255 | 0 | 1 |

Exact response evidence is stored privately with source records and hashes; local aggregate receipts are ignored under `.artifacts/`. They are not committed with personal information. Mapped BODS/OCDS assertions remain UNVERIFIED and are queried internally with `verified_only=false`. Non-active awards and closed/unknown ownership assertions were skipped with explicit warnings. TED awarded amounts are not payment receipts.

Open Ownership is a partial prefix of its publisher snapshot released on **2025-03-11**, not a current Companies House connection. The connector reads a bounded HTTPS byte range from the actual ZIP and complete NDJSON statements; it does not download or claim to import the entire registry.

Cellar follows the publisher's same-host redirect using HTTPS and a separate 64 MiB response bound. The corrected parser selects only the requested RDF subject and explicit CDM predicates, retaining direction and excluding proposed amendments and annotation vocabulary. Migration 008 preserves and retires legacy overbroad parser assertions; new extraction has a distinct parser identity. The live 62.7 MB response succeeded after this correction.

The production-like native database also received the actual BODS snapshot subset (53 entities/21 relationships), with successful evidence Path Finder checks and no synthetic entities.

## Container and CI evidence

The repository includes GitHub Actions for Linux unit/integration workflows, required development containers, production-like containers/public gateway, actual-server browser checks and Windows installer/UI compatibility. Container execution results will be recorded after the GitHub run; native checks above must not be represented as Docker execution.

## Remaining installation dependencies

* Configured authenticated BODS/PPDS exports require the operator's actual URL, mapping, credentials and lawful access. These were not falsely reported as tested institutional integrations.
* No real wealth declaration, tax/bank data or private-property records were supplied. Numeric reconciliation passed with clearly marked fixtures in the disposable test database; a full real-person wealth reconciliation cannot be demonstrated without authorized component evidence. Missing amounts are never synthesized.
* Institutional production use still requires TLS, identity-provider/MFA integration, institution-specific scope/retention/access decisions, tested backup restoration, monitoring, independent audit checkpoints and security/privacy review. API keys and database/runtime boundaries are implemented, not a substitute for those controls.
* The referenced 66-page Spanish v0.2 PDF was not available in supplied sources or retrieved conversation attachments. Existing TRACE core and the stated architecture were preserved; a page-by-page conformance claim would be unsupported.

Reproduce live checks with `python scripts/live_validation.py --sources gleif ted ocds openownership eurlex`. Reproduce local smoke with `python scripts/smoke.py`; production boundary with `python scripts/production_smoke.py`. See README and DEPLOYMENT for configuration and startup commands. Run integration fixtures only in a disposable migrated database with its own evidence directory.
