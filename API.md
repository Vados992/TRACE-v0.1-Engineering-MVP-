# API and usage

Current contract: [openapi/trace-pia.json](openapi/trace-pia.json), also `/openapi.json`. `/docs` is a local, CSP-compatible API explorer. Existing YAML contracts are historical core snapshots, not the complete current contract.

| Boundary | Auth | Purpose |
|---|---|---|
| `/api/v1/*` | Scoped Bearer key | Preserved core source ingestion, entity resolution, relationships, Path Finder and investigations |
| `/api/internal/*` | Scoped Bearer key + operation role | Imports, evidence/claim review, wealth, conflict context, cases and audit |
| `/api/public/*` | Read-only anonymous | Status and explicit redacted releases only |
| `/health`, `/ready` | Anonymous; internal gateway only | Liveness/readiness |

Internal keys are entered in the browser login or supplied as `Authorization: Bearer ...`. No session cookie or implicit admin privilege is used. Development keys are in README; production uses private generated keys and distinct people.

## Analyst workflow

1. Fetch a real source in the console or via the live connector endpoints documented in CONNECTORS. Inspect import warnings and evidence dates/license. Do not interpret unavailable data as evidence of absence.
2. Search `/api/v1/entities/search?q=...`; synthetic entities are excluded by default (`include_demo=true` is explicit testing only). Select existing UUIDs, never guess identities from names.
3. Call `/api/v1/graph/path` with `source_entity_id`, `target_entity_id`, optional aware ISO timestamps `from_time/to_time`, `max_depth` (up to 6), `limit` and `verified_only`. New mapped imports need review or an explicitly unverified internal exploration. Returned paths contain original edge direction, common validity and uncertainty. Undirected connectivity does not imply causality.
4. Inspect `/api/v1/relationships/{id}/why` and `/api/internal/claims/{claim_id}`. Download `/api/internal/evidence/{artifact_id}` with an authorized role; compare `X-Evidence-SHA256`. Evidence downloads are private, attachment-only and audited.
5. A distinct reviewer can POST `/api/internal/claims/{id}/review` with a supported status and explanatory note. Synthetic evidence cannot be promoted to verified factual evidence.
6. Use `/api/internal/conflicts/scan` to create direct-role/supplier ownership context signals, then reviewer `/conflicts/{id}/review` to dismiss/escalate with reasons. The bounded rule includes time checks/uncertainty; it does not make a legal conflict determination. Synthetic subjects are excluded unless explicitly requested on a test system.
7. POST `/api/internal/cases` with subject, title, reason and actual `claim_ids`. Review/publish/appeal/withdraw via `/cases/{id}/actions`. Reviewer supplies redacted public title/summary; publisher uses exactly that text, cannot replace it silently, and must be a third identity. An appeal withdraws current public text pending fresh review. Production rejects publication of synthetic evidence.

## Wealth reconciliation

Supply an authorized `wealth-bridge/1` request to `/api/internal/wealth/reconcile` with person UUID, stable dataset ID, period, currency, license/legal basis and per-component evidence locators. Engine:

`expected closing net worth = opening + income + gifts + realized gains + unrealized gains - expenses - taxes + other adjustment`.

`residual = observed closing net worth - expected closing net worth`.

Use net wealth (assets minus liabilities), consistent valuation dates/currency, and actual evidence for every number. No FX/rate inference or automatic OCR is performed. Missing fields must be null, not invented zero. Missing any required component returns INCOMPLETE and no residual. Complete unexplained residual beyond tolerance returns REVIEW_REQUIRED. This creates an internal review item, not a suspicion score or legal accusation. `/wealth/{entity_id}` retains versioned inputs/results and source references.

The system does not obtain bank/tax/private asset data itself. Public ownership/procurement data alone is insufficient to reconstruct personal wealth: do not manufacture a complete declaration to satisfy a demo. Synthetic arithmetic cases remain deterministic tests only.

## Common responses

401 missing/invalid key; 403 role/origin/host denial; 404 missing record; 409 independence, publication-state or evidence-integrity conflict; 413 body too large; 422 invalid import/time range/query budget; 502 external source unavailable; 503 database/audit/storage or configured-source prerequisite failure. Exact request/response schemas and endpoint lists are generated from executable models.

New atomic domain mutations write audit events in their transaction. Legacy source writes preserve a prior committed intent and completion record, with completion failure signaled by response header. Claims/public release text are not automatically derived into accusations. Public endpoints have no access to internal case/evidence tables through the application projection.
