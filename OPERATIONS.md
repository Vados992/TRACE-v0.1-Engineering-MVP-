# Operations

## Health and monitoring

`GET /health` is process liveness. `GET /ready` checks PostgreSQL migrations and writable evidence storage; required failure gives 503. Authenticated `/api/v1/system/status` also probes optional services; an absent optional Neo4j/Redis/OpenSearch service is not a required-stack failure. It does not prove source freshness.

Monitor request errors, ready status, source retrieval/publication timestamps, failed imports, audit-chain continuity, vault hash failures, disk space, DB connections and migration failures. Connector timeout is an upstream failure; never relabel it as an empty successful dataset. API access logs may contain internal entity IDs; restrict access/retention. No secret request bodies or Bearer keys belong in routine logs.

Use `docker compose logs --tail=200 api migrate postgres`, or the corresponding `--env-file .env.production -f compose.production.yml` prefix. `GET /api/internal/imports` lists import status; reviewer/admin `/api/internal/audit` supports ordered `after_id` pagination. Live-source verification writes aggregate reports to ignored `.artifacts`, not public personal-data dumps.

## Backup and recovery

Back up PostgreSQL and Evidence Vault together with an installation/commit/migration manifest. Protect backups with encryption and access controls; preserve object versions where applicable. A DB-only backup cannot reconstruct vault bytes. Keep offline/off-site copies and test restoration on an isolated environment before relying on them.

Linux example for a development stack (binary output; use provider tools/pgAdmin or binary-safe subprocess redirection on Windows):

```sh
mkdir -p backups
docker compose exec -T postgres pg_dump -U trace -d trace -Fc > backups/trace.dump
docker compose exec -T api tar -C /var/lib/trace/evidence -cf - . > backups/evidence.tar
```

For production, use `trace_owner` and the production Compose file. Do not commit `backups/`; it is ignored. Quiesce new writes or use a provider-consistent DB/object-store checkpoint, then record the audit tail `(id,event_hash)` in independent custody. The application does not ship an automatic backup service or signed off-site checkpoint daemon.

Restore a fresh DB using `pg_restore` as an authorized owner; restore the evidence filesystem/bucket to matching keys; re-provision runtime grants. Compare migration checksums, audit links, referenced artifact hashes and known case counts. Run `/ready`, protected evidence reads, smoke tests and a non-public workflow. Verify that no draft/private content appears through the public gateway. Restore procedures are incomplete until a deployment-specific recovery drill meets its RPO/RTO.

## Audit and integrity incidents

On evidence mismatch, quarantine the affected object and stop relying on its claims; preserve evidence/logs, compare trusted off-site copy and investigate. Do not rewrite content under an existing hash. On audit completion failure (`X-Trace-Audit`), inspect the committed intent and resulting domain records before replaying a request. Replays are idempotent for canonical imports, but case publication and wealth submissions are not arbitrary duplicate-safe operations.

Audit events/case history reject UPDATE, DELETE and TRUNCATE for ordinary operations. The chain can be recomputed using `previous_hash || jsonb_build_array(id, occurred_at AT TIME ZONE 'UTC',actor,action,resource,details)::text` and PostgreSQL `digest(...,'sha256')`. A DBA can bypass protection; checkpoints must be outside DBA control to detect capture. Sequence gaps after rollback are legitimate; verify ordered links rather than requiring contiguous IDs.

## Retention and corrections

Publication withdrawal/appeal removes current public projection and keeps accountable history. Retracting a claim removes it from ordinary path search; it does not erase original evidence. Govern retention/redaction of personal source data, orphan vault objects and backups through a lawful, documented process. No destructive purge API is exposed. Handle legitimate erasure/access requests with accountable operators and counsel, including backup retention consequences.

## Capacity / upgrades

The current HTTP imports are synchronous and bounded; there is no persistent job queue despite optional Redis. Partition large datasets into stable batches. Keep provenance and parser versions during reprocessing. Watch the frontier/expansion limits; split graph investigations rather than raising limits blindly. Use ordinary managed PostgreSQL tuning/index review before adding a second authoritative graph service. Apply only new numbered migrations; migration rollback requires a tested recovery plan.

## Commit receipts and historical availability

Before each database backup or PostgreSQL upgrade run `python scripts/finalize_temporal.py` with the target DSN, or `docker compose exec api python /app/scripts/finalize_temporal.py`. The API also finalizes automatically before reads and after writes. If external SQL writers operate while the API is idle, schedule receipt finalization at least every minute. Preserve temporal versions, receipts and the history baseline together in backup/restore. Missing tracker timestamps fail closed; do not fabricate replacement dates. See [TEMPORAL.md](TEMPORAL.md).
