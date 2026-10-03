"""Pinned knowledge cutoffs and durable PostgreSQL commit receipts."""

from datetime import datetime

from fastapi import HTTPException

from .db import connection


async def resolve_known_at(known_at: datetime | None = None) -> datetime:
    async with connection() as conn:
        clock = (await (await conn.execute("SELECT clock_timestamp() AS current_time")).fetchone())[
            "current_time"
        ]
        # Refresh after pinning the cutoff: subsequently committed versions cannot enter this view.
        await conn.execute("SELECT trace_finalize_temporal_commits()")
        row = await (
            await conn.execute(
                """SELECT clock_timestamp() AS current_time,c.committed_at AS history_available_from
                   FROM temporal_control t JOIN temporal_commits c
                     ON c.transaction_id=t.activation_transaction"""
            )
        ).fetchone()
        if not row:
            raise HTTPException(503, "Temporal baseline commit receipt unavailable")
        cutoff = known_at or clock
        if cutoff.tzinfo is None:
            raise HTTPException(422, "known_at must include a timezone")
        if cutoff > row["current_time"]:
            raise HTTPException(422, "known_at cannot be in the future")
        if cutoff < row["history_available_from"]:
            raise HTTPException(
                409,
                {
                    "code": "HISTORY_UNAVAILABLE",
                    "history_available_from": row["history_available_from"].isoformat(),
                    "message": "Exact pre-migration history was not captured; no inferred snapshot is returned",
                },
            )
        return cutoff
