from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .entity_resolution.normalize import normalize_identifier, normalize_org_name, normalize_text
from .ingest_repository import ensure_entity, ensure_identifier, get_source_id


async def _get_mapping(conn, source_id: UUID, external_key: str) -> UUID | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT entity_id FROM source_entity_mappings WHERE source_id=%s AND external_entity_key=%s",
            (source_id, external_key),
        )
        row = await cur.fetchone()
        return row["entity_id"] if row else None


async def find_entity_by_identifier(
    conn,
    *,
    scheme: str,
    identifier_value: str,
    country_code: str | None = None,
) -> UUID | None:
    normalized = normalize_identifier(identifier_value)
    if not normalized:
        return None
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT entity_id FROM entity_identifiers
               WHERE scheme=%s AND identifier_value=%s
                 AND (%s IS NULL OR country_code IS NULL OR country_code=%s)
               ORDER BY verified DESC, created_at ASC LIMIT 1""",
            (scheme, normalized, country_code, country_code),
        )
        row = await cur.fetchone()
        return row["entity_id"] if row else None


async def save_source_mapping(
    conn,
    *,
    source_id: UUID,
    external_key: str,
    entity_id: UUID,
    method: str,
    confidence: float,
    source_record_id: UUID | None,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO source_entity_mappings(
                   source_id, external_entity_key, entity_id, mapping_method,
                   confidence, source_record_id
               ) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id, external_entity_key)
               DO UPDATE SET entity_id=EXCLUDED.entity_id,
                             mapping_method=EXCLUDED.mapping_method,
                             confidence=EXCLUDED.confidence,
                             source_record_id=COALESCE(EXCLUDED.source_record_id, source_entity_mappings.source_record_id),
                             updated_at=now()""",
            (source_id, external_key, entity_id, method, confidence, source_record_id),
        )


async def _queue_name_candidates(
    conn,
    *,
    entity_id: UUID,
    normalized_name: str,
    entity_type: str,
    jurisdiction_code: str | None,
) -> None:
    if not normalized_name:
        return
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT id, similarity(normalized_name, %s) AS score
               FROM entities
               WHERE id<>%s AND entity_type=%s
                 AND (%s IS NULL OR jurisdiction_code IS NULL OR jurisdiction_code=%s)
                 AND similarity(normalized_name, %s) >= 0.90
               ORDER BY score DESC LIMIT 5""",
            (
                normalized_name,
                entity_id,
                entity_type,
                jurisdiction_code,
                jurisdiction_code,
                normalized_name,
            ),
        )
        for row in await cur.fetchall():
            left_id, right_id = sorted([entity_id, row["id"]], key=str)
            await cur.execute(
                """SELECT 1 FROM entity_resolution_queue
                   WHERE left_entity_id=%s AND right_entity_id=%s AND status='OPEN'""",
                (left_id, right_id),
            )
            if await cur.fetchone():
                continue
            await cur.execute(
                """INSERT INTO entity_resolution_queue(
                       left_entity_id, right_entity_id, score, features, reasons
                   ) VALUES (%s,%s,%s,%s,%s)""",
                (
                    left_id,
                    right_id,
                    row["score"],
                    Jsonb({"normalized_name": float(row["score"])}),
                    Jsonb(["cross-source name candidate; requires human review"]),
                ),
            )


async def resolve_external_entity(
    conn,
    *,
    source_code: str,
    external_key: str,
    entity_type: str,
    name: str | None,
    jurisdiction_code: str | None,
    source_record_id: UUID | None,
    strong_identifier: str | None = None,
    strong_scheme: str = "NATIONAL_COMPANY_NUMBER",
) -> UUID:
    source_id = await get_source_id(conn, source_code)
    mapped = await _get_mapping(conn, source_id, external_key)
    if mapped:
        return mapped

    normalized_name = (
        normalize_org_name(name)
        if entity_type in {"ORGANIZATION", "PUBLIC_BODY"}
        else normalize_text(name)
    )
    display_name = name or f"{source_code} entity {external_key}"
    identifier_value = normalize_identifier(strong_identifier)

    if identifier_value:
        entity_id = await ensure_entity(
            conn,
            entity_type=entity_type,
            canonical_name=display_name,
            normalized_name=normalized_name or normalize_text(display_name),
            jurisdiction_code=jurisdiction_code,
            identifier_scheme=strong_scheme,
            identifier_value=identifier_value,
        )
        await ensure_identifier(
            conn,
            entity_id=entity_id,
            scheme=strong_scheme,
            identifier_value=identifier_value,
            country_code=jurisdiction_code,
            verified=True,
            source_record_id=source_record_id,
        )
        method = f"EXACT_{strong_scheme}"
        confidence = 1.0
    else:
        source_scheme = f"SOURCE:{source_code}"
        entity_id = await ensure_entity(
            conn,
            entity_type=entity_type,
            canonical_name=display_name,
            normalized_name=normalized_name or normalize_text(display_name),
            jurisdiction_code=jurisdiction_code,
            identifier_scheme=source_scheme,
            identifier_value=external_key,
        )
        await ensure_identifier(
            conn,
            entity_id=entity_id,
            scheme=source_scheme,
            identifier_value=external_key,
            country_code=jurisdiction_code,
            verified=True,
            source_record_id=source_record_id,
        )
        method = "SOURCE_SCOPED_ID"
        confidence = 1.0
        await _queue_name_candidates(
            conn,
            entity_id=entity_id,
            normalized_name=normalized_name,
            entity_type=entity_type,
            jurisdiction_code=jurisdiction_code,
        )

    await save_source_mapping(
        conn,
        source_id=source_id,
        external_key=external_key,
        entity_id=entity_id,
        method=method,
        confidence=confidence,
        source_record_id=source_record_id,
    )
    return entity_id
