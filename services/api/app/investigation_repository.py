from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .db import connection
from .models import InvestigationRequest


async def create_investigation(request: InvestigationRequest) -> UUID:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO investigations(
                       query_text, source_entity_id, target_entity_id, from_time, to_time,
                       max_depth, verified_only, status
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,'RUNNING') RETURNING id""",
                (
                    request.query_text,
                    request.source_entity_id,
                    request.target_entity_id,
                    request.from_time,
                    request.to_time,
                    request.max_depth,
                    request.verified_only,
                ),
            )
            row = await cur.fetchone()
        await conn.commit()
        return row["id"]


async def finish_investigation(
    investigation_id: UUID,
    result: dict[str, Any] | None,
    *,
    error: str | None = None,
) -> None:
    status = "FAILED" if error else "SUCCEEDED"
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE investigations
                   SET status=%s, completed_at=now(), result=%s, error_summary=%s
                   WHERE id=%s""",
                (status, Jsonb(result) if result is not None else None, error, investigation_id),
            )
        await conn.commit()


async def get_investigation(investigation_id: UUID) -> dict[str, Any] | None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT id, query_text, source_entity_id, target_entity_id,
                          from_time, to_time, max_depth, verified_only, status,
                          created_at, completed_at, result, error_summary
                   FROM investigations WHERE id=%s""",
                (investigation_id,),
            )
            return await cur.fetchone()
