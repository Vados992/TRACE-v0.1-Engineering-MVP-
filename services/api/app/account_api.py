"""Protected TRACE-ACCOUNT preview, submission, and independent review routes.

Route mounted below /api/internal/, using TRACE BoundaryMiddleware and role rules.
The API does not publish accusations or invoke EVIDENCE-X without operator consent.

Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg.types.json import Jsonb
from pydantic import Field

from . import audit
from .account_connectors import EvidenceXClient, EvidenceXUnavailable
from .account_engine import ProjectAssessmentInput, Strict, assess
from .account_portugal import PortugalBaseClient, PortugalSourceError
from .account_portugal_store import persist_portugal_snapshot
from .db import connection
from .security import require
from .settings import settings

router = APIRouter(prefix="/api/internal/accountability", tags=["TRACE-ACCOUNT"])


class ReviewInput(Strict):
    verdict: Literal["NEEDS_INFORMATION", "DISPUTED", "READY_FOR_EXTERNAL_AUDIT"]
    note: str = Field(min_length=20, max_length=3000)


@router.get("/evidence-x/sources")
async def evidence_x_sources(request: Request, limit: int = Query(default=25, ge=1, le=100)):
    require(request, "reviewer", "admin")
    try:
        client = EvidenceXClient(settings.account_evidence_x_base_url,
                                 settings.account_evidence_x_key.get_secret_value())
        return await client.list_sources(limit)
    except EvidenceXUnavailable as exc:
        raise HTTPException(503, "EVIDENCE-X integration is unavailable or invalid") from exc


@router.post("/preview")
async def preview(payload: ProjectAssessmentInput, request: Request):
    require(request, "analyst", "reviewer", "admin")
    return assess(payload)


@router.post("/submit", status_code=201)
async def submit(payload: ProjectAssessmentInput, request: Request):
    user = require(request, "analyst", "admin")
    result = assess(payload)
    async with connection() as conn:
        async with conn.transaction():
            # TRACE refs must exist. EVIDENCE-X IDs remain operator-supplied external metadata.
            trace_refs = [UUID(str(e.trace_source_record_id)) for e in payload.evidence
                          if e.trace_source_record_id]
            if trace_refs:
                rows = await (await conn.execute(
                    "SELECT id FROM source_records WHERE id = ANY(%s)",
                    (trace_refs,),
                )).fetchall()
                if len(set(trace_refs)) != len(rows):
                    raise HTTPException(422, "Unknown TRACE source record ID")
            project = await (await conn.execute(
                """INSERT INTO accountability_projects(project_key,title,jurisdiction,source_system,created_by)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT(project_key) DO NOTHING RETURNING id,title,jurisdiction""",
                (payload.project_id, payload.title, payload.jurisdiction,
                 payload.source_system, user.subject),
            )).fetchone()
            if project is None:
                project = await (await conn.execute(
                    "SELECT id,title,jurisdiction FROM accountability_projects WHERE project_key=%s",
                    (payload.project_id,),
                )).fetchone()
                if project["title"] != payload.title or project["jurisdiction"] != payload.jurisdiction:
                    raise HTTPException(409, "Project identity is immutable; use a new project key")
            row = await (await conn.execute(
                """INSERT INTO accountability_assessments(project_id,input_sha256,input_json,
                       result_json,submitted_by)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT(project_id,input_sha256) DO NOTHING RETURNING id""",
                (project["id"], result.input_sha256, Jsonb(payload.model_dump(mode="json")),
                 Jsonb(result.model_dump(mode="json")), user.subject),
            )).fetchone()
            reused = row is None
            if reused:
                row = await (await conn.execute(
                    "SELECT id FROM accountability_assessments WHERE project_id=%s AND input_sha256=%s",
                    (project["id"], result.input_sha256),
                )).fetchone()
            else:
                await audit.record(conn, user.subject, "ACCOUNT_ASSESSMENT_CREATED",
                                   str(row["id"]), {"project_key": payload.project_id,
                                                      "hash": result.input_sha256})
    return {"assessment_id": str(row["id"]), "reused": reused,
            "review_state": result.review_state, "result": result}


@router.get("/assessments/{assessment_id}")
async def assessment_detail(assessment_id: UUID, request: Request):
    require(request, "reviewer", "admin")
    async with connection() as conn:
        record = await (await conn.execute(
            """SELECT a.id,p.project_key,a.input_sha256,a.result_json,a.submitted_by,
                      a.created_at FROM accountability_assessments a
               JOIN accountability_projects p ON p.id=a.project_id WHERE a.id=%s""",
            (assessment_id,),
        )).fetchone()
        if record is None:
            raise HTTPException(404, "Assessment not found")
        reviews = await (await conn.execute(
            "SELECT reviewer,verdict,note,created_at FROM accountability_reviews WHERE assessment_id=%s ORDER BY created_at",
            (assessment_id,),
        )).fetchall()
        return {"assessment": record, "reviews": reviews}


@router.post("/assessments/{assessment_id}/review", status_code=201)
async def review(assessment_id: UUID, payload: ReviewInput, request: Request):
    reviewer = require(request, "reviewer")
    async with connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                "SELECT submitted_by FROM accountability_assessments WHERE id=%s FOR UPDATE",
                (assessment_id,),
            )).fetchone()
            if row is None:
                raise HTTPException(404, "Assessment not found")
            if row["submitted_by"] == reviewer.subject:
                raise HTTPException(409, "Review must be independent of submitting analyst")
            existing = await (await conn.execute(
                "SELECT id FROM accountability_reviews WHERE assessment_id=%s AND reviewer=%s",
                (assessment_id, reviewer.subject),
            )).fetchone()
            if existing:
                raise HTTPException(409, "This reviewer has already recorded a review")
            inserted = await (await conn.execute(
                """INSERT INTO accountability_reviews(assessment_id,reviewer,verdict,note)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (assessment_id, reviewer.subject, payload.verdict, payload.note),
            )).fetchone()
            await audit.record(conn, reviewer.subject, "ACCOUNT_REVIEW_CREATED",
                               str(assessment_id), {"review_id": str(inserted["id"]),
                                                     "verdict": payload.verdict})
    return {"review_id": str(inserted["id"]), "status": "reviewed_not_published",
            "verdict": payload.verdict}

# Portuguese official-source capture. Caller supplies no arbitrary URLs.


@router.get('/portugal/catalog')
async def portugal_catalog(request: Request):
    require(request, 'analyst', 'reviewer', 'admin')
    try:
        snapshot, payload, options = await PortugalBaseClient().catalog()
    except PortugalSourceError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        'publisher': payload.get('organization', {}).get('name') if isinstance(payload.get('organization'), dict) else None,
        'dataset': snapshot.dataset_slug, 'sha256': snapshot.sha256,
        'data_status': 'official_catalog_metadata_not_yet_ingested',
        'resources': [{'id': x.id, 'title': x.title, 'format': x.media_format,
                       'url': x.url, 'declared_size': x.published_size} for x in options],
    }


@router.post('/portugal/refresh')
async def portugal_refresh(request: Request, catalog_only: bool = False):
    actor = require(request, 'analyst', 'admin')
    try:
        client = PortugalBaseClient()
        snapshot, _payload, options = await client.catalog()
        capture = await persist_portugal_snapshot(snapshot, actor.subject)
        data_capture = None
        skipped = None
        if not catalog_only:
            # Refuse silent fallback: a missing, oversize or unsupported resource
            # is explicitly reported; catalog capture is not presented as ingest.
            if not options:
                skipped = 'No allowlisted JSON/CSV resource discovered in official catalog'
            else:
                selected = next((r for r in options if r.media_format == 'json'), options[0])
                try:
                    resource, rows = await client.resource(selected)
                    data_capture = await persist_portugal_snapshot(resource, actor.subject, rows)
                except PortugalSourceError as exc:
                    skipped = str(exc)
        return {'catalog': capture, 'records': data_capture,
                'data_status': 'raw_official_records_captured_unreviewed'
                  if data_capture else 'catalog_only_no_contract_rows_captured',
                'resource_note': skipped,
                'warning': 'Contract awards are NOT payments, savings, fiscal damages or findings of misconduct.'}
    except PortugalSourceError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get('/portugal/snapshots/{snapshot_id}/verify')
async def portugal_verify_snapshot(snapshot_id: UUID, request: Request):
    import hashlib
    require(request, 'reviewer', 'admin')
    async with connection() as conn:
        row = await (await conn.execute(
            "SELECT content_sha256, original_bytes, source_record_id FROM "
            "accountability_portugal_snapshots WHERE id=%s",
            (snapshot_id,),
        )).fetchone()
    if row is None:
        raise HTTPException(404, 'Snapshot not found')
    actual = hashlib.sha256(bytes(row['original_bytes'])).hexdigest()
    return {'snapshot_id': str(snapshot_id), 'sha256': actual,
            'integrity_ok': actual == row['content_sha256'],
            'trace_source_record_id': str(row['source_record_id']),
            'note': 'Byte integrity does not establish accuracy of publisher claims.'}
