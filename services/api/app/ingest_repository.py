from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


async def get_source_id(conn, code: str) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM sources WHERE code=%s AND active=TRUE", (code,))
        row = await cur.fetchone()
    if not row:
        raise RuntimeError(f"source {code!r} is not seeded")
    return row["id"]


async def create_ingest_job(
    conn, source_id: UUID, job_type: str, request_payload: dict[str, Any]
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO ingest_jobs(source_id, job_type, request_payload, status)
               VALUES (%s,%s,%s,'RUNNING') RETURNING id""",
            (source_id, job_type, Jsonb(request_payload)),
        )
        return (await cur.fetchone())["id"]


async def finish_ingest_job(
    conn,
    job_id: UUID,
    status: str,
    source_record_id: UUID | None,
    raw_artifact_id: UUID | None,
    error: str | None,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """UPDATE ingest_jobs
               SET status=%s, finished_at=now(), source_record_id=%s,
                   raw_artifact_id=%s, error_summary=%s
               WHERE id=%s""",
            (status, source_record_id, raw_artifact_id, error, job_id),
        )


async def upsert_raw_artifact(
    conn, source_id: UUID, external_id: str, artifact, metadata: dict[str, Any]
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO raw_artifacts(
                   source_id, external_id, content_hash, object_key, media_type, byte_length, metadata
               ) VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id, external_id, content_hash)
               DO UPDATE SET metadata = raw_artifacts.metadata || EXCLUDED.metadata
               RETURNING id""",
            (
                source_id,
                external_id,
                artifact.sha256,
                artifact.object_key,
                artifact.media_type,
                artifact.byte_length,
                Jsonb(metadata),
            ),
        )
        return (await cur.fetchone())["id"]


async def upsert_source_record(
    conn,
    *,
    source_id: UUID,
    external_id: str,
    payload_hash: str,
    payload_uri: str,
    parser_version: str,
    schema_version: str | None,
    raw_payload: dict[str, Any] | None,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO source_records(
                   source_id, external_id, payload_uri, payload_hash,
                   parser_version, schema_version, raw_payload
               ) VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id, external_id, payload_hash)
               DO UPDATE SET payload_uri=EXCLUDED.payload_uri
               RETURNING id""",
            (
                source_id,
                external_id,
                payload_uri,
                payload_hash,
                parser_version,
                schema_version,
                Jsonb(raw_payload) if raw_payload is not None else None,
            ),
        )
        return (await cur.fetchone())["id"]


async def ensure_entity(
    conn,
    *,
    entity_type: str,
    canonical_name: str,
    normalized_name: str,
    jurisdiction_code: str | None,
    identifier_scheme: str,
    identifier_value: str,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (identifier_scheme + ":" + identifier_value,),
        )
        await cur.execute(
            """SELECT e.id FROM entities e
               JOIN entity_identifiers i ON i.entity_id=e.id
               WHERE i.scheme=%s AND i.identifier_value=%s
                 AND (CAST(%s AS TEXT) IS NULL OR i.country_code IS NULL OR i.country_code=CAST(%s AS TEXT))
               ORDER BY i.verified DESC, e.created_at ASC LIMIT 1""",
            (identifier_scheme, identifier_value, jurisdiction_code, jurisdiction_code),
        )
        row = await cur.fetchone()
        if row:
            return row["id"]
        await cur.execute(
            """INSERT INTO entities(
                   entity_type, canonical_name, normalized_name, jurisdiction_code, status
               ) VALUES (%s,%s,%s,%s,'ACTIVE') RETURNING id""",
            (entity_type, canonical_name, normalized_name, jurisdiction_code),
        )
        return (await cur.fetchone())["id"]


async def ensure_identifier(
    conn,
    *,
    entity_id: UUID,
    scheme: str,
    identifier_value: str,
    country_code: str | None,
    verified: bool,
    source_record_id: UUID | None,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT id FROM entity_identifiers
               WHERE entity_id=%s AND scheme=%s AND identifier_value=%s LIMIT 1""",
            (entity_id, scheme, identifier_value),
        )
        row = await cur.fetchone()
        if row:
            await cur.execute(
                """UPDATE entity_identifiers
                   SET verified = verified OR %s,
                       source_record_id = COALESCE(source_record_id, %s)
                   WHERE id=%s""",
                (verified, source_record_id, row["id"]),
            )
            return row["id"]
        await cur.execute(
            """INSERT INTO entity_identifiers(
                   entity_id, scheme, identifier_value, country_code, verified, source_record_id
               ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (entity_id, scheme, identifier_value, country_code, verified, source_record_id),
        )
        return (await cur.fetchone())["id"]


async def ensure_claim_with_source(
    conn,
    *,
    subject_entity_id: UUID,
    predicate: str,
    literal_value: dict[str, Any],
    claim_type: str,
    verification_status: str,
    source_record_id: UUID,
    evidence_strength: str,
    extraction_method: str,
    document_version_id: UUID | None = None,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT c.id FROM claims c
               JOIN claim_evidence ce ON ce.claim_id=c.id
               WHERE c.subject_entity_id=%s AND c.predicate=%s
                 AND c.literal_value=%s::jsonb AND ce.source_record_id=%s
               LIMIT 1""",
            (subject_entity_id, predicate, Jsonb(literal_value), source_record_id),
        )
        row = await cur.fetchone()
        if row:
            return row["id"]
        await cur.execute(
            """INSERT INTO claims(
                   subject_entity_id, predicate, literal_value, claim_type, verification_status
               ) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (subject_entity_id, predicate, Jsonb(literal_value), claim_type, verification_status),
        )
        claim_id = (await cur.fetchone())["id"]
        await cur.execute(
            """INSERT INTO claim_evidence(
                   claim_id, document_version_id, source_record_id,
                   extraction_method, extractor_version, evidence_strength
               ) VALUES (%s,%s,%s,%s,'trace-v0.2',%s)""",
            (claim_id, document_version_id, source_record_id, extraction_method, evidence_strength),
        )
        return claim_id


async def ensure_document_version(
    conn,
    *,
    source_code: str,
    external_document_id: str,
    document_type: str,
    title: str,
    issuer_entity_id: UUID | None,
    canonical_uri: str,
    content_hash: str,
    object_uri: str,
    mime_type: str,
    language: str,
    parser_version: str,
) -> tuple[UUID, UUID]:
    source_id = await get_source_id(conn, source_code)
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO documents(
                   source_id, external_document_id, document_type, title,
                   issuer_entity_id, canonical_uri
               ) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id, external_document_id)
               DO UPDATE SET title=EXCLUDED.title, canonical_uri=EXCLUDED.canonical_uri
               RETURNING id""",
            (
                source_id,
                external_document_id,
                document_type,
                title,
                issuer_entity_id,
                canonical_uri,
            ),
        )
        document_id = (await cur.fetchone())["id"]
        await cur.execute(
            """INSERT INTO document_versions(
                   document_id, content_hash, object_uri, mime_type, language, parser_version
               ) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (document_id, content_hash)
               DO UPDATE SET object_uri=EXCLUDED.object_uri
               RETURNING id""",
            (document_id, content_hash, object_uri, mime_type, language, parser_version),
        )
        return document_id, (await cur.fetchone())["id"]
