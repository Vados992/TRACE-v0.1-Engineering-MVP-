# TRACE v0.3 — Relationship Intelligence Layer

**Transparent Relationship & Allocation Chain Explorer**

TRACE is a provenance-first platform for reconstructing documented relationships between public policy, organizations, public/professional actors, procurement, corporate structures, lobbying disclosures and financial flows.

v0.3 extends the v0.2 execution layer with automatic, source-backed relationship builders and cross-source reconciliation.

```text
PUBLIC SOURCE
    ↓
CONNECTOR / STANDARDIZED OFFICIAL IMPORT
    ↓
IMMUTABLE RAW EVIDENCE (MinIO + SHA-256)
    ↓
SOURCE RECORD
    ↓
SOURCE-SPECIFIC PARSER
    ↓
CROSS-SOURCE ENTITY RECONCILIATION
    ↓
RELATIONSHIP OBSERVATION
    ↓
CANONICAL TEMPORAL RELATIONSHIP
    ↓
OWNERSHIP / PROCUREMENT / MONEY / LOBBYING / POLICY GRAPH
    ↓
PATH FINDER + WHY ENDPOINT
```

## Relationship intelligence implemented in v0.3

### Ownership / corporate structure

`POST /api/v1/relationship-intelligence/ownership/gleif/{lei}`

The builder retrieves the LEI record plus available GLEIF direct and ultimate parent records and creates:

- `DIRECT_ACCOUNTING_PARENT_OF`
- `ULTIMATE_ACCOUNTING_PARENT_OF`
- corresponding `ownership_interests` records with explicit GLEIF accounting-consolidation semantics

TRACE deliberately does **not** relabel these records as beneficial ownership.

### Procurement + awarded money

`POST /api/v1/relationship-intelligence/procurement/ted/search`

TRACE requests the TED fields required for buyer, winner, notice, procedure, award date and notice-result value. It automatically creates:

- canonical procurement notice/contract entities;
- buyer → notice edges;
- notice → winner edges;
- buyer → winner `AWARDED_CONTRACT_TO` edges only when the pair is unambiguous;
- `money_flows` only when one buyer, one winner, amount and currency are all available;
- procurement award records.

For multi-party awards, TRACE does not distribute a notice-level total across winners unless the source provides an unambiguous allocation.

### Cross-source reconciliation

v0.3 introduces:

- `source_entity_mappings`;
- deterministic strong-identifier reconciliation;
- GLEIF national registration identifiers;
- TED organization identifier mappings;
- exact cross-source registration-number matching when jurisdiction aligns;
- human-review queue for name-only candidates;
- `relationship_observations` linked to canonical relationships;
- numeric conflict detection across relationship observations;
- `reconciliation_conflicts`.

Name similarity alone does not silently merge organizations across sources.

### Lobbying / transparency observations

`POST /api/v1/relationship-intelligence/lobbying/import`

The public EU Transparency Register is an authoritative disclosure source, but v0.3 does not depend on an undocumented scraping endpoint. It accepts standardized records derived from official register/meeting exports or another approved official-data ingestion process and automatically creates:

- canonical registrants keyed by EU Transparency Register ID;
- public institutions;
- `MET_WITH` edges for explicit dated meetings;
- `LOBBIED_ON` only when the source record explicitly supplies a policy CELEX identifier;
- budget disclosures as disclosure metadata, not as money transfers.

Free-text meeting subjects alone never create a policy-causation edge.

### Policy lifecycle / legal relations

`POST /api/v1/relationship-intelligence/policy/eurlex/{celex}`

TRACE retrieves Cellar RDF metadata for the CELEX work, persists it immutably, extracts allow-listed CELEX-to-CELEX legal relations, and creates canonical edges such as:

- `AMENDS`
- `AMENDED_BY`
- `CITES`
- `CITED_BY`
- `BASED_ON`
- `BASIS_FOR`
- `SUCCESSOR_OF`
- `HAS_SUCCESSOR`
- `CORRECTS`
- `CORRECTED_BY`

Unknown RDF predicates are ignored rather than guessed.

## Reconciliation visibility

`GET /api/v1/reconciliation/summary`

Returns counts for:

- open entity-resolution candidates;
- open relationship conflicts;
- source-to-canonical mappings;
- relationship observations.

## Explainability

Every automatically built canonical relationship can be inspected with:

```text
GET /api/v1/relationships/{relationship_id}/why
```

The response includes:

- canonical relationship;
- canonical claim evidence;
- every source observation attached to the relationship;
- immutable payload URI/hash metadata;
- reconciliation conflicts.

## Path Finder

New v0.3 relationships are written directly to the canonical PostgreSQL relationship layer, so the existing Path Finder can use them immediately without waiting for a Neo4j rebuild:

```text
POST /api/v1/graph/path
POST /api/v1/investigations
```

Neo4j remains a rebuildable projection/acceleration layer, not the system of record.

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
S3 dev gateway: http://localhost:9000
Neo4j UI:  http://localhost:7474
```

## Examples

### Build a GLEIF ownership chain

```bash
curl -X POST http://localhost:8000/api/v1/relationship-intelligence/ownership/gleif/529900T8BM49AURSDO55
```

### Build TED procurement relationships

```bash
curl -X POST http://localhost:8000/api/v1/relationship-intelligence/procurement/ted/search \
  -H 'content-type: application/json' \
  -d '{
    "query": "publication-date >= 20260101",
    "limit": 25
  }'
```

### Import an official lobbying/meeting observation

```bash
curl -X POST http://localhost:8000/api/v1/relationship-intelligence/lobbying/import \
  -H 'content-type: application/json' \
  -d '{
    "records": [{
      "transparency_id": "000000000000-00",
      "registrant_name": "Example Association",
      "registrant_country": "BE",
      "institution_name": "European Commission",
      "meeting_date": "2026-09-01",
      "subject": "Discussion of an identified legislative file",
      "policy_celex": "32026R0001",
      "source_external_id": "official-export-row-123"
    }]
  }'
```

### Build Cellar legal/policy relationships

```bash
curl -X POST http://localhost:8000/api/v1/relationship-intelligence/policy/eurlex/32016R0679
```

## Tests and CI

```bash
python -m compileall -q services/api scripts
pytest -q
```

The repository uses explicit setuptools package discovery so GitHub Actions can install the project with:

```bash
pip install -e '.[dev]'
```

This fixes the v0.2 CI packaging failure caused by flat-layout auto-discovery.

## Safety / evidence invariants

TRACE must not output a corruption probability, political integrity score or inferred criminal intent.

A graph edge means only that a defined relationship is supported by the cited source under the stated semantics. Temporal proximity does not establish causation. Missing data does not establish wrongdoing. Name similarity alone does not establish identity.

## Current limits

v0.3 is still an engineering MVP. A production public service still requires authentication/RBAC, WAF/rate limiting, staff MFA, DPIA/data-subject workflows, production observability, backup/restore, signed containers/SBOM, source-license review, robust official Transparency Register export automation, broader national registries, and integration tests against live services and container infrastructure.


## Docker end-to-end smoke test

TRACE includes a separate GitHub Actions workflow at `.github/workflows/docker-smoke.yml`.

It validates a clean deployment rather than only Python imports:

1. starts PostgreSQL, MinIO, Neo4j, OpenSearch and Redis;
2. applies all SQL migrations;
3. starts the FastAPI service and verifies `/health`;
4. performs a live GLEIF ingestion for a real LEI;
5. verifies immutable raw evidence and the canonical LEI in PostgreSQL;
6. links the ingested entity to a deterministic verified smoke-test relationship;
7. calls `POST /api/v1/graph/path` and requires a verified path;
8. calls `GET /api/v1/relationships/{id}/why` and requires provenance;
9. rechecks all infrastructure services.

Run the same test on a Docker-capable developer machine:

```bash
cp .env.example .env
bash scripts/docker_smoke.sh
```

The live external ingestion is retried, but an unavailable or incompatible upstream GLEIF API still causes the smoke test to fail intentionally: an end-to-end test should detect that the real integration is unavailable.
