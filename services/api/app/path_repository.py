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
    known_at: datetime,
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    params = {"ids": entity_ids, "from_time": from_time, "to_time": to_time, "known_at": known_at}
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
               rv.known_from,rv.version_id AS temporal_version_id,
               COALESCE(c.verification_status, 'UNVERIFIED') AS verification_status,
               COALESCE(c.claim_type, 'DERIVED') AS claim_type,
               (SELECT count(*) FROM trace_relationship_observations_at(%(known_at)s) ro
                 WHERE ro.canonical_relationship_id=r.id
                   AND ro.observation_status='ACTIVE') AS observation_count
        FROM trace_relationships_at(%(known_at)s) r
        JOIN trace_versions_at('relationships',%(known_at)s) rv ON rv.record_id=r.id
        LEFT JOIN trace_claims_at(%(known_at)s) c ON c.id=r.claim_id
        WHERE (r.subject_entity_id = ANY(%(ids)s) OR r.object_entity_id = ANY(%(ids)s))
          AND r.superseded_at IS NULL
          AND COALESCE(c.verification_status, 'UNVERIFIED') <> 'RETRACTED'
          AND (CAST(%(from_time)s AS TIMESTAMPTZ) IS NULL OR r.valid_to IS NULL OR r.valid_to >= CAST(%(from_time)s AS TIMESTAMPTZ))
          AND (CAST(%(to_time)s AS TIMESTAMPTZ) IS NULL OR r.valid_from IS NULL OR r.valid_from <= CAST(%(to_time)s AS TIMESTAMPTZ))
          {verification_clause}
        ORDER BY r.observed_at ASC, r.id ASC
        LIMIT 1001
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def relationship_evidence(relationship_id: UUID, known_at: datetime) -> dict[str, Any] | None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.relationship_type, r.subject_entity_id, r.object_entity_id,
                          r.valid_from, r.valid_to, r.observed_at, r.derivation_method,
                          c.id AS claim_id, c.claim_type, c.verification_status, c.literal_value
                   FROM trace_relationships_at(%s) r
                   LEFT JOIN trace_claims_at(%s) c ON c.id=r.claim_id
                   WHERE r.id=%s""",
                (known_at, known_at, relationship_id),
            )
            rel = await cur.fetchone()
            if not rel:
                return None

            await cur.execute(
                """SELECT ro.id AS observation_id, ro.semantic_key, ro.amount, ro.currency,
                          ro.valid_from, ro.valid_to, ro.observation_status, ro.details,
                          s.code AS source_code, sr.external_id AS source_external_id,
                          sr.payload_uri, sr.payload_hash, sr.retrieved_at
                   FROM trace_relationship_observations_at(%s) ro
                   JOIN trace_sources_at(%s) s ON s.id=ro.source_id
                   JOIN trace_source_records_at(%s) sr ON sr.id=ro.source_record_id
                   WHERE ro.canonical_relationship_id=%s
                   ORDER BY ro.created_at ASC""",
                (known_at, known_at, known_at, relationship_id),
            )
            observations = await cur.fetchall()

            evidence = []
            if rel["claim_id"]:
                await cur.execute(
                    """SELECT ce.evidence_strength, ce.extraction_method, ce.locator,
                              sr.external_id AS source_external_id, s.code AS source_code,
                              sr.payload_uri, d.canonical_uri, d.title
                       FROM trace_claim_evidence_at(%s) ce
                       LEFT JOIN trace_source_records_at(%s) sr ON sr.id=ce.source_record_id
                       LEFT JOIN trace_sources_at(%s) s ON s.id=sr.source_id
                       LEFT JOIN trace_document_versions_at(%s) dv ON dv.id=ce.document_version_id
                       LEFT JOIN trace_documents_at(%s) d ON d.id=dv.document_id
                       WHERE ce.claim_id=%s
                       ORDER BY ce.evidence_strength ASC""",
                    (known_at, known_at, known_at, known_at, known_at, rel["claim_id"]),
                )
                evidence = await cur.fetchall()

            await cur.execute(
                """SELECT rc.id, rc.conflict_type, rc.status, rc.details,
                          rc.observation_a, rc.observation_b
                   FROM trace_reconciliation_conflicts_at(%s) rc
                   JOIN trace_relationship_observations_at(%s) a ON a.id=rc.observation_a
                   JOIN trace_relationship_observations_at(%s) b ON b.id=rc.observation_b
                   WHERE a.canonical_relationship_id=%s OR b.canonical_relationship_id=%s
                   ORDER BY rc.created_at ASC""",
                (known_at, known_at, known_at, relationship_id, relationship_id),
            )
            conflicts = await cur.fetchall()

            return {
                "known_at": known_at,
                "relationship": rel,
                "canonical_claim_evidence": evidence,
                "source_observations": observations,
                "reconciliation_conflicts": conflicts,
            }
