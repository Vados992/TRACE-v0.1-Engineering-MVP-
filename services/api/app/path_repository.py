from datetime import datetime
from typing import Any
from uuid import UUID

from .db import connection


async def fetch_relationship_frontier(
    entity_ids: list[UUID],
    *,
    from_time: datetime | None,
    to_time: datetime | None,
    verified_only: bool,
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    params = {"ids": entity_ids, "from_time": from_time, "to_time": to_time}
    verification_clause = (
        """AND c.verification_status IN (
             'VERIFIED_PRIMARY','VERIFIED_AUTHORITATIVE','CORROBORATED'
           ) AND c.claim_type <> 'HYPOTHESIS'"""
        if verified_only
        else ""
    )
    sql = f"""
        SELECT r.id, r.subject_entity_id, r.object_entity_id, r.relationship_type,
               r.valid_from, r.valid_to,
               COALESCE(c.verification_status, 'UNVERIFIED') AS verification_status,
               COALESCE(c.claim_type, 'DERIVED') AS claim_type
        FROM relationships r
        LEFT JOIN claims c ON c.id=r.claim_id
        WHERE (r.subject_entity_id = ANY(%(ids)s) OR r.object_entity_id = ANY(%(ids)s))
          AND r.superseded_at IS NULL
          AND (%(from_time)s IS NULL OR r.valid_to IS NULL OR r.valid_to >= %(from_time)s)
          AND (%(to_time)s IS NULL OR r.valid_from IS NULL OR r.valid_from <= %(to_time)s)
          {verification_clause}
        ORDER BY r.observed_at ASC, r.id ASC
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def relationship_evidence(relationship_id: UUID) -> dict[str, Any] | None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.relationship_type, r.subject_entity_id, r.object_entity_id,
                          r.valid_from, r.valid_to, r.observed_at, r.derivation_method,
                          c.id AS claim_id, c.claim_type, c.verification_status, c.literal_value
                   FROM relationships r
                   LEFT JOIN claims c ON c.id=r.claim_id
                   WHERE r.id=%s""",
                (relationship_id,),
            )
            rel = await cur.fetchone()
            if not rel:
                return None
            evidence = []
            if rel["claim_id"]:
                await cur.execute(
                    """SELECT ce.evidence_strength, ce.extraction_method, ce.locator,
                              sr.external_id AS source_external_id, s.code AS source_code,
                              sr.payload_uri, d.canonical_uri, d.title
                       FROM claim_evidence ce
                       LEFT JOIN source_records sr ON sr.id=ce.source_record_id
                       LEFT JOIN sources s ON s.id=sr.source_id
                       LEFT JOIN document_versions dv ON dv.id=ce.document_version_id
                       LEFT JOIN documents d ON d.id=dv.document_id
                       WHERE ce.claim_id=%s
                       ORDER BY ce.evidence_strength ASC""",
                    (rel["claim_id"],),
                )
                evidence = await cur.fetchall()
            return {"relationship": rel, "evidence": evidence}
