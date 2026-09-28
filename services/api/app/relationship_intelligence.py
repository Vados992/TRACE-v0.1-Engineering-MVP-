from __future__ import annotations

import json
from datetime import datetime, time, timezone
from typing import Any
from uuid import UUID

from .canonicalize import canonicalize_gleif
from .connectors.eurlex import EurLexConnector
from .connectors.gleif import GleifConnector
from .connectors.ted import TedConnector
from .db import connection
from .entity_reconciliation import (
    find_entity_by_identifier,
    resolve_external_entity,
    save_source_mapping,
)
from .entity_resolution.normalize import normalize_identifier, normalize_org_name
from .ingest_repository import ensure_identifier, get_source_id, upsert_raw_artifact, upsert_source_record
from .models import LobbyingImportRequest, RelationshipBuildResult, TedSearchRequest
from .object_store import EvidenceStore
from .parsers import (
    extract_ted_rows,
    pair_entities,
    parse_cellar_legal_relations,
    parse_gleif_record,
    parse_ted_notice,
)
from .relationship_repository import (
    ensure_money_flow,
    ensure_ownership_interest,
    ensure_relationship_from_observation,
)
from .settings import settings

TED_FIELDS = [
    "publication-number", "notice-title", "procedure-identifier", "publication-date",
    "buyer-name", "buyer-identifier", "buyer-country",
    "winner-name", "winner-identifier", "winner-country", "winner-decision-date",
    "result-value-notice", "result-value-cur-notice", "total-value", "total-value-cur",
]


class RelationshipIntelligenceService:
    def __init__(self) -> None:
        self.store = EvidenceStore()

    async def _persist(
        self,
        conn,
        source: str,
        external_id: str,
        payload: Any,
        schema: str,
        media_type: str = "application/json",
    ) -> tuple[UUID, UUID]:
        if media_type == "application/json":
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        else:
            raw = str(payload).encode()
        artifact = self.store.put_bytes(source, external_id, raw, media_type)
        source_id = await get_source_id(conn, source)
        await upsert_raw_artifact(
            conn, source_id, external_id, artifact, {"schema": schema}
        )
        source_record_id = await upsert_source_record(
            conn,
            source_id=source_id,
            external_id=external_id,
            payload_hash=artifact.sha256,
            payload_uri=self.store.uri(artifact.object_key),
            parser_version="trace-v0.3",
            schema_version=schema,
            raw_payload=None,
        )
        return source_id, source_record_id

    @staticmethod
    async def _claim_id(conn, relationship_id: UUID) -> UUID:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT claim_id FROM relationships WHERE id=%s",
                (relationship_id,),
            )
            row = await cur.fetchone()
        if not row or not row["claim_id"]:
            raise RuntimeError("relationship has no canonical claim")
        return row["claim_id"]

    async def build_gleif_ownership(self, lei: str) -> RelationshipBuildResult:
        connector = GleifConnector(
            settings.gleif_base_url, settings.http_timeout_seconds
        )
        child_payload = await connector.get_lei(lei)
        parents = [
            (
                "direct-parent",
                await connector.direct_parent(lei),
                "DIRECT_ACCOUNTING_PARENT_OF",
                "GLEIF_DIRECT_ACCOUNTING_CONSOLIDATING_PARENT",
            ),
            (
                "ultimate-parent",
                await connector.ultimate_parent(lei),
                "ULTIMATE_ACCOUNTING_PARENT_OF",
                "GLEIF_ULTIMATE_ACCOUNTING_CONSOLIDATING_PARENT",
            ),
        ]
        entity_ids: list[UUID] = []
        relationship_ids: list[UUID] = []
        source_record_ids: list[UUID] = []
        notes: list[str] = []

        async with connection() as conn:
            async with conn.transaction():
                source_id, child_sr = await self._persist(
                    conn, "GLEIF", lei, child_payload, "GLEIF_JSON_API"
                )
                child = await canonicalize_gleif(conn, child_payload, child_sr)
                entity_ids.append(child)
                source_record_ids.append(child_sr)
                await save_source_mapping(
                    conn,
                    source_id=source_id,
                    external_key=f"lei:{lei}",
                    entity_id=child,
                    method="EXACT_LEI",
                    confidence=1.0,
                    source_record_id=child_sr,
                )

                for relation_name, payload, relation_type, basis in parents:
                    if not payload:
                        notes.append(f"GLEIF {relation_name} unavailable for {lei}")
                        continue
                    parsed = parse_gleif_record(payload)
                    _, sr = await self._persist(
                        conn,
                        "GLEIF",
                        f"{lei}:{relation_name}:{parsed['lei']}",
                        payload,
                        "GLEIF_JSON_API_RELATIONSHIP_TARGET",
                    )
                    parent = await canonicalize_gleif(conn, payload, sr)
                    entity_ids.append(parent)
                    source_record_ids.append(sr)
                    await save_source_mapping(
                        conn,
                        source_id=source_id,
                        external_key=f"lei:{parsed['lei']}",
                        entity_id=parent,
                        method="EXACT_LEI",
                        confidence=1.0,
                        source_record_id=sr,
                    )
                    relationship_id, _, _ = await ensure_relationship_from_observation(
                        conn,
                        source_id=source_id,
                        source_record_id=sr,
                        subject_entity_id=parent,
                        relationship_type=relation_type,
                        object_entity_id=child,
                        predicate="ACCOUNTING_CONSOLIDATION_PARENT_RELATIONSHIP",
                        details={
                            "child_lei": lei,
                            "parent_lei": parsed["lei"],
                            "basis": basis,
                            "not_beneficial_ownership": True,
                        },
                        verification_status="VERIFIED_AUTHORITATIVE",
                        evidence_strength="E1",
                        extraction_method="GLEIF_LEVEL2_ENDPOINT",
                    )
                    relationship_ids.append(relationship_id)
                    await ensure_ownership_interest(
                        conn,
                        owner_entity_id=parent,
                        owned_entity_id=child,
                        relationship_basis=basis,
                        valid_from=None,
                        valid_to=None,
                        source_claim_id=await self._claim_id(
                            conn, relationship_id
                        ),
                    )

        return RelationshipBuildResult(
            layer="ownership",
            status="SUCCEEDED",
            source_record_ids=list(dict.fromkeys(source_record_ids)),
            entity_ids=list(dict.fromkeys(entity_ids)),
            relationship_ids=list(dict.fromkeys(relationship_ids)),
            notes=notes
            + [
                "GLEIF Level 2 describes accounting-consolidation parents, "
                "not beneficial ownership."
            ],
        )

    async def _ted_party(
        self,
        conn,
        *,
        source_id: UUID,
        source_record_id: UUID,
        publication_number: str,
        role: str,
        index: int,
        party: dict[str, str | None],
        entity_type: str,
    ) -> UUID:
        identifier = normalize_identifier(party.get("identifier"))
        country = party.get("country")
        key = (
            f"{role}:{publication_number}:{index}:"
            f"{identifier or normalize_org_name(party.get('name'))}"
        )

        if identifier and country:
            existing = await find_entity_by_identifier(
                conn,
                scheme="NATIONAL_COMPANY_NUMBER",
                identifier_value=identifier,
                country_code=country,
            )
            if existing:
                await ensure_identifier(
                    conn,
                    entity_id=existing,
                    scheme="TED_ORG_IDENTIFIER",
                    identifier_value=identifier,
                    country_code=country,
                    verified=True,
                    source_record_id=source_record_id,
                )
                await save_source_mapping(
                    conn,
                    source_id=source_id,
                    external_key=key,
                    entity_id=existing,
                    method="CROSS_SOURCE_NATIONAL_ID_MATCH",
                    confidence=1.0,
                    source_record_id=source_record_id,
                )
                return existing

        return await resolve_external_entity(
            conn,
            source_code="TED",
            external_key=key,
            entity_type=entity_type,
            name=party.get("name"),
            jurisdiction_code=country,
            source_record_id=source_record_id,
            strong_identifier=identifier or None,
            strong_scheme="TED_ORG_IDENTIFIER",
        )

    async def build_ted_procurement(
        self, request: TedSearchRequest
    ) -> RelationshipBuildResult:
        connector = TedConnector(settings.ted_base_url, settings.http_timeout_seconds)
        effective = request.model_copy(
            update={"fields": list(dict.fromkeys([*request.fields, *TED_FIELDS]))}
        )
        payload = await connector.search(effective)
        rows = extract_ted_rows(payload)
        fingerprint = connector.stable_json_hash(
            effective.model_dump(mode="json")
        )[:24]

        entities: list[UUID] = []
        relationships: list[UUID] = []
        money_flows: list[UUID] = []
        notes: list[str] = []

        async with connection() as conn:
            async with conn.transaction():
                source_id, source_record_id = await self._persist(
                    conn,
                    "TED",
                    f"relationship-search-{fingerprint}",
                    payload,
                    "TED_V3_SEARCH_RELATIONSHIP_INTELLIGENCE",
                )

                for row in rows:
                    notice = parse_ted_notice(row)
                    if not notice:
                        continue

                    notice_entity = await resolve_external_entity(
                        conn,
                        source_code="TED",
                        external_key=f"notice:{notice.publication_number}",
                        entity_type="CONTRACT",
                        name=notice.notice_title,
                        jurisdiction_code=(
                            notice.buyer_countries[0]
                            if len(notice.buyer_countries) == 1
                            else "EU"
                        ),
                        source_record_id=source_record_id,
                        strong_identifier=notice.publication_number,
                        strong_scheme="TED_PUBLICATION",
                    )
                    entities.append(notice_entity)

                    buyer_rows = pair_entities(
                        notice.buyer_names,
                        notice.buyer_identifiers,
                        notice.buyer_countries,
                    )
                    winner_rows = pair_entities(
                        notice.winner_names,
                        notice.winner_identifiers,
                        notice.winner_countries,
                    )
                    buyers: list[UUID] = []
                    winners: list[UUID] = []

                    published_at = (
                        datetime.combine(
                            notice.publication_date,
                            time.min,
                            tzinfo=timezone.utc,
                        )
                        if notice.publication_date
                        else None
                    )
                    awarded_at = (
                        datetime.combine(
                            notice.decision_date,
                            time.min,
                            tzinfo=timezone.utc,
                        )
                        if notice.decision_date
                        else None
                    )

                    for index, party in enumerate(buyer_rows):
                        buyer = await self._ted_party(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            publication_number=notice.publication_number,
                            role="buyer",
                            index=index,
                            party=party,
                            entity_type="PUBLIC_BODY",
                        )
                        buyers.append(buyer)
                        entities.append(buyer)
                        rid, _, _ = await ensure_relationship_from_observation(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            subject_entity_id=buyer,
                            relationship_type="BUYER_FOR_PROCUREMENT_NOTICE",
                            object_entity_id=notice_entity,
                            predicate="PROCUREMENT_BUYER",
                            valid_from=published_at,
                            details={
                                "publication_number": notice.publication_number
                            },
                            verification_status="VERIFIED_PRIMARY",
                            evidence_strength="E0",
                            extraction_method="TED_V3_SEARCH_FIELDS",
                        )
                        relationships.append(rid)

                    for index, party in enumerate(winner_rows):
                        winner = await self._ted_party(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            publication_number=notice.publication_number,
                            role="winner",
                            index=index,
                            party=party,
                            entity_type="ORGANIZATION",
                        )
                        winners.append(winner)
                        entities.append(winner)
                        rid, _, _ = await ensure_relationship_from_observation(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            subject_entity_id=notice_entity,
                            relationship_type="AWARDED_TO",
                            object_entity_id=winner,
                            predicate="PROCUREMENT_AWARD_WINNER",
                            valid_from=awarded_at,
                            amount=(
                                notice.total_value
                                if len(winner_rows) == 1
                                else None
                            ),
                            currency=(
                                notice.currency
                                if len(winner_rows) == 1
                                else None
                            ),
                            details={
                                "publication_number": notice.publication_number
                            },
                            verification_status="VERIFIED_PRIMARY",
                            evidence_strength="E0",
                            extraction_method="TED_V3_SEARCH_FIELDS",
                        )
                        relationships.append(rid)

                    direct_rel = None
                    flow_id = None
                    if len(buyers) == 1 and len(winners) == 1:
                        direct_rel, _, _ = await ensure_relationship_from_observation(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            subject_entity_id=buyers[0],
                            relationship_type="AWARDED_CONTRACT_TO",
                            object_entity_id=winners[0],
                            predicate="PROCUREMENT_AWARD",
                            valid_from=awarded_at,
                            amount=notice.total_value,
                            currency=notice.currency,
                            details={
                                "publication_number": notice.publication_number,
                                "procedure_identifier": notice.procedure_identifier,
                                "unique_buyer_winner_pair": True,
                            },
                            verification_status="VERIFIED_PRIMARY",
                            evidence_strength="E0",
                            extraction_method="TED_V3_SEARCH_FIELDS",
                        )
                        relationships.append(direct_rel)

                        if (
                            notice.total_value is not None
                            and notice.currency
                        ):
                            flow_id = await ensure_money_flow(
                                conn,
                                payer_entity_id=buyers[0],
                                recipient_entity_id=winners[0],
                                amount=notice.total_value,
                                currency=notice.currency,
                                flow_type="CONTRACT",
                                flow_state="AWARDED",
                                award_date=notice.decision_date,
                                contract_entity_id=notice_entity,
                                source_claim_id=await self._claim_id(
                                    conn, direct_rel
                                ),
                            )
                            money_flows.append(flow_id)
                    elif notice.total_value is not None and winners:
                        notes.append(
                            f"TED {notice.publication_number}: total value not "
                            "allocated because buyer/winner mapping is not unique."
                        )

                    async with conn.cursor() as cur:
                        for winner in winners:
                            buyer = buyers[0] if len(buyers) == 1 else None
                            await cur.execute(
                                """INSERT INTO procurement_awards(
                                   notice_entity_id,buyer_entity_id,winner_entity_id,
                                   procedure_identifier,publication_number,
                                   decision_date,awarded_amount,currency,
                                   source_record_id,buyer_winner_relationship_id,
                                   money_flow_id
                                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                   ON CONFLICT (
                                     source_record_id,publication_number,
                                     buyer_entity_id,winner_entity_id
                                   ) DO NOTHING""",
                                (
                                    notice_entity,
                                    buyer,
                                    winner,
                                    notice.procedure_identifier,
                                    notice.publication_number,
                                    notice.decision_date,
                                    (
                                        notice.total_value
                                        if len(winners) == 1
                                        else None
                                    ),
                                    (
                                        notice.currency
                                        if len(winners) == 1
                                        else None
                                    ),
                                    source_record_id,
                                    direct_rel,
                                    flow_id,
                                ),
                            )

        if not rows:
            notes.append(
                "TED response contained no recognized notice rows; "
                "raw evidence was still persisted."
            )

        return RelationshipBuildResult(
            layer="procurement",
            status="SUCCEEDED" if rows else "PARTIAL",
            source_record_ids=[source_record_id],
            entity_ids=list(dict.fromkeys(entities)),
            relationship_ids=list(dict.fromkeys(relationships)),
            money_flow_ids=list(dict.fromkeys(money_flows)),
            notes=notes,
        )

    async def import_lobbying(
        self, request: LobbyingImportRequest
    ) -> RelationshipBuildResult:
        entities: list[UUID] = []
        relationships: list[UUID] = []
        records: list[UUID] = []
        notes: list[str] = []

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, "EU_TR")

                for item in request.records:
                    _, source_record_id = await self._persist(
                        conn,
                        "EU_TR",
                        item.source_external_id,
                        item.model_dump(mode="json"),
                        "TRACE_EU_TR_STANDARDIZED_OBSERVATION_V1",
                    )
                    records.append(source_record_id)

                    registrant = await resolve_external_entity(
                        conn,
                        source_code="EU_TR",
                        external_key=f"registrant:{item.transparency_id}",
                        entity_type="ORGANIZATION",
                        name=item.registrant_name,
                        jurisdiction_code=item.registrant_country,
                        source_record_id=source_record_id,
                        strong_identifier=item.transparency_id,
                        strong_scheme="EU_TRANSPARENCY_ID",
                    )
                    entities.append(registrant)

                    institution = None
                    if item.institution_name:
                        institution = await resolve_external_entity(
                            conn,
                            source_code="EU_TR",
                            external_key=(
                                "institution:"
                                + normalize_org_name(item.institution_name)
                            ),
                            entity_type="PUBLIC_BODY",
                            name=item.institution_name,
                            jurisdiction_code="EU",
                            source_record_id=source_record_id,
                        )
                        entities.append(institution)

                    policy = None
                    if item.policy_celex:
                        policy = await resolve_external_entity(
                            conn,
                            source_code="EU_TR",
                            external_key=f"policy:{item.policy_celex}",
                            entity_type="LEGAL_ACT",
                            name=f"EU legal act {item.policy_celex}",
                            jurisdiction_code="EU",
                            source_record_id=source_record_id,
                            strong_identifier=item.policy_celex,
                            strong_scheme="CELEX",
                        )
                        entities.append(policy)

                    observed_at = (
                        datetime.combine(
                            item.meeting_date,
                            time.min,
                            tzinfo=timezone.utc,
                        )
                        if item.meeting_date
                        else None
                    )

                    meeting_rel = None
                    lobbying_rel = None

                    if institution and observed_at:
                        meeting_rel, _, _ = await ensure_relationship_from_observation(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            subject_entity_id=registrant,
                            relationship_type="MET_WITH",
                            object_entity_id=institution,
                            predicate="DOCUMENTED_MEETING_WITH_INTEREST_REPRESENTATIVE",
                            valid_from=observed_at,
                            details={
                                "subject": item.subject,
                                "transparency_id": item.transparency_id,
                            },
                            extraction_method="EU_TRANSPARENCY_STANDARDIZED_IMPORT",
                        )
                        relationships.append(meeting_rel)

                    if policy:
                        lobbying_rel, _, _ = await ensure_relationship_from_observation(
                            conn,
                            source_id=source_id,
                            source_record_id=source_record_id,
                            subject_entity_id=registrant,
                            relationship_type="LOBBIED_ON",
                            object_entity_id=policy,
                            predicate="DISCLOSED_POLICY_INTEREST_ACTIVITY",
                            valid_from=observed_at,
                            details={
                                "subject": item.subject,
                                "transparency_id": item.transparency_id,
                                "explicit_policy_identifier": True,
                            },
                            extraction_method="EU_TRANSPARENCY_STANDARDIZED_IMPORT",
                        )
                        relationships.append(lobbying_rel)
                    elif item.subject:
                        notes.append(
                            f"{item.source_external_id}: no LOBBIED_ON edge "
                            "without explicit policy CELEX."
                        )

                    async with conn.cursor() as cur:
                        await cur.execute(
                            """INSERT INTO lobbying_disclosures(
                               registrant_entity_id,transparency_id,
                               institution_entity_id,policy_entity_id,
                               meeting_date,subject,declared_budget_min,
                               declared_budget_max,currency,source_record_id,
                               relationship_id
                               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (
                                registrant,
                                item.transparency_id,
                                institution,
                                policy,
                                item.meeting_date,
                                item.subject,
                                item.declared_budget_min,
                                item.declared_budget_max,
                                (
                                    item.currency.upper()[:3]
                                    if item.currency
                                    else None
                                ),
                                source_record_id,
                                lobbying_rel or meeting_rel,
                            ),
                        )

        return RelationshipBuildResult(
            layer="lobbying",
            status="SUCCEEDED",
            source_record_ids=list(dict.fromkeys(records)),
            entity_ids=list(dict.fromkeys(entities)),
            relationship_ids=list(dict.fromkeys(relationships)),
            notes=notes,
        )

    async def build_policy_lifecycle(
        self, celex: str
    ) -> RelationshipBuildResult:
        connector = EurLexConnector(
            settings.cellar_base_url, settings.http_timeout_seconds
        )
        rdf = await connector.fetch_metadata_rdf(celex)
        text = str((rdf.payload or {}).get("text", ""))
        parsed = parse_cellar_legal_relations(text, celex)
        entities: list[UUID] = []
        relationships: list[UUID] = []

        async with connection() as conn:
            async with conn.transaction():
                source_id, source_record_id = await self._persist(
                    conn,
                    "EURLEX",
                    f"{celex}:rdf-tree",
                    text,
                    "CELLAR_RDF_TREE",
                    rdf.content_type or "application/rdf+xml",
                )
                subject = await resolve_external_entity(
                    conn,
                    source_code="EURLEX",
                    external_key=f"celex:{celex}",
                    entity_type="LEGAL_ACT",
                    name=f"EU legal act {celex}",
                    jurisdiction_code="EU",
                    source_record_id=source_record_id,
                    strong_identifier=celex,
                    strong_scheme="CELEX",
                )
                entities.append(subject)

                for relation_type, target_celex in parsed:
                    target = await resolve_external_entity(
                        conn,
                        source_code="EURLEX",
                        external_key=f"celex:{target_celex}",
                        entity_type="LEGAL_ACT",
                        name=f"EU legal act {target_celex}",
                        jurisdiction_code="EU",
                        source_record_id=source_record_id,
                        strong_identifier=target_celex,
                        strong_scheme="CELEX",
                    )
                    entities.append(target)

                    relationship_id, _, _ = await ensure_relationship_from_observation(
                        conn,
                        source_id=source_id,
                        source_record_id=source_record_id,
                        subject_entity_id=subject,
                        relationship_type=relation_type,
                        object_entity_id=target,
                        predicate="CELLAR_LEGAL_RELATION",
                        details={
                            "subject_celex": celex,
                            "target_celex": target_celex,
                        },
                        extraction_method="CELLAR_RDF_TREE",
                    )
                    relationships.append(relationship_id)

                    async with conn.cursor() as cur:
                        await cur.execute(
                            """INSERT INTO policy_lifecycle_edges(
                               subject_entity_id,lifecycle_relation,
                               object_entity_id,source_record_id,
                               canonical_relationship_id
                               ) VALUES (%s,%s,%s,%s,%s)
                               ON CONFLICT (
                                 subject_entity_id,lifecycle_relation,
                                 object_entity_id,source_record_id
                               ) DO NOTHING""",
                            (
                                subject,
                                relation_type,
                                target,
                                source_record_id,
                                relationship_id,
                            ),
                        )

        notes = (
            []
            if parsed
            else [
                "No allow-listed Cellar legal relations found; "
                "unknown predicates were ignored."
            ]
        )
        return RelationshipBuildResult(
            layer="policy_lifecycle",
            status="SUCCEEDED" if parsed else "PARTIAL",
            source_record_ids=[source_record_id],
            entity_ids=list(dict.fromkeys(entities)),
            relationship_ids=list(dict.fromkeys(relationships)),
            notes=notes,
        )


async def reconciliation_summary() -> dict[str, int]:
    async with connection() as conn:
        async with conn.cursor() as cur:
            counts: dict[str, int] = {}
            for key, table, where in (
                (
                    "open_entity_candidates",
                    "entity_resolution_queue",
                    " WHERE status='OPEN'",
                ),
                (
                    "open_relationship_conflicts",
                    "reconciliation_conflicts",
                    " WHERE status='OPEN'",
                ),
                ("source_mappings", "source_entity_mappings", ""),
                ("relationship_observations", "relationship_observations", ""),
            ):
                await cur.execute(
                    f"SELECT count(*) AS n FROM {table}{where}"
                )
                counts[key] = (await cur.fetchone())["n"]
    return counts
