# TRACE v0.2 — Execution Layer

**Transparent Relationship & Allocation Chain Explorer**

TRACE is a provenance-first system for reconstructing documented relationships between public policy, organizations, public/professional actors, corporate ownership, procurement, lobbying and financial flows.

v0.2 turns the v0.1 architecture into an executable evidence pipeline:

```text
PUBLIC SOURCE
    ↓
CONNECTOR
    ↓
IMMUTABLE RAW ARTIFACT (MinIO + SHA-256)
    ↓
SOURCE RECORD
    ↓
PARSER / CANONICALIZER
    ↓
ENTITY + IDENTIFIER + CLAIM + EVIDENCE
    ↓
TEMPORAL RELATIONSHIP GRAPH
    ↓
PATH FINDER
    ↓
INVESTIGATION RESULT
```

## Implemented in v0.2

- Checksum-protected PostgreSQL migrations.
- Immutable raw-artifact metadata and MinIO object storage.
- Ingestion job ledger.
- GLEIF LEI ingestion into canonical organizations and verified LEI identifiers.
- EUR-Lex/Cellar CELEX ingestion into canonical legal acts, documents and document versions.
- TED v3 raw search-response ingestion with schema-gated normalization policy.
- Claim/evidence linkage to source records and document versions.
- Time-filtered, evidence-filtered relationship Path Finder.
- `WHY IS THIS CONNECTION SHOWN?` evidence endpoint.
- Persisted investigations with explicit `unknowns` and warnings.
- Minimal citizen investigation web console at `/ui/`.
- GitHub Actions test/compile workflow.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Endpoints:

```text
API docs:  http://localhost:8000/docs
UI:        http://localhost:8000/ui/
Health:    http://localhost:8000/health
MinIO UI:  http://localhost:9001
Neo4j UI:  http://localhost:7474
```

## Example: ingest a GLEIF record

```bash
curl -X POST http://localhost:8000/api/v1/ingest/gleif/529900T8BM49AURSDO55
```

TRACE stores the raw JSON in MinIO, records its SHA-256, inserts a source record, creates/reuses the canonical organization, stores the LEI as a verified identifier, and creates an evidence-backed identity claim.

## Example: ingest an EUR-Lex act

```bash
curl -X POST 'http://localhost:8000/api/v1/ingest/eurlex/32016R0679?language=eng'
```

## Example: raw TED evidence ingestion

```bash
curl -X POST http://localhost:8000/api/v1/ingest/ted/search \
  -H 'content-type: application/json' \
  -d '{
    "query": "publication-number = 000000-2026",
    "fields": ["publication-number", "notice-title", "buyer-name"],
    "limit": 10
  }'
```

TED normalization is intentionally conservative in v0.2. Search responses are persisted immutably first; notice-to-canonical extraction should be implemented per validated TED notice schema/version instead of guessing a universal mapping.

## Example: find a documented path

```bash
curl -X POST http://localhost:8000/api/v1/graph/path \
  -H 'content-type: application/json' \
  -d '{
    "source_entity_id": "00000000-0000-0000-0000-000000000001",
    "target_entity_id": "00000000-0000-0000-0000-000000000002",
    "max_depth": 6,
    "limit": 10,
    "verified_only": true
  }'
```

## Investigation semantics

TRACE never converts proximity into causality. A meeting, contract, ownership change or funding event can be shown on the same timeline without implying that one caused another.

Every investigation can return:

- verified paths;
- evidence status;
- time boundaries;
- unknowns;
- explicit warnings.

Absence of a path means only that no qualifying path exists in the currently ingested canonical graph.

## GLEIF ownership semantics

GLEIF Level 2 data describes direct and ultimate **accounting consolidating parents**. TRACE must not relabel those relationships as beneficial ownership unless a separate source establishes beneficial ownership.

## Current limits

v0.2 is an execution-layer MVP, not a production public service. Before public deployment it still needs authentication/RBAC, gateway rate limiting, staff MFA, DPIA/data-subject workflows, source-specific retention rules, full TED canonical parsers, broader corporate-registry/lobbying/funding connectors, human entity-resolution review UI, production observability, backup/restore, SBOM/container signing, and penetration testing.

## Tests

```bash
python -m compileall -q services/api scripts
pytest -q
```
