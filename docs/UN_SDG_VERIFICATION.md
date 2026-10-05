# UN SDG Claim Verification

## Purpose

This layer answers a narrow question reproducibly: **does a numeric assertion equal the result obtained from a specified snapshot of official UN SDG observations under explicit filters and arithmetic?**

It does not infer corruption, causality, policy quality, or legal liability.

## Evidence pipeline

\`\`\`
UNSD SDG API
  -> bounded HTTPS pages
  -> completeness invariant (page count + totalElements)
  -> immutable Evidence Vault artifact + SHA-256
  -> source_record
  -> normalized sdg_observations
  -> deterministic recalculation
  -> claim_verification_run
  -> append-only audit event
\`\`\`

The connector is pinned to the official \`https://unstats.un.org/SDGAPI\` host. A query is rejected if the upstream result requires more pages than the operator-authorized bound; TRACE never treats a partial result as a complete verification dataset.

## Supported calculations

- \`count_observations\`
- \`count_distinct_geographies\`
- \`sum_values\`
- \`mean_values\`
- \`percent_change\`

\`percent_change\` requires explicit baseline and comparison periods and an explicit \`sum\` or \`mean\` aggregation. It uses:

\`\`\`
(current - baseline) / abs(baseline) * 100
\`\`\`

A zero baseline is rejected as undefined.

All arithmetic uses Python \`Decimal\`. Values such as \`<0.1\`, textual estimates, blanks or other non-decimal source representations remain preserved in evidence but are not silently converted to numbers.

## Example: import a real snapshot

Authenticated internal request:

\`\`\`json
{
  "query": {
    "series_code": "EG_ELC_ACCS",
    "area_codes": [620],
    "time_period_start": 2020,
    "time_period_end": 2025,
    "page_size": 100,
    "max_pages": 5
  },
  "legal_basis": "Operator-authorized verification of official public statistics"
}
\`\`\`

Send this to \`POST /api/internal/sdg/import\`. The response returns the immutable \`source_record_id\`, Evidence Vault artifact ID, observation count and SHA-256.

## Example: reproduce from stored evidence

\`\`\`json
{
  "source_record_id": "<uuid>",
  "calculation": {
    "operation": "count_distinct_geographies",
    "dimension_filters": {},
    "attribute_filters": {},
    "aggregation": "sum"
  }
}
\`\`\`

Send to \`POST /api/internal/sdg/recalculate\`. No network access is needed; the operation reads the stored snapshot.

## Example: end-to-end verification

\`\`\`json
{
  "query": {
    "series_code": "EG_ELC_ACCS",
    "area_codes": [620],
    "time_period_start": 2020,
    "time_period_end": 2025
  },
  "calculation": {
    "operation": "count_observations",
    "dimension_filters": {},
    "attribute_filters": {},
    "aggregation": "sum"
  },
  "asserted_value": "6",
  "tolerance": "0",
  "assertion_text": "The selected official dataset contains six matching observations.",
  "legal_basis": "Operator-authorized verification of official public statistics"
}
\`\`\`

\`POST /api/internal/sdg/verify\` performs the live retrieval, evidence capture, recalculation and comparison in one audited workflow.

## Verification semantics

- **VERIFIED**: \`abs(calculated - asserted) <= tolerance\`.
- **REFUTED**: a complete captured dataset produces a value outside tolerance.
- Retrieval/schema/completeness failures are errors, not REFUTED results.
- Missing numeric observations cannot be invented or coerced to make an assertion evaluable.
- The raw upstream snapshot and source response hashes are retained so a reviewer can trace the calculation.

## Identity

Development can use scoped API keys. Institutional deployments should configure \`AUTH_MODE=oidc\`.

OIDC accepts only RS256 JWTs and validates signature, issuer, audience, expiry, issued-at/not-before time and subject. External IdP groups are mapped through \`OIDC_ROLE_MAP_JSON\`; an unmapped group called \`admin\` does not grant TRACE administrator access.

## Observability

Every request receives/retains a TRACE request ID, security headers are added to responses, structured access telemetry is emitted, and an admin can scrape \`/api/internal/metrics\` in Prometheus exposition format.

The metrics implementation intentionally avoids entity IDs and query strings in labels to prevent high-cardinality telemetry and accidental disclosure.

## Backup and restore

Use the production compose file together with \`compose.ops.yml\`.

\`\`\`sh
mkdir -p .artifacts/backups
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops run --rm backup
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops up -d restore-postgres
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops run --rm restore-drill
\`\`\`

The backup contains a PostgreSQL custom-format dump, Evidence Vault tar archive, hashes and metadata. The restore drill verifies archive hashes, restores into a disposable PostgreSQL 17 instance, confirms all migrations, and checks audit-chain linkage.

Evidence files are written before their database references are committed, while the evidence store is content-addressed and append-only. Therefore a database snapshot followed by the evidence archive cannot create a committed DB reference to an evidence file that did not already exist; concurrent later evidence may only add harmless extra files to the archive.

## Production boundary

This repository provides deployable controls, but institutional production still requires the operator's actual IdP, TLS termination, secrets/KMS policy, monitoring destination, retention policy, authorized data-access agreements, capacity targets, external penetration testing and an independent privacy/security review.
