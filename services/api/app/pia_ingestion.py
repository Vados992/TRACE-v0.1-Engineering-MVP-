import asyncio
import hashlib
import json

from psycopg.types.json import Jsonb

from . import audit
from .adapters import parse_import
from .db import connection
from .ingest_repository import (
    ensure_entity,
    ensure_identifier,
    get_source_id,
    upsert_raw_artifact,
    upsert_source_record,
)
from .object_store import EvidenceStore
from .relationship_repository import ensure_money_flow, ensure_relationship_from_observation

VERSION = "trace-pia/0.4.0"


async def persist_source(conn, source_code, dataset_id, envelope):
    raw = json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    store = EvidenceStore()
    artifact = await asyncio.to_thread(
        store.put_bytes, source_code, dataset_id, raw, "application/json"
    )
    source_id = await get_source_id(conn, source_code)
    artifact_id = await upsert_raw_artifact(
        conn,
        source_id,
        dataset_id,
        artifact,
        {"format": envelope.get("format"), "demo": source_code == "DEMO"},
    )
    record_id = await upsert_source_record(
        conn,
        source_id=source_id,
        external_id=dataset_id,
        payload_hash=artifact.sha256,
        payload_uri=store.uri(artifact.object_key),
        parser_version=VERSION,
        schema_version=envelope.get("format"),
        raw_payload=None,
    )
    await conn.execute(
        "UPDATE source_records SET metadata=%s WHERE id=%s",
        (
            Jsonb(
                {
                    "license": envelope.get("license"),
                    "legal_basis": envelope.get("legal_basis"),
                    "demo": source_code == "DEMO",
                    "upstream": {
                        k: v for k, v in envelope.get("provenance", {}).items() if k != "responses"
                    },
                    "responses": [
                        {k: v for k, v in r.items() if k != "body_base64"}
                        for r in envelope.get("provenance", {}).get("responses", [])
                    ],
                }
            ),
            record_id,
        ),
    )
    return source_id, record_id, artifact_id, artifact.sha256


async def import_dataset(request, actor: str):
    normalized = parse_import(request.format, request.payload)
    source_code = "DEMO" if request.demo else request.format.upper() + "_IMPORT"
    envelope = request.model_dump(mode="json")
    identity_envelope = {k: v for k, v in envelope.items() if k != "provenance"}
    digest = hashlib.sha256(
        json.dumps(identity_envelope, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    try:
        async with connection() as conn:
            async with conn.transaction():
                # Serialize canonical entity creation and retries across concurrent file imports.
                await conn.execute("SELECT pg_advisory_xact_lock(7450207)")
                source_id = await get_source_id(conn, source_code)
                existing = await (
                    await conn.execute(
                        "SELECT id,status,result FROM import_batches WHERE source_id=%s AND dataset_id=%s AND payload_hash=%s",
                        (source_id, request.dataset_id, digest),
                    )
                ).fetchone()
                if existing and existing["status"] == "SUCCEEDED":
                    await audit.record(conn, actor, "IMPORT_REPLAYED", str(existing["id"]))
                    return {**existing["result"], "replayed": True}
                source_id, record_id, artifact_id, _ = await persist_source(
                    conn, source_code, request.dataset_id, envelope
                )
                batch = await (
                    await conn.execute(
                        """INSERT INTO import_batches(source_id,dataset_id,format,payload_hash,status,created_by,source_record_id)
                       VALUES (%s,%s,%s,%s,'RUNNING',%s,%s)
                       ON CONFLICT(source_id,dataset_id,payload_hash) DO UPDATE SET status='RUNNING',error_code=NULL
                       RETURNING id""",
                        (source_id, request.dataset_id, request.format, digest, actor, record_id),
                    )
                ).fetchone()
                entity_ids, relationship_ids, claim_ids = {}, [], []
                for entity in normalized.entities:
                    # Local references are dataset scoped. Only supplied registry IDs link sources.
                    scheme = entity.scheme or "TRACE_LOCAL"
                    identifier = (
                        entity.identifier or f"{source_code}:{request.dataset_id}:{entity.key}"
                    )
                    if request.demo:
                        scheme = "DEMO:" + scheme  # Synthetic IDs cannot merge with live people.
                    entity_id = await ensure_entity(
                        conn,
                        entity_type=entity.entity_type,
                        canonical_name=entity.name,
                        normalized_name=entity.name.casefold(),
                        jurisdiction_code=entity.country,
                        identifier_scheme=scheme,
                        identifier_value=identifier,
                    )
                    canonical = await (
                        await conn.execute(
                            "SELECT entity_type FROM entities WHERE id=%s", (entity_id,)
                        )
                    ).fetchone()
                    if canonical["entity_type"] != entity.entity_type:
                        raise ValueError(
                            "Identifier has incompatible entity type; human reconciliation required"
                        )
                    await ensure_identifier(
                        conn,
                        entity_id=entity_id,
                        scheme=scheme,
                        identifier_value=identifier,
                        country_code=entity.country,
                        verified=False,
                        source_record_id=record_id,
                    )
                    entity_ids[entity.key] = str(entity_id)
                    if request.demo:
                        await conn.execute(
                            "UPDATE entities SET is_demo=TRUE WHERE id=%s", (entity_id,)
                        )
                for edge in normalized.relationships:
                    relationship_id, _, _ = await ensure_relationship_from_observation(
                        conn,
                        source_id=source_id,
                        source_record_id=record_id,
                        subject_entity_id=entity_ids[edge.subject],
                        object_entity_id=entity_ids[edge.object],
                        relationship_type=edge.relation,
                        predicate=edge.relation,
                        valid_from=edge.valid_from,
                        valid_to=edge.valid_to,
                        amount=edge.amount,
                        currency=edge.currency,
                        details={
                            **edge.details,
                            "locator": edge.locator,
                            "ownership_percent": str(edge.ownership_percent)
                            if edge.ownership_percent is not None
                            else None,
                        },
                        verification_status="UNVERIFIED",
                        evidence_strength="E1",
                        extraction_method=VERSION,
                        extractor_version=VERSION,
                    )
                    relationship_ids.append(str(relationship_id))
                    # This observation has its own claim even if a canonical edge already exists.
                    claim = await (
                        await conn.execute(
                            """SELECT c.id FROM claims c JOIN claim_evidence ce ON ce.claim_id=c.id
                           WHERE ce.source_record_id=%s AND c.subject_entity_id=%s AND c.object_entity_id=%s
                             AND c.predicate=%s AND c.valid_from IS NOT DISTINCT FROM %s
                             AND c.valid_to IS NOT DISTINCT FROM %s ORDER BY c.created_at DESC LIMIT 1""",
                            (
                                record_id,
                                entity_ids[edge.subject],
                                entity_ids[edge.object],
                                edge.relation,
                                edge.valid_from,
                                edge.valid_to,
                            ),
                        )
                    ).fetchone()
                    claim_id = claim["id"]
                    claim_ids.append(str(claim_id))
                    await conn.execute(
                        "UPDATE claims SET created_by=COALESCE(created_by,%s) WHERE id=%s",
                        (actor, claim_id),
                    )
                    await conn.execute(
                        "UPDATE claim_evidence SET locator=%s WHERE claim_id=%s AND source_record_id=%s",
                        (Jsonb({"pointer": edge.locator}), claim_id, record_id),
                    )
                    if edge.relation in {"BENEFICIAL_OWNER_OF", "OWNS"}:
                        await conn.execute(
                            """INSERT INTO ownership_interests(owner_entity_id,owned_entity_id,ownership_percent,
                               relationship_basis,valid_from,valid_to,source_claim_id)
                               SELECT %s,%s,%s,%s,%s,%s,%s WHERE NOT EXISTS
                               (SELECT 1 FROM ownership_interests WHERE source_claim_id=%s)""",
                            (
                                entity_ids[edge.subject],
                                entity_ids[edge.object],
                                edge.ownership_percent,
                                edge.relation,
                                edge.valid_from.date() if edge.valid_from else None,
                                edge.valid_to.date() if edge.valid_to else None,
                                claim_id,
                                claim_id,
                            ),
                        )
                    if edge.relation == "AWARDED_TO":
                        flow_id = None
                        if edge.amount is not None:
                            flow_id = await ensure_money_flow(
                                conn,
                                payer_entity_id=entity_ids[edge.subject],
                                recipient_entity_id=entity_ids[edge.object],
                                amount=edge.amount,
                                currency=edge.currency,
                                flow_type="CONTRACT",
                                flow_state="AWARDED",
                                award_date=edge.valid_from.date() if edge.valid_from else None,
                                contract_entity_id=entity_ids.get(edge.contract),
                                source_claim_id=claim_id,
                            )
                        if not edge.contract:
                            # Do not mislabel a buyer as a procurement notice.
                            continue
                        await conn.execute(
                            """INSERT INTO procurement_awards(notice_entity_id,buyer_entity_id,winner_entity_id,
                               publication_number,decision_date,awarded_amount,currency,source_record_id,
                               buyer_winner_relationship_id,money_flow_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT DO NOTHING""",
                            (
                                entity_ids[edge.contract],
                                entity_ids[edge.subject],
                                entity_ids[edge.object],
                                request.dataset_id + edge.locator,
                                edge.valid_from.date() if edge.valid_from else None,
                                edge.amount,
                                edge.currency,
                                record_id,
                                relationship_id,
                                flow_id,
                            ),
                        )
                result = {
                    "batch_id": str(batch["id"]),
                    "source_record_id": str(record_id),
                    "artifact_id": str(artifact_id),
                    "entity_ids": entity_ids,
                    "relationship_ids": relationship_ids,
                    "claim_ids": claim_ids,
                    "status": "SUCCEEDED",
                    "demo": request.demo,
                    "replayed": False,
                    "warnings": normalized.warnings + ["Imported assertions remain UNVERIFIED"],
                }
                await conn.execute(
                    "UPDATE import_batches SET status='SUCCEEDED',result=%s,finished_at=now() WHERE id=%s",
                    (Jsonb(result), batch["id"]),
                )
                await audit.record(
                    conn,
                    actor,
                    "IMPORT_SUCCEEDED",
                    str(batch["id"]),
                    {"format": request.format, "claims": len(claim_ids), "demo": request.demo},
                )
                return result
    except Exception as exc:
        # Persist the failed attempt after canonical transaction rollback. Never expose error bodies/secrets.
        async with connection() as conn:
            source_id = await get_source_id(conn, source_code)
            await conn.execute(
                """INSERT INTO import_batches(source_id,dataset_id,format,payload_hash,status,created_by,error_code,finished_at)
                   VALUES (%s,%s,%s,%s,'FAILED',%s,%s,now()) ON CONFLICT(source_id,dataset_id,payload_hash)
                   DO UPDATE SET status='FAILED',error_code=EXCLUDED.error_code,finished_at=now()""",
                (source_id, request.dataset_id, request.format, digest, actor, type(exc).__name__),
            )
            await audit.record(
                conn, actor, "IMPORT_FAILED", request.dataset_id, {"error_code": type(exc).__name__}
            )
        raise
