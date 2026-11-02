# TRACE-ACCOUNT v0.1 — Engineering and Validation
Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.

## Implemented
- Deterministic financial screening with Decimal, source references, period-scoped data and reproducible SHA-256 inputs.
- Budget, contract award, payment, operational cost, operating revenue and capital investment are distinct measures. Missing data are never treated as zero.
- Read-only EVIDENCE-X source metadata adapter. Metadata imported from another service remains unverified.
- TRACE source-record foreign-key checks and protected internal review API.
- PostgreSQL append-only assessments, independent reviewer, idempotent submissions, TRACE chained audit events.
- No corruption scores, automated blame assignment, public release or sanctions.

## Activation in existing TRACE stack
The branch mounts the router in services/api/app/main.py under /api/internal/accountability. Run the existing migration runner against a BACKED-UP STAGING PostgreSQL database:

    python scripts/migrate.py

Start TRACE with its existing settings. Never use demo keys in production. Endpoints are internal and omitted from public OpenAPI pending an access and governance review.

Protected endpoints:
- POST /api/internal/accountability/preview (analyst/reviewer/admin)
- POST /api/internal/accountability/submit (analyst/admin)
- GET /api/internal/accountability/assessments/{uuid} (reviewer/admin)
- POST /api/internal/accountability/assessments/{uuid}/review (independent reviewer)

## Reproducible tests
    PYTHONPATH=services/api python -m pytest -q services/api/tests/test_accountability.py
    PYTHONPATH=services/api python scripts/accountability_case.py fixtures/accountability/kastoria_eca2014.json

Database-dependent suite (disposable migrated TRACE DB with scoped test credentials):

    TRACE_INTEGRATION=1 PYTHONPATH=services/api python -m pytest -q -m integration services/api/tests/test_accountability_integration.py

## Published audit case (historical, manually transcribed)
European Court of Auditors, Special Report 21/2014, Box 5 (printed page 27):
https://www.eca.europa.eu/lists/ecadocuments/sr14_21/qjab14021enc.pdf

2005–2012 figures: airport operating costs EUR 7,700,000 and revenues EUR 176,000; runway extension investment EUR 16,500,000 including EU funds EUR 5,600,000. Screening computes an operating gap of EUR 7,524,000. This is NOT a finding of illegal spending, personal liability, or public fiscal damage. Budget variance and decisions are NOT calculable from this evidence alone.

This example is not a live API ingestion or independently authenticated capture. Each evidence reference is explicitly marked unverified in the fixture.

## Outstanding work
1. Staging PostgreSQL migrations and authenticated API integration test; full TRACE CI.
2. Permissioned service-to-service verification for EVIDENCE-X metadata; currently an offline schema bridge.
3. Licensed BASE/TED/OC4IDS official-data connectors with field-level provenance, validation, source terms and rate limits.
4. Temporal revisions, linkage resolution, independent legal audit and GDPR access/correction governance.
5. Formal security review before any production release.

Note: GitHub Actions execution may be blocked by the GitHub account billing/spending limit.

## EVIDENCE-X HTTPS integration
Set ACCOUNT_EVIDENCE_X_BASE_URL (HTTPS origin, no path, userinfo or port) and ACCOUNT_EVIDENCE_X_KEY (scoped service credential stored as a secret). Both are disabled by default. An independent reviewer or admin can call GET /api/internal/accountability/evidence-x/sources?limit=25. The read-only client uses the existing EVIDENCE-X /sources endpoint and x-evidence-key authorization header; no redirects and no proxy environment trust. HTTP errors or unexpected response formats fail closed. Metadata remain unverified without checking underlying payload bytes. In v0.1 the endpoint lists the latest 100 source records at most, not complete archive coverage.

## Second official historical test
European Court of Auditors, Special Report 21/2014, paragraph 47: Cordoba airport 2013 passenger forecast 179,000 versus 6,955 actual. The reproducible offline sample fixtures/accountability/cordoba_eca2014.json gives 3.89% target realization and a review signal. Figures are manually transcribed from published material, not fetched through a live API.
