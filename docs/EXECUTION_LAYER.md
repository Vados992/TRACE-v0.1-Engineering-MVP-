# TRACE v0.2 Execution Layer

## Contract

The execution layer connects public-source retrieval to canonical evidence without allowing the LLM or UI to invent graph facts.

### Persistence order

1. Retrieve public source payload.
2. Calculate SHA-256.
3. Store immutable payload in object storage.
4. Register `raw_artifacts` metadata.
5. Create an immutable `source_records` row.
6. Parse source-specific fields.
7. Resolve/create canonical entities by strong identifiers first.
8. Create claims and evidence references.
9. Create temporal relationships only when the source supports them.
10. Query paths with time and evidence filters.

## Failure semantics

A failed parse must not mutate a raw artifact. A failed entity resolution must preserve the source record. A missing graph path is `UNKNOWN/NO QUALIFYING PATH`, not proof of no relationship.

## Path Finder

v0.2 uses the canonical PostgreSQL relationship table for authoritative traversal. Neo4j remains a rebuildable acceleration/projection layer. This prevents graph freshness from becoming a correctness dependency.

The path finder:

- treats relationships as traversable in either direction for discovery;
- prevents cycles within a path;
- caps depth at 8;
- supports `from_time` / `to_time` overlap filtering;
- can restrict traversal to primary/authoritative/corroborated non-hypothesis claims;
- returns relationship IDs so the client can call `/relationships/{id}/why`.

## Evidence storage

Object keys are content-addressed by SHA-256 and namespaced by source. Re-ingesting identical bytes reuses the same object key. PostgreSQL stores the content hash, object key, source, external ID, media type and byte length.

## Security boundary

v0.2 is local/development deployment. The write ingestion endpoints must not be internet-exposed without authentication, authorization, abuse controls and rate limiting.
