# Databases and storage

| Component | Required? | Purpose / connection |
|---|---|---|
| PostgreSQL 17 | Yes | Primary transactional evidence/graph/case database. `DATABASE_URL` |
| Evidence Vault filesystem | Yes by default, persistent volume | `EVIDENCE_BACKEND=filesystem`, `EVIDENCE_DIRECTORY`; back up alongside DB |
| S3-compatible object storage | Alternative to filesystem | `EVIDENCE_BACKEND=s3`, `MINIO_ENDPOINT`, access/secret keys, bucket, TLS |
| Neo4j 5 | Optional | Rebuildable graph projection; `NEO4J_URI`, user/password; `--profile graph` |
| Redis 7 | Optional | Reserved infrastructure; no durable worker depends on it; `--profile cache` |
| OpenSearch | Optional legacy component | Not needed for entity search, which uses PostgreSQL trigram indexes |
| Apache AGE | Not required | Deliberately not installed; transactional SQL graph avoids extra extension |

PostgreSQL needs `pgcrypto` (hashes/UUIDs) and `pg_trgm` (entity search). Run `python scripts/migrate.py` as the schema owner. The runner locks concurrent migration sessions, applies each file in a transaction and verifies SHA-256 checksums. Existing checksums may use LF or CRLF from older checkouts; only those line-ending variants are accepted. Never edit an applied migration. Add a new numbered file instead.

Migrations 001–005 preserve the original core; 006 adds governance/audit/import/wealth/case projections; 007 separates synthetic entities and protects case event history; 008 retires the old overbroad Cellar derivation, preserving its evidence/history before subject-scoped replay. Source definitions are seeded automatically. No synthetic entity data is loaded during startup.

Development Compose publishes PostgreSQL to loopback 5432. The production-like stack does not publish a database port. It uses `trace_owner` for migrations, then `scripts/provision_runtime.py` creates `trace_runtime` without superuser/create-role/create-database rights. Runtime has data DML and sequence usage, read-only migration metadata and no audit/case-history deletion rights. Re-run provisioning after adding migrations to grant permissions on new tables. The API rejects a superuser connection in production.

For a managed database: create the two roles according to provider policy, apply required extensions as an authorized owner, set an SSL-verified PostgreSQL DSN (for example `?sslmode=verify-full&sslrootcert=/path/provider-ca.pem`), provision the runtime role and test backups/restore. Do not put the owner password in API environment variables.

Filesystem objects use a SHA-256-derived key and atomic first-write behavior, with integrity checks on reads. Object storage is private; enable encryption, versioning and retention/Object Lock if supported and legally appropriate. Filesystem hash addressing is not OS-level WORM storage. Both PostgreSQL and vault must be recovered to a mutually consistent point. See [OPERATIONS.md](OPERATIONS.md).

## Required bitemporal configuration

PostgreSQL must run with `track_commit_timestamp=on` before migration 009. Updated dev/production/desktop Compose files configure it. For native/managed PostgreSQL enable the parameter and restart first, then migrate and re-provision runtime grants. Migration 009 captures 24 versioned tables, an immutable commit receipt cache and a pending receipt queue. Complete DB backups must include these. Read [TEMPORAL.md](TEMPORAL.md) before upgrading or querying old dates.

Migration 010 namespaces XIDs by PostgreSQL's cluster system identifier. The migration/function owner needs permission to execute `pg_control_system()`; runtime uses a SECURITY DEFINER wrapper and keeps read-only ledger access. Confirm this capability with a managed provider. Logical restores preserve original namespace columns and cached commit dates; new writes use the destination cluster identity. Finalize pending receipts before a dump after quiescing writes. Unknown foreign receipts cannot be reconstructed from the destination transaction tracker.
