from datetime import datetime
from uuid import UUID

from .db import connection
from .temporal import resolve_known_at


async def search_entities(
    q: str,
    entity_type: str | None,
    limit: int = 25,
    include_demo: bool = False,
    known_at: datetime | None = None,
):
    known_at = await resolve_known_at(known_at)
    normalized = " ".join(q.lower().split())
    params = {
        "q": normalized,
        "limit": limit,
        "entity_type": entity_type,
        "include_demo": include_demo,
        "known_at": known_at,
    }
    type_clause = "AND entity_type = %(entity_type)s" if entity_type else ""
    sql = f"""
        SELECT id, entity_type, canonical_name, jurisdiction_code, status,
               similarity(normalized_name, %(q)s) AS similarity
        FROM trace_entities_at(%(known_at)s)
        WHERE (normalized_name %% %(q)s OR normalized_name LIKE '%%' || %(q)s || '%%')
          AND (NOT is_demo OR %(include_demo)s)
          {type_clause}
        ORDER BY similarity DESC, canonical_name
        LIMIT %(limit)s
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def get_entity(entity_id: UUID, known_at: datetime | None = None):
    known_at = await resolve_known_at(known_at)
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, entity_type, canonical_name, jurisdiction_code, status FROM trace_entities_at(%s) WHERE id=%s",
                (known_at, entity_id),
            )
            entity = await cur.fetchone()
            if not entity:
                return None
            await cur.execute(
                """SELECT scheme, identifier_value, country_code, verified
                   FROM trace_entity_identifiers_at(%s) WHERE entity_id=%s ORDER BY scheme, identifier_value""",
                (known_at, entity_id),
            )
            entity["identifiers"] = await cur.fetchall()
            return entity
