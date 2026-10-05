import asyncio
import hashlib
import json
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, Field, model_validator

from . import audit
from .adapters import StrictModel
from .connectors.base import ConnectorError
from .connectors.datasets import JsonDatasetConnector, OcdsConnector, OpenOwnershipArchiveConnector
from .db import connection
from .object_store import EvidenceStore
from .observability import prometheus_text
from .pia_ingestion import import_dataset, persist_source
from .relationship_semantics import semantic_key
from .sdg_verification import (
    RecalculateStoredRequest,
    SdgQuery,
    SdgVerificationService,
    VerificationRequest,
)
from .security import bearer_schema, principal, require
from .settings import settings
from .statistical_verification import (
    CrossSourceVerificationRequest,
    StatisticalImportRequest,
    StatisticalRecalculateRequest,
    StatisticalVerificationRequest,
    StatisticalVerificationService,
)
from .temporal import resolve_known_at
from .wealth import ENGINE_VERSION, WealthInput, reconcile

internal = APIRouter(
    prefix="/api/internal", tags=["Internal PIA"], dependencies=[Depends(bearer_schema)]
)
public = APIRouter(prefix="/api/public", tags=["Public portal"])


class ImportRequest(StrictModel):
    format: Literal["ocds", "bods", "ted", "ppds", "trace"]
    dataset_id: str = Field(min_length=1, max_length=200)
    payload: Any
    license: str = Field(min_length=1, max_length=1000)
    legal_basis: str = Field(min_length=1, max_length=2000)
    demo: bool = False
    provenance: dict = Field(default_factory=dict)


class LiveImport(StrictModel):
    source: Literal["ocds", "openownership", "bods", "ppds"]
    limit: int = Field(default=5, ge=1, le=25)
    legal_basis: str = Field(min_length=10, max_length=2000)
    license: str = Field(min_length=1, max_length=1000)


@internal.post("/connectors/fetch")
async def live_import(body: LiveImport, request: Request):
    actor = require(request, "analyst", "admin")
    try:
        if body.source == "ocds":
            connector = OcdsConnector(settings.ocds_base_url, settings.http_timeout_seconds)
            payload = await connector.releases(body.limit)
            format, dataset = "ocds", "find-tender:latest"
        elif body.source == "openownership":
            connector = OpenOwnershipArchiveConnector(
                settings.openownership_archive_url, settings.http_timeout_seconds
            )
            fetched = await connector.sample(body.limit)
            payload = fetched["statements"]
            format, dataset = "bods", "openownership-uk04:archive-prefix"
        else:
            url = getattr(settings, body.source + "_dataset_url")
            if not url:
                raise HTTPException(
                    503, "Source URL not configured; operator access and mapping required"
                )
            connector = JsonDatasetConnector(url, settings.http_timeout_seconds)
            payload = await connector.fetch(getattr(settings, body.source + "_token_env"))
            format, dataset = body.source, "configured:" + body.source
        imported = ImportRequest(
            format=format,
            dataset_id=dataset,
            payload=payload,
            license=body.license,
            legal_basis=body.legal_basis,
            demo=False,
            provenance={
                "source": body.source,
                "endpoint": connector.base_url,
                "responses": connector.responses,
                "snapshot": fetched["snapshot"]
                if body.source.startswith("openownership")
                else None,
            },
        )
        result = await import_dataset(imported, actor.subject)
        return {**result, "source": body.source, "upstream_requests": len(connector.responses)}
    except ValueError as exc:
        raise HTTPException(
            422, "Upstream schema or mapped identifiers invalid; inspect protected evidence"
        ) from exc
    except (ConnectorError, httpx.HTTPError) as exc:
        async with connection() as conn:
            await audit.record(
                conn,
                actor.subject,
                "CONNECTOR_FAILED",
                body.source,
                {"error_code": type(exc).__name__},
            )
        raise


class ClaimReview(StrictModel):
    status: Literal[
        "VERIFIED_PRIMARY",
        "VERIFIED_AUTHORITATIVE",
        "CORROBORATED",
        "UNVERIFIED",
        "CONFLICTED",
        "RETRACTED",
    ]
    note: str = Field(min_length=10, max_length=5000)


class RelationshipCorrection(StrictModel):
    valid_from: AwareDatetime | None
    valid_to: AwareDatetime | None
    source_record_id: UUID
    note: str = Field(min_length=10, max_length=5000)

    @model_validator(mode="after")
    def interval(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Invalid corrected validity interval")
        return self


@internal.post("/relationships/{relationship_id}/correct")
async def correct_relationship(
    relationship_id: UUID, body: RelationshipCorrection, request: Request
):
    actor = require(request, "reviewer")
    async with connection() as conn:
        async with conn.transaction():
            rel = await one(
                conn, "SELECT * FROM relationships WHERE id=%s FOR UPDATE", (relationship_id,)
            )
            if not rel or rel["superseded_at"]:
                raise HTTPException(409, "An active relationship is required")
            claim = await one(
                conn, "SELECT * FROM claims WHERE id=%s FOR UPDATE", (rel["claim_id"],)
            )
            if not claim or claim["created_by"] == actor.subject:
                raise HTTPException(409, "Independent reviewer and canonical claim required")
            source = await one(
                conn,
                "SELECT sr.source_id,s.is_demo FROM source_records sr JOIN sources s ON s.id=sr.source_id WHERE sr.id=%s",
                (body.source_record_id,),
            )
            subject = await one(
                conn, "SELECT is_demo FROM entities WHERE id=%s", (rel["subject_entity_id"],)
            )
            if not source or source["is_demo"] != subject["is_demo"]:
                raise HTTPException(
                    422, "Correction evidence must match the live/test classification"
                )
            await conn.execute(
                "UPDATE relationships SET valid_from=%s,valid_to=%s WHERE id=%s",
                (body.valid_from, body.valid_to, relationship_id),
            )
            await conn.execute(
                "UPDATE claims SET valid_from=%s,valid_to=%s,verification_status='UNVERIFIED',created_by=%s,reviewed_by=%s,reviewed_at=now() WHERE id=%s",
                (body.valid_from, body.valid_to, actor.subject, actor.subject, claim["id"]),
            )
            await conn.execute(
                "UPDATE relationship_observations SET observation_status='SUPERSEDED' WHERE canonical_relationship_id=%s AND observation_status='ACTIVE'",
                (relationship_id,),
            )
            await conn.execute(
                "INSERT INTO claim_evidence(claim_id,source_record_id,extraction_method,evidence_strength) VALUES (%s,%s,'REVIEWED_VALIDITY_CORRECTION','E0') ON CONFLICT DO NOTHING",
                (claim["id"], body.source_record_id),
            )
            key = semantic_key(
                rel["subject_entity_id"],
                rel["relationship_type"],
                rel["object_entity_id"],
                body.valid_from,
                body.valid_to,
            )
            await conn.execute(
                """INSERT INTO relationship_observations(source_id,source_record_id,canonical_relationship_id,subject_entity_id,relationship_type,object_entity_id,valid_from,valid_to,semantic_key,details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_record_id,semantic_key) DO UPDATE SET observation_status='ACTIVE'""",
                (
                    source["source_id"],
                    body.source_record_id,
                    relationship_id,
                    rel["subject_entity_id"],
                    rel["relationship_type"],
                    rel["object_entity_id"],
                    body.valid_from,
                    body.valid_to,
                    key,
                    Jsonb({"correction_note": body.note, "reviewer": actor.subject}),
                ),
            )
            await audit.record(
                conn,
                actor.subject,
                "RELATIONSHIP_CORRECTED",
                str(relationship_id),
                {"source_record_id": str(body.source_record_id), "note": body.note},
            )
    return {"relationship_id": relationship_id, "status": "UNVERIFIED", "history_preserved": True}


class CaseInput(StrictModel):
    entity_id: UUID
    title: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=10, max_length=5000)
    claim_ids: list[UUID] = Field(min_length=1, max_length=100)


class CaseAction(StrictModel):
    action: Literal["review", "publish", "withdraw", "appeal"]
    note: str = Field(min_length=10, max_length=5000)
    public_title: str | None = Field(default=None, min_length=1, max_length=300)
    public_summary: str | None = Field(default=None, min_length=10, max_length=5000)


class SignalReview(StrictModel):
    status: Literal["DISMISSED", "ESCALATED"]
    note: str = Field(min_length=10, max_length=5000)


async def one(conn, sql, args=()):
    return await (await conn.execute(sql, args)).fetchone()


@internal.get("/me")
async def me(request: Request):
    identity = principal(request)
    return {"subject": identity.subject, "role": identity.role, "auth_method": identity.auth_method}


@internal.get("/temporal/status")
async def temporal_status():
    cutoff = await resolve_known_at()
    async with connection() as conn:
        baseline = await one(
            conn,
            "SELECT c.committed_at FROM temporal_control t JOIN temporal_commits c ON c.transaction_id=t.activation_transaction AND c.cluster_id=t.activation_cluster",
        )
        return {
            "known_at": cutoff,
            "history_available_from": baseline["committed_at"],
            "system_time": "postgresql_transaction_commit",
            "pre_migration_reconstruction": False,
        }


@internal.post("/imports")
async def ingest(body: ImportRequest, request: Request):
    actor = require(request, "analyst", "admin")
    try:
        return await import_dataset(body, actor.subject)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@internal.get("/imports")
async def imports(limit: int = Query(50, ge=1, le=100), include_demo: bool = False):
    async with connection() as conn:
        return await (
            await conn.execute(
                """SELECT b.id,b.dataset_id,b.format,b.status,b.error_code,b.started_at,b.finished_at FROM import_batches b
                   JOIN sources s ON s.id=b.source_id WHERE NOT s.is_demo OR %s ORDER BY b.started_at DESC LIMIT %s""",
                (include_demo, limit),
            )
        ).fetchall()


@internal.get("/claims/{claim_id}")
async def claim_detail(claim_id: UUID, known_at: AwareDatetime | None = None):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        claim = await one(
            conn, "SELECT * FROM trace_claims_at(%s) WHERE id=%s", (known_at, claim_id)
        )
        if not claim:
            raise HTTPException(404, "Claim not found")
        evidence = await (
            await conn.execute(
                """SELECT ce.id,ce.locator,ce.extraction_method,ce.extractor_version,ce.evidence_strength,
               ce.source_record_id,sr.payload_hash,sr.parser_version,sr.retrieved_at,sr.metadata,s.code,s.is_demo
               FROM trace_claim_evidence_at(%s) ce LEFT JOIN trace_source_records_at(%s) sr ON sr.id=ce.source_record_id
               LEFT JOIN trace_sources_at(%s) s ON s.id=sr.source_id WHERE ce.claim_id=%s""",
                (known_at, known_at, known_at, claim_id),
            )
        ).fetchall()
        return {"claim": claim, "evidence": evidence, "known_at": known_at}


@internal.post("/claims/{claim_id}/review")
async def review_claim(claim_id: UUID, body: ClaimReview, request: Request):
    actor = require(request, "reviewer")
    async with connection() as conn:
        async with conn.transaction():
            claim = await one(conn, "SELECT * FROM claims WHERE id=%s FOR UPDATE", (claim_id,))
            if not claim:
                raise HTTPException(404, "Claim not found")
            if claim["created_by"] == actor.subject:
                raise HTTPException(409, "Independent reviewer required")
            evidence = await one(
                conn,
                """SELECT count(*) AS count,COALESCE(bool_or(s.is_demo),false) AS demo FROM claim_evidence ce
                   LEFT JOIN source_records sr ON sr.id=ce.source_record_id LEFT JOIN sources s ON s.id=sr.source_id
                   WHERE ce.claim_id=%s""",
                (claim_id,),
            )
            if not evidence["count"]:
                raise HTTPException(409, "Provenance required before verification")
            if evidence["demo"] and body.status.startswith(("VERIFIED", "CORROBORATED")):
                raise HTTPException(409, "Synthetic evidence cannot be promoted to verified facts")
            await conn.execute(
                "UPDATE claims SET verification_status=%s,reviewed_by=%s,reviewed_at=now() WHERE id=%s",
                (body.status, actor.subject, claim_id),
            )
            await audit.record(
                conn,
                actor.subject,
                "CLAIM_REVIEW",
                str(claim_id),
                {"before": claim["verification_status"], "after": body.status, "note": body.note},
            )
            return {"claim_id": claim_id, "status": body.status}


@internal.get("/evidence/{artifact_id}")
async def evidence(artifact_id: UUID, request: Request, known_at: AwareDatetime | None = None):
    actor = require(request, "analyst", "reviewer", "admin")
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        artifact = await one(
            conn, "SELECT * FROM trace_raw_artifacts_at(%s) WHERE id=%s", (known_at, artifact_id)
        )
        if not artifact:
            raise HTTPException(404, "Evidence not found")
        current = await one(
            conn, "SELECT access_class FROM raw_artifacts WHERE id=%s", (artifact_id,)
        )
        if (
            not current
            or current["access_class"] == "RESTRICTED"
            or artifact["access_class"] == "RESTRICTED"
        ) and actor.role != "admin":
            raise HTTPException(403, "Restricted evidence requires administrator")
        try:
            raw = await asyncio.to_thread(
                EvidenceStore().get_bytes, artifact["object_key"], artifact["content_hash"]
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(
                409, "Evidence missing or hash mismatch; quarantine and investigate"
            ) from exc
        await audit.record(
            conn,
            actor.subject,
            "EVIDENCE_READ",
            str(artifact_id),
            {"sha256": artifact["content_hash"]},
        )
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact_id}.json"',
            "X-Evidence-SHA256": artifact["content_hash"],
            "Cache-Control": "no-store",
        },
    )


@internal.post("/wealth/reconcile")
async def wealth(body: WealthInput, request: Request):
    actor = require(request, "analyst", "admin")
    result = reconcile(body)
    async with connection() as conn:
        async with conn.transaction():
            entity = await one(
                conn, "SELECT entity_type,is_demo FROM entities WHERE id=%s", (body.entity_id,)
            )
            if not entity:
                raise HTTPException(404, "Subject not found")
            if entity["entity_type"] != "PERSON":
                raise HTTPException(422, "Wealth reconciliation requires a person")
            if body.demo != entity["is_demo"]:
                raise HTTPException(
                    422, "Subject and submission must have the same live/test classification"
                )
            _, record_id, artifact_id, _ = await persist_source(
                conn,
                "DEMO" if body.demo else "DECLARATIONS",
                body.dataset_id,
                {"format": "wealth-bridge/1", **body.model_dump(mode="json")},
            )
            row = await one(
                conn,
                """INSERT INTO wealth_submissions(entity_id,source_record_id,period_start,period_end,currency,
                   inputs,result,engine_version,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    body.entity_id,
                    record_id,
                    body.period_start,
                    body.period_end,
                    body.currency,
                    Jsonb(body.model_dump(mode="json")),
                    Jsonb(result),
                    ENGINE_VERSION,
                    actor.subject,
                ),
            )
            await audit.record(
                conn,
                actor.subject,
                "WEALTH_RECONCILED",
                str(row["id"]),
                {"status": result["status"]},
            )
    return {
        **result,
        "submission_id": row["id"],
        "source_record_id": record_id,
        "artifact_id": artifact_id,
    }


@internal.get("/wealth/{entity_id}")
async def wealth_history(
    entity_id: UUID, limit: int = Query(50, ge=1, le=100), known_at: AwareDatetime | None = None
):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        return await (
            await conn.execute(
                "SELECT * FROM trace_wealth_submissions_at(%s) WHERE entity_id=%s ORDER BY created_at DESC LIMIT %s",
                (known_at, entity_id, limit),
            )
        ).fetchall()


@internal.post("/conflicts/scan")
async def scan(request: Request, include_demo: bool = False, known_at: AwareDatetime | None = None):
    actor = require(request, "analyst", "admin")
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        async with conn.transaction():
            # A disclosed role + ownership of a supplier at award time is context requiring review.
            rows = await (
                await conn.execute(
                    """SELECT role.subject_entity_id AS person_id,role.claim_id AS role_claim,
                   own.claim_id AS ownership_claim,pa.id AS award_id,pa.decision_date,
                   role.valid_from AS role_start,own.valid_from AS own_start,
                   winner.claim_id AS award_claim
                   FROM trace_relationships_at(%s) role JOIN trace_relationships_at(%s) own ON own.subject_entity_id=role.subject_entity_id
                   JOIN trace_procurement_awards_at(%s) pa ON pa.buyer_entity_id=role.object_entity_id AND pa.winner_entity_id=own.object_entity_id
                   JOIN trace_relationships_at(%s) winner ON winner.id=pa.buyer_winner_relationship_id
                   JOIN trace_claims_at(%s) cr ON cr.id=role.claim_id JOIN trace_claims_at(%s) co ON co.id=own.claim_id
                   JOIN trace_claims_at(%s) ca ON ca.id=winner.claim_id
                   JOIN trace_entities_at(%s) subject ON subject.id=role.subject_entity_id
                   WHERE role.relationship_type='HOLDS_ROLE_IN'
                     AND own.relationship_type IN ('OWNS','BENEFICIAL_OWNER_OF','DECLARED_INTEREST_IN')
                     AND role.superseded_at IS NULL AND own.superseded_at IS NULL AND winner.superseded_at IS NULL
                     AND cr.verification_status <> 'RETRACTED' AND co.verification_status <> 'RETRACTED'
                     AND ca.verification_status <> 'RETRACTED'
                     AND (NOT subject.is_demo OR %s)
                     AND (pa.decision_date IS NULL OR role.valid_from IS NULL OR role.valid_from::date<=pa.decision_date)
                     AND (pa.decision_date IS NULL OR role.valid_to IS NULL OR role.valid_to::date>=pa.decision_date)
                     AND (pa.decision_date IS NULL OR own.valid_from IS NULL OR own.valid_from::date<=pa.decision_date)
                     AND (pa.decision_date IS NULL OR own.valid_to IS NULL OR own.valid_to::date>=pa.decision_date)
                   ORDER BY pa.id,role.id,own.id LIMIT 1001""",
                    (*([known_at] * 8), include_demo),
                )
            ).fetchall()
            if len(rows) > 1000:
                raise HTTPException(
                    422, "Scan exceeds MVP bound; partition dataset before scanning"
                )
            ids = []
            for row in rows:
                evidence = {
                    "known_at": known_at.isoformat(),
                    "claim_ids": [
                        str(row[k]) for k in ["role_claim", "ownership_claim", "award_claim"]
                    ],
                    "award_id": str(row["award_id"]),
                    "is_legal_conclusion": False,
                    "temporal_uncertainty": not all(
                        row[k] for k in ["decision_date", "role_start", "own_start"]
                    ),
                    "warning": "Source assertions require independent review; no adverse decision is automated",
                }
                fingerprint = hashlib.sha256(
                    json.dumps(evidence, sort_keys=True).encode()
                ).hexdigest()
                saved = await one(
                    conn,
                    """INSERT INTO conflict_signals(entity_id,rule_version,fingerprint,signal_type,evidence)
                       VALUES (%s,'direct-role-supplier/1',%s,'POTENTIAL_CONFLICT',%s)
                       ON CONFLICT(fingerprint) DO UPDATE SET fingerprint=EXCLUDED.fingerprint RETURNING id""",
                    (row["person_id"], fingerprint, Jsonb(evidence)),
                )
                ids.append(saved["id"])
            await audit.record(
                conn,
                actor.subject,
                "CONFLICT_SCAN",
                "direct-role-supplier/1",
                {"signals": len(ids)},
            )
            return {
                "signal_ids": ids,
                "count": len(ids),
                "is_legal_conclusion": False,
                "known_at": known_at,
            }


@internal.get("/conflicts")
async def signals(
    limit: int = Query(50, ge=1, le=100),
    include_demo: bool = False,
    known_at: AwareDatetime | None = None,
):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        return await (
            await conn.execute(
                """SELECT s.* FROM trace_conflict_signals_at(%s) s JOIN trace_entities_at(%s) e ON e.id=s.entity_id
                   WHERE NOT e.is_demo OR %s ORDER BY s.created_at DESC LIMIT %s""",
                (known_at, known_at, include_demo, limit),
            )
        ).fetchall()


@internal.post("/conflicts/{signal_id}/review")
async def signal_review(signal_id: UUID, body: SignalReview, request: Request):
    actor = require(request, "reviewer")
    async with connection() as conn:
        async with conn.transaction():
            row = await one(
                conn, "SELECT status FROM conflict_signals WHERE id=%s FOR UPDATE", (signal_id,)
            )
            if not row:
                raise HTTPException(404, "Signal not found")
            if row["status"] != "OPEN":
                raise HTTPException(409, "Signal already reviewed")
            await conn.execute(
                "UPDATE conflict_signals SET status=%s,reviewed_by=%s,review_note=%s,reviewed_at=now() WHERE id=%s",
                (body.status, actor.subject, body.note, signal_id),
            )
            await audit.record(
                conn, actor.subject, "CONFLICT_REVIEW", str(signal_id), body.model_dump()
            )
            return {"id": signal_id, "status": body.status}


@internal.post("/cases")
async def create_case(body: CaseInput, request: Request):
    actor = require(request, "analyst", "admin")
    async with connection() as conn:
        async with conn.transaction():
            if not await one(conn, "SELECT id FROM entities WHERE id=%s", (body.entity_id,)):
                raise HTTPException(404, "Entity not found")
            claims = await (
                await conn.execute("SELECT id FROM claims WHERE id=ANY(%s)", (body.claim_ids,))
            ).fetchall()
            if len(claims) != len(set(body.claim_ids)):
                raise HTTPException(422, "Every cited claim must exist")
            row = await one(
                conn,
                "INSERT INTO cases(entity_id,title,reason,created_by) VALUES (%s,%s,%s,%s) RETURNING *",
                (body.entity_id, body.title, body.reason, actor.subject),
            )
            for claim_id in set(body.claim_ids):
                await conn.execute(
                    "INSERT INTO case_evidence(case_id,claim_id) VALUES (%s,%s)",
                    (row["id"], claim_id),
                )
            await conn.execute(
                "INSERT INTO case_events(case_id,actor,event_type,note) VALUES (%s,%s,'CREATED',%s)",
                (row["id"], actor.subject, body.reason),
            )
            await audit.record(conn, actor.subject, "CASE_CREATED", str(row["id"]))
            return row


@internal.get("/cases")
async def cases(
    limit: int = Query(50, ge=1, le=100),
    include_demo: bool = False,
    known_at: AwareDatetime | None = None,
):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        return await (
            await conn.execute(
                """SELECT c.* FROM trace_cases_at(%s) c JOIN trace_entities_at(%s) e ON e.id=c.entity_id
                                  WHERE NOT e.is_demo OR %s ORDER BY c.created_at DESC LIMIT %s""",
                (known_at, known_at, include_demo, limit),
            )
        ).fetchall()


@internal.get("/cases/{case_id}")
async def case_detail(case_id: UUID, known_at: AwareDatetime | None = None):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        case = await one(conn, "SELECT * FROM trace_cases_at(%s) WHERE id=%s", (known_at, case_id))
        if not case:
            raise HTTPException(404, "Case not found")
        events = await (
            await conn.execute(
                "SELECT * FROM trace_case_events_at(%s) WHERE case_id=%s ORDER BY created_at",
                (known_at, case_id),
            )
        ).fetchall()
        claims = await (
            await conn.execute(
                "SELECT claim_id FROM trace_case_evidence_at(%s) WHERE case_id=%s",
                (known_at, case_id),
            )
        ).fetchall()
        return {"case": case, "events": events, "claims": claims, "known_at": known_at}


@internal.post("/cases/{case_id}/actions")
async def case_action(case_id: UUID, body: CaseAction, request: Request):
    roles = {
        "review": ("reviewer",),
        "publish": ("publisher",),
        "withdraw": ("publisher", "reviewer", "admin"),
        "appeal": ("analyst", "reviewer", "admin"),
    }
    actor = require(request, *roles[body.action])
    async with connection() as conn:
        async with conn.transaction():
            case = await one(conn, "SELECT * FROM cases WHERE id=%s FOR UPDATE", (case_id,))
            if not case:
                raise HTTPException(404, "Case not found")
            if body.action == "review":
                if case["status"] != "OPEN" or actor.subject == case["created_by"]:
                    raise HTTPException(409, "Open case and independent reviewer required")
                if not body.public_title or not body.public_summary:
                    raise HTTPException(
                        422, "Reviewer must prepare explicitly redacted public title and summary"
                    )
                await conn.execute(
                    """UPDATE cases SET status='REVIEWED',reviewed_by=%s,review_note=%s,
                       publication_title=%s,publication_summary=%s,updated_at=now() WHERE id=%s""",
                    (actor.subject, body.note, body.public_title, body.public_summary, case_id),
                )
            elif body.action == "publish":
                if case["status"] != "REVIEWED" or actor.subject in {
                    case["created_by"],
                    case["reviewed_by"],
                }:
                    raise HTTPException(409, "Independent publisher and reviewed case required")
                # Publisher cannot silently replace the reviewed text.
                if body.public_title is not None or body.public_summary is not None:
                    raise HTTPException(422, "Publish uses the reviewer-approved public text")
                synthetic = await one(
                    conn,
                    """SELECT COALESCE(bool_or(s.is_demo),false) AS demo FROM case_evidence ce
                       JOIN claim_evidence ev ON ev.claim_id=ce.claim_id
                       JOIN source_records sr ON sr.id=ev.source_record_id
                       JOIN sources s ON s.id=sr.source_id WHERE ce.case_id=%s""",
                    (case_id,),
                )
                if settings.trace_env == "production" and synthetic["demo"]:
                    raise HTTPException(409, "Synthetic cases cannot be published in production")
                release = await one(
                    conn,
                    """INSERT INTO public_releases(case_id,title,summary,publication_note,published_by)
                       VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        case_id,
                        case["publication_title"],
                        case["publication_summary"],
                        body.note,
                        actor.subject,
                    ),
                )
                await conn.execute(
                    "UPDATE cases SET status='PUBLISHED',published_by=%s,updated_at=now() WHERE id=%s",
                    (actor.subject, case_id),
                )
                await audit.record(
                    conn, actor.subject, "PUBLIC_RELEASE_CREATED", str(release["id"])
                )
            else:
                if body.action == "withdraw" and case["status"] != "PUBLISHED":
                    raise HTTPException(409, "Only published cases can be withdrawn")
                # Appeal immediately removes public text pending new review and preserves the event history.
                await conn.execute(
                    "UPDATE public_releases SET withdrawn_at=now() WHERE case_id=%s AND withdrawn_at IS NULL",
                    (case_id,),
                )
                await conn.execute(
                    """UPDATE cases SET status=%s,reviewed_by=NULL,review_note=NULL,published_by=NULL,
                       publication_title=NULL,publication_summary=NULL,updated_at=now() WHERE id=%s""",
                    ("OPEN" if body.action == "appeal" else "WITHDRAWN", case_id),
                )
            await conn.execute(
                "INSERT INTO case_events(case_id,actor,event_type,note) VALUES (%s,%s,%s,%s)",
                (case_id, actor.subject, body.action.upper(), body.note),
            )
            await audit.record(
                conn,
                actor.subject,
                "CASE_" + body.action.upper(),
                str(case_id),
                {"note": body.note},
            )
            return await one(conn, "SELECT * FROM cases WHERE id=%s", (case_id,))


@internal.get("/audit")
async def audit_list(
    request: Request, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
):
    require(request, "reviewer", "admin")
    async with connection() as conn:
        return await (
            await conn.execute(
                "SELECT * FROM audit_events WHERE id>%s ORDER BY id LIMIT %s", (after_id, limit)
            )
        ).fetchall()


@public.get("/status")
async def public_status():
    return {
        "name": "TRACE-PIA",
        "version": "0.4.0",
        "scope": "Only explicitly reviewed public releases; relationships and signals are not legal conclusions",
    }


@public.get("/releases")
async def public_releases(limit: int = Query(25, ge=1, le=100)):
    async with connection() as conn:
        return await (
            await conn.execute(
                "SELECT id,title,summary,published_at FROM public_releases WHERE withdrawn_at IS NULL ORDER BY published_at DESC LIMIT %s",
                (limit,),
            )
        ).fetchall()



class SdgImportRequest(StrictModel):
    query: SdgQuery
    legal_basis: str = Field(min_length=10, max_length=2000)


@internal.post("/sdg/import", include_in_schema=False)
async def sdg_import(body: SdgImportRequest, request: Request):
    """Fetch and persist a complete immutable snapshot from the official UNSD SDG API."""
    actor = require(request, "analyst", "admin")
    try:
        snapshot = await SdgVerificationService().import_snapshot(
            body.query, actor.subject, body.legal_basis
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "source": "UN_SDG",
        "status": "SUCCEEDED",
        "source_record_id": snapshot.source_record_id,
        "artifact_id": snapshot.artifact_id,
        "observation_count": snapshot.observation_count,
        "sha256": snapshot.sha256,
        "external_id": snapshot.external_id,
        "demo": False,
    }


@internal.post("/sdg/recalculate", include_in_schema=False)
async def sdg_recalculate(body: RecalculateStoredRequest, request: Request):
    """Recompute a deterministic metric from a previously captured UN SDG snapshot."""
    actor = require(request, "analyst", "reviewer", "admin")
    try:
        return await SdgVerificationService().recalculate_stored(
            body.source_record_id, body.calculation, actor.subject
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@internal.post("/sdg/verify", include_in_schema=False)
async def sdg_verify(body: VerificationRequest, request: Request):
    """Fetch official data, persist it, independently recalculate, and compare an assertion."""
    actor = require(request, "analyst", "reviewer", "admin")
    try:
        return await SdgVerificationService().verify(body, actor.subject)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@internal.get("/metrics", include_in_schema=False)
async def internal_metrics(request: Request):
    require(request, "admin")
    return Response(
        content=prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )



@internal.post("/statistics/import", include_in_schema=False)
async def statistical_import(body: StatisticalImportRequest, request: Request):
    """Capture a bounded immutable snapshot from an official statistical provider."""
    actor = require(request, "analyst", "admin")
    try:
        snapshot = await StatisticalVerificationService().import_snapshot(
            body.provider, body.query, actor.subject, body.legal_basis
        )
    except (ConnectorError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "provider": snapshot.provider,
        "dataset_code": snapshot.dataset_code,
        "status": "SUCCEEDED",
        "source_record_id": snapshot.source_record_id,
        "artifact_id": snapshot.artifact_id,
        "observation_count": snapshot.observation_count,
        "sha256": snapshot.sha256,
        "external_id": snapshot.external_id,
        "demo": False,
    }


@internal.post("/statistics/recalculate", include_in_schema=False)
async def statistical_recalculate(
    body: StatisticalRecalculateRequest, request: Request
):
    """Reproduce arithmetic from a stored official statistical snapshot."""
    actor = require(request, "analyst", "reviewer", "admin")
    try:
        return await StatisticalVerificationService().recalculate_stored(
            body.source_record_id, body.calculation, actor.subject
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@internal.post("/statistics/verify", include_in_schema=False)
async def statistical_verify(
    body: StatisticalVerificationRequest, request: Request
):
    """Capture official evidence, recalculate, and compare one numeric assertion."""
    actor = require(request, "analyst", "reviewer", "admin")
    try:
        return await StatisticalVerificationService().verify(body, actor.subject)
    except (ConnectorError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@internal.post("/statistics/cross-verify", include_in_schema=False)
async def statistical_cross_verify(
    body: CrossSourceVerificationRequest, request: Request
):
    """Compare an operator-declared equivalent claim across independent providers."""
    actor = require(request, "analyst", "reviewer", "admin")
    try:
        return await StatisticalVerificationService().cross_verify(body, actor.subject)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
