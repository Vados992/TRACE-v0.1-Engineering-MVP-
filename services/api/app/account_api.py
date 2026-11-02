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
