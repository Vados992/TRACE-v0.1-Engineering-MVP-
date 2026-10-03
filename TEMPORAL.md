# Bitemporal evidence and reconstruction

Two independent clocks are enforced by migration 009 and the API:

* **Valid time** (`valid_from`, `valid_to`, request `from_time`, `to_time`): when a source says a fact applied in the world. Unknown dates stay unknown and set temporal uncertainty.
* **System knowledge time** (`known_at` in requests, `known_from` in graph results): when a transaction containing that version actually **committed in PostgreSQL**. Neither a publisher date, `retrieved_at`, parser execution time nor transaction start substitutes for this clock.

A January ownership assertion imported in March cannot enter a February knowledge snapshot. A correction received in April with a January effective date changes April's knowledge; the March snapshot retains the old statement. Later verification, retraction, supersession, identity changes, additional observations or evidence links do not alter earlier snapshots.

## Storage and read semantics

Database triggers retain full immutable row versions for 24 fact/evidence/identity/review/decision tables, including claims, relationships, observations, source records, artifacts, entity identifiers, procurement awards, monetary flows, cases and their evidence. Base tables are current projections; updates and deletes append history rather than destroying the previous version. TRUNCATE is rejected. Multiple writes in one transaction become visible atomically at its commit; intermediate states inside that transaction are not returned.

PostgreSQL must run with `track_commit_timestamp=on`. Compose enables this automatically. `temporal_pending` collects committed changes; `trace_finalize_temporal_commits()` copies the actual PostgreSQL commit timestamps into immutable durable `temporal_commits` receipts. Every application database connection refreshes receipts before reading and after committing writes. `scripts/finalize_temporal.py` also supports external SQL writers and backup/maintenance operations. Missing/pruned commit timestamps cause an explicit failure, never a silently incomplete history.

Snapshot queries select the last committed version of each record at or before `known_at`, breaking same-transaction ties by version order and excluding tombstones. Valid-time filtering is then applied to that snapshot. Claim status, entity labels, evidence, observation counts and source metadata come from the same knowledge cutoff. Path Finder pins one cutoff for the entire traversal; saved investigations retain that cutoff and their result. Conflict scans evaluate role, ownership, award and claim versions at one cutoff and retain it in the analysis evidence.

The private API supports `known_at` for graph paths, investigations, entity search/detail, relationship provenance, claim detail, artifact retrieval, wealth history, conflict scanning/history and case lists/detail. Omitting it pins current database time for that operation. The analyst console exposes independent fact-period and knowledge-time controls; evidence buttons retain the cutoff of the displayed path. Current authorization always applies, including later evidence restrictions. Public release APIs deliberately serve current approved releases only; historical access must not republish withdrawn material.

## Query

First call authenticated `GET /api/internal/temporal/status` to obtain `history_available_from` and current `known_at`. Select a knowledge timestamp within those bounds and supply it explicitly:

```json
{
  "source_entity_id": "actual-loaded-source-UUID",
  "target_entity_id": "actual-loaded-target-UUID",
  "from_time": "2025-06-01T12:00:00Z",
  "to_time": "2025-06-01T12:00:00Z",
  "known_at": "replace-with-actual-supported-knowledge-timestamp",
  "verified_only": false
}
```

This is request structure, not an executable fabricated evidence example. Replace UUIDs/timestamp with loaded records and a supported cutoff. Equal valid-time endpoints ask for a fact at one instant; a wider interval asks for overlapping validity and Path Finder requires a common interval across the whole path. `verified_only=false` permits internal examination of unverified assertions; it does not promote them to facts.

Knowledge dates require an explicit timezone. Future dates and unknown request fields are rejected with 422. Requests before the history baseline return **409 HISTORY_UNAVAILABLE**, including the earliest supported timestamp.

## Upgrade and historic limits

Migration 009 snapshots existing current rows at its own commit. **It does not invent earlier states or backdate baseline knowledge to old retrieval/creation dates.** Complete exact history is supported from that baseline onward. An earlier installation without version capture cannot promise exact reconstruction of its lost past; raw old evidence may support a separately identified retrospective analysis, but it is not the system's former knowledge snapshot.

For an existing native/managed PostgreSQL installation, enable `track_commit_timestamp=on`, restart PostgreSQL, then run migrations with the owner and re-provision runtime grants. Existing Docker installations use the updated Compose PostgreSQL command; `docker compose up --build -d --wait` recreates the service while preserving named volumes. Production uses its dedicated env file and Compose file. Do not delete volumes or edit previously applied migrations.

Finalize receipts before DB backup, PostgreSQL upgrades, long maintenance and transaction-ID wraparound. A background operator job should run `python scripts/finalize_temporal.py` at least every minute when external SQL writers are used or the API is idle. Back up `temporal_versions`, `temporal_commits`, `temporal_control` and remaining database/evidence together. Source payloads and history contain private data and require the same legal retention/access controls as the original evidence; unlimited retention is not assumed. A DBA can disable triggers or alter the database clock; independent audit checkpoints and infrastructure clock controls remain required.

## Executed regression coverage

PostgreSQL integration tests verify late ingestion, corrections of past validity, identity changes, verification/retraction/supersession, late observations/evidence, saved investigation cutoffs, transaction start versus commit, unavailable/future/naive dates and conflict scans excluding later disclosures. Synthetic fixtures remain exclusively in disposable test databases. Real working databases retain their original evidence and contain no automatic synthetic seeding.
