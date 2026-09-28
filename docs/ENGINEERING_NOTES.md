# TRACE v0.1 Engineering Notes

## Scope of this package

This package is the first executable engineering layer of TRACE. It intentionally prioritizes provenance, reversible entity resolution, and public-source connectivity over UI polish.

## Important invariants

1. PostgreSQL is canonical. Neo4j is a rebuildable projection.
2. Raw source records are immutable and content-hashed.
3. Exact identifiers outrank name similarity.
4. Natural persons are never auto-merged from names alone.
5. A financial award, commitment, invoice, and payment are different states.
6. GLEIF accounting-parent relationships are not automatically labelled beneficial ownership.
7. Temporal proximity is not causation.
8. Public availability does not remove GDPR-purpose, necessity, and minimization obligations.

## Connector behavior

### TED
Uses the official v3 Search API endpoint `/v3/notices/search`. Search of published notices is documented as openly accessible without authentication. Payloads use expert-query syntax and explicit field selection.

### GLEIF
Uses the public GLEIF JSON:API under `/api/v1/lei-records`. The connector exposes name search and individual LEI retrieval. Parent/child retrieval support is prepared in the connector but should be validated against live API relationship names before production use.

### EUR-Lex / Cellar
The MVP connector retrieves a known CELEX document using Cellar content negotiation at `/resource/celex/{celex}`. This does not provide general EUR-Lex search. General expert search through the EUR-Lex SOAP webservice requires registration and should be added behind credentials as a separate connector mode.

## Production gaps before public launch

- Authentication/authorization enforcement and staff MFA.
- Rate limiting at gateway/WAF level.
- Object-store persistence for raw document bodies.
- Full connector ingestion into canonical tables.
- Data-subject workflow and DPIA implementation.
- Jurisdiction-specific entity-resolution calibration datasets.
- Human review console for ambiguous merges.
- Graph path ranking by evidence quality and temporal consistency.
- OpenSearch indexing.
- CI/CD, signed containers, SBOM, dependency and secret scanning.
- Backup/restore drills and disaster-recovery plan.
- Legal review of source licences/terms and personal-data exposure.
