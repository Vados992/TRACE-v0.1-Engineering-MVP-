# TRACE v0.1 MVP

**Transparent Relationship & Allocation Chain Explorer**

TRACE is a provenance-first temporal relationship platform for reconstructing documented public-policy, procurement, corporate, lobbying and funding relationships. It is designed to show evidence and uncertainty, not to assign guilt or political ratings.

## What is implemented

- PostgreSQL canonical schema and checksum-protected SQL migrations.
- OpenAPI 3.1 contract.
- FastAPI service.
- TED v3 Search API connector.
- GLEIF LEI connector.
- EUR-Lex/Cellar CELEX document connector.
- Explainable entity-resolution scorer with exact-identifier precedence.
- Person-safety invariant: no automatic merge from name similarity alone.
- Neo4j rebuild script for canonical relationships.
- Local Docker stack: PostgreSQL, Neo4j, OpenSearch, Redis, MinIO and API.
- Unit tests for normalization and entity resolution.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

API:

```text
http://localhost:8000
http://localhost:8000/docs
```

Health check:

```bash
curl http://localhost:8000/health
```

### Entity-resolution example

```bash
curl -X POST http://localhost:8000/api/v1/resolve/compare \
  -H 'content-type: application/json' \
  -d '{
    "left": {
      "entity_type": "ORGANIZATION",
      "name": "Example AG",
      "jurisdiction_code": "DE",
      "identifiers": {"LEI": "529900TESTTESTTEST00"}
    },
    "right": {
      "entity_type": "ORGANIZATION",
      "name": "Example Aktiengesellschaft",
      "jurisdiction_code": "DE",
      "identifiers": {"LEI": "529900TESTTESTTEST00"}
    }
  }'
```

### GLEIF example

```bash
curl 'http://localhost:8000/api/v1/connectors/gleif/search?name=Siemens&page_size=5'
```

### EUR-Lex example

```bash
curl 'http://localhost:8000/api/v1/connectors/eurlex/32016R0679?language=eng'
```

### TED example

TED uses expert-query syntax. Example field/query combinations should be validated against the current TED field catalogue before production ingestion.

```bash
curl -X POST http://localhost:8000/api/v1/connectors/ted/search \
  -H 'content-type: application/json' \
  -d '{
    "query": "publication-number = 000000-2026",
    "fields": ["publication-number", "notice-title", "buyer-name"],
    "limit": 10
  }'
```

## Local verification

```bash
python -m compileall -q services/api scripts
pytest -q
```

## Security note

The provided Docker Compose file is a **local development topology**, not an internet-facing production deployment. OpenSearch security is deliberately disabled locally. Do not expose database, Neo4j, OpenSearch, Redis or MinIO ports publicly in production.

## Data ethics / legal invariant

TRACE must distinguish documented fact, derived relationship and hypothesis. A meeting followed by a contract may be temporally related, but TRACE must never represent that sequence as proof of improper influence without evidence supporting that causal claim.
