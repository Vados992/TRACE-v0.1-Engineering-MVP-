"""Atomic TRACE capture of Portuguese official-source bytes and their raw records."""
from psycopg.types.json import Jsonb

from . import audit
from .account_portugal import Snapshot, row_fingerprint, source_key
from .db import connection


async def persist_portugal_snapshot(snapshot: Snapshot, actor: str, rows: list[dict] | None = None):
    rows = rows or []
    # No HTTP calls inside transaction; database-owned provenance and audit are atomic.
    async with connection() as conn:
        async with conn.transaction():
            source = await (await conn.execute(
                """INSERT INTO sources (code,name,publisher,source_type,authority_level,is_demo,
                       base_uri,license,jurisdiction)
                   VALUES ('PORTUGAL_BASE_IMPIC','Portugal BASE open-data contracts',
                      'IMPIC / dados.gov.pt','PROCUREMENT','OFFICIAL',false,
                      'https://dados.gov.pt/','See source dataset licensing','PT')
                   ON CONFLICT(code) DO NOTHING RETURNING id"""
            )).fetchone()
            if source is None:
                source = await (await conn.execute(
                    "SELECT id FROM sources WHERE code='PORTUGAL_BASE_IMPIC'"
                )).fetchone()
            # Existing TRACE source_records uniqueness gives safe idempotency.
            record = await (await conn.execute(
                """INSERT INTO source_records (
                       source_id,external_id,payload_hash,parser_version,metadata,raw_payload)
                   VALUES (%s,%s,%s,'account-portugal-0.2',%s,%s)
                   ON CONFLICT(source_id,external_id,payload_hash) DO NOTHING RETURNING id""",
                (source["id"], f"{snapshot.kind}:{snapshot.url}", snapshot.sha256,
                 Jsonb({"origin": "official_catalog", "verified": False,
                        "media_format": snapshot.media_format}),
                 Jsonb({"url": snapshot.url, "sha256": snapshot.sha256,
                        "kind": snapshot.kind, "row_count": len(rows)})),
            )).fetchone()
            if record is None:
                record = await (await conn.execute(
                    """SELECT id FROM source_records
                       WHERE source_id=%s AND external_id=%s AND payload_hash=%s""",
                    (source["id"], f"{snapshot.kind}:{snapshot.url}", snapshot.sha256),
                )).fetchone()
            inserted = await (await conn.execute(
                """INSERT INTO accountability_portugal_snapshots (
                       source_record_id,dataset_slug,kind,source_url,media_format,
                       content_sha256,original_bytes,captured_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(dataset_slug,kind,source_url,content_sha256)
                   DO NOTHING RETURNING id""",
                (record["id"], snapshot.dataset_slug, snapshot.kind, snapshot.url,
                 snapshot.media_format, snapshot.sha256, snapshot.content, actor),
            )).fetchone()
            reused = inserted is None
            if reused:
                inserted = await (await conn.execute(
                    """SELECT id FROM accountability_portugal_snapshots
                       WHERE dataset_slug=%s AND kind=%s AND source_url=%s AND content_sha256=%s""",
                    (snapshot.dataset_slug, snapshot.kind, snapshot.url, snapshot.sha256),
                )).fetchone()
            else:
                for row in rows:
                    fp = row_fingerprint(row)
                    await conn.execute(
                        """INSERT INTO accountability_portugal_records(
                               snapshot_id,external_key,row_sha256,row_json)
                           VALUES(%s,%s,%s,%s)
                           ON CONFLICT(snapshot_id,external_key,row_sha256) DO NOTHING""",
                        (inserted["id"], source_key(row, fp), fp, Jsonb(row)),
                    )
                await audit.record(conn, actor, "PORTUGAL_BASE_SNAPSHOT_CAPTURED",
                                   str(inserted["id"]),
                                   {"sha256": snapshot.sha256, "kind": snapshot.kind,
                                    "row_count": len(rows)})
            return {"snapshot_id": str(inserted["id"]), "trace_source_record_id": str(record["id"]),
                    "sha256": snapshot.sha256, "kind": snapshot.kind,
                    "row_count": len(rows), "reused": reused,
                    "status": "official_bytes_captured_unreviewed"}
