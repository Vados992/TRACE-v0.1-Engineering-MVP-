from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


from .relationship_semantics import semantic_key
async def ensure_relationship_from_observation(
    conn,
    *,
    source_id: UUID,
    source_record_id: UUID,
    subject_entity_id: UUID,
    relationship_type: str,
    object_entity_id: UUID,
    predicate: str,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    details: dict[str, Any] | None = None,
    verification_status: str = "VERIFIED_PRIMARY",
    evidence_strength: str = "E0",
    extraction_method: str = "TRACE_V03_RELATIONSHIP_BUILDER",
) -> tuple[UUID, UUID, bool]:
    if subject_entity_id == object_entity_id:
        raise ValueError("self relationships are not permitted")

    key = semantic_key(
        subject_entity_id,
        relationship_type,
        object_entity_id,
        valid_from,
        valid_to,
    )
    details = details or {}

    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT ro.id, ro.canonical_relationship_id
               FROM relationship_observations ro
               WHERE ro.source_record_id=%s AND ro.semantic_key=%s""",
            (source_record_id, key),
        )
        existing_obs = await cur.fetchone()
        if existing_obs and existing_obs["canonical_relationship_id"]:
            return existing_obs["canonical_relationship_id"], existing_obs["id"], False

        await cur.execute(
            """SELECT r.id
               FROM relationships r
               WHERE r.subject_entity_id=%s AND r.relationship_type=%s
                 AND r.object_entity_id=%s AND r.superseded_at IS NULL
                 AND r.valid_from IS NOT DISTINCT FROM %s
                 AND r.valid_to IS NOT DISTINCT FROM %s
               ORDER BY r.observed_at ASC LIMIT 1""",
            (
                subject_entity_id,
                relationship_type,
                object_entity_id,
                valid_from,
                valid_to,
            ),
        )
        existing_rel = await cur.fetchone()

        claim_literal = {
            "relationship_type": relationship_type,
            "object_entity_id": str(object_entity_id),
            "amount": str(amount) if amount is not None else None,
            "currency": currency,
            "details": details,
        }
        await cur.execute(
            """INSERT INTO claims(
                   subject_entity_id, predicate, object_entity_id, literal_value,
                   valid_from, valid_to, claim_type, verification_status
               ) VALUES (%s,%s,%s,%s,%s,%s,'FACT',%s)
               RETURNING id""",
            (
                subject_entity_id,
                predicate,
                object_entity_id,
                Jsonb(claim_literal),
                valid_from,
                valid_to,
                verification_status,
            ),
        )
        claim_id = (await cur.fetchone())["id"]
        await cur.execute(
            """INSERT INTO claim_evidence(
                   claim_id, source_record_id, extraction_method,
                   extractor_version, evidence_strength
               ) VALUES (%s,%s,%s,'trace-v0.3',%s)""",
            (claim_id, source_record_id, extraction_method, evidence_strength),
        )

        created = existing_rel is None
        if existing_rel:
            relationship_id = existing_rel["id"]
        else:
            await cur.execute(
                """INSERT INTO relationships(
                       subject_entity_id, relationship_type, object_entity_id,
                       valid_from, valid_to, relationship_status, derivation_method, claim_id
                   ) VALUES (%s,%s,%s,%s,%s,'ACTIVE',%s,%s)
                   RETURNING id""",
                (
                    subject_entity_id,
                    relationship_type,
                    object_entity_id,
                    valid_from,
                    valid_to,
                    extraction_method,
                    claim_id,
                ),
            )
            relationship_id = (await cur.fetchone())["id"]

        await cur.execute(
            """INSERT INTO relationship_observations(
                   source_id, source_record_id, canonical_relationship_id,
                   subject_entity_id, relationship_type, object_entity_id,
                   valid_from, valid_to, amount, currency, semantic_key, details
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_record_id, semantic_key)
               DO UPDATE SET canonical_relationship_id=EXCLUDED.canonical_relationship_id,
                             details=relationship_observations.details || EXCLUDED.details
               RETURNING id""",
            (
                source_id,
                source_record_id,
                relationship_id,
                subject_entity_id,
                relationship_type,
                object_entity_id,
                valid_from,
                valid_to,
                amount,
                currency,
                key,
                Jsonb(details),
            ),
        )
        observation_id = (await cur.fetchone())["id"]

        if amount is not None:
            await cur.execute(
                """SELECT id, amount, currency FROM relationship_observations
                   WHERE semantic_key=%s AND id<>%s AND amount IS NOT NULL
                     AND observation_status='ACTIVE'""",
                (key, observation_id),
            )
            for other in await cur.fetchall():
                if other["amount"] != amount or other["currency"] != currency:
                    a, b = sorted([observation_id, other["id"]], key=str)
                    await cur.execute(
                        """INSERT INTO reconciliation_conflicts(
                               conflict_type, semantic_key, observation_a, observation_b, details
                           ) VALUES ('NUMERIC_MISMATCH',%s,%s,%s,%s)
                           ON CONFLICT (observation_a, observation_b) DO NOTHING""",
                        (
                            key,
                            a,
                            b,
                            Jsonb(
                                {
                                    "amount_a": str(amount),
                                    "currency_a": currency,
                                    "amount_b": str(other["amount"]),
                                    "currency_b": other["currency"],
                                }
                            ),
                        ),
                    )

        return relationship_id, observation_id, created


async def ensure_money_flow(
    conn,
    *,
    payer_entity_id: UUID,
    recipient_entity_id: UUID,
    amount: Decimal,
    currency: str,
    flow_type: str,
    flow_state: str,
    award_date: date | None,
    contract_entity_id: UUID | None,
    source_claim_id: UUID,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT id FROM money_flows
               WHERE payer_entity_id=%s AND recipient_entity_id=%s
                 AND amount=%s AND currency=%s AND flow_type=%s AND flow_state=%s
                 AND award_date IS NOT DISTINCT FROM %s
                 AND contract_entity_id IS NOT DISTINCT FROM %s
                 AND source_claim_id=%s
               LIMIT 1""",
            (
                payer_entity_id,
                recipient_entity_id,
                amount,
                currency,
                flow_type,
                flow_state,
                award_date,
                contract_entity_id,
                source_claim_id,
            ),
        )
        row = await cur.fetchone()
        if row:
            return row["id"]
        await cur.execute(
            """INSERT INTO money_flows(
                   payer_entity_id, recipient_entity_id, amount, currency,
                   flow_type, flow_state, award_date, contract_entity_id, source_claim_id
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                payer_entity_id,
                recipient_entity_id,
                amount,
                currency,
                flow_type,
                flow_state,
                award_date,
                contract_entity_id,
                source_claim_id,
            ),
        )
        return (await cur.fetchone())["id"]


async def ensure_ownership_interest(
    conn,
    *,
    owner_entity_id: UUID,
    owned_entity_id: UUID,
    relationship_basis: str,
    valid_from: date | None,
    valid_to: date | None,
    source_claim_id: UUID,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT id FROM ownership_interests
               WHERE owner_entity_id=%s AND owned_entity_id=%s
                 AND relationship_basis=%s
                 AND valid_from IS NOT DISTINCT FROM %s
                 AND valid_to IS NOT DISTINCT FROM %s
               LIMIT 1""",
            (owner_entity_id, owned_entity_id, relationship_basis, valid_from, valid_to),
        )
        row = await cur.fetchone()
        if row:
            return row["id"]
        await cur.execute(
            """INSERT INTO ownership_interests(
                   owner_entity_id, owned_entity_id, relationship_basis,
                   valid_from, valid_to, source_claim_id
               ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                owner_entity_id,
                owned_entity_id,
                relationship_basis,
                valid_from,
                valid_to,
                source_claim_id,
            ),
        )
        return (await cur.fetchone())["id"]
