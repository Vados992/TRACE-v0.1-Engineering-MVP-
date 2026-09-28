from uuid import UUID

from .db import connection


async def search_entities(q: str, entity_type: str | None, limit: int = 25):
    normalized = " ".join(q.lower().split())
    params = {"q": normalized, "limit": limit, "entity_type": entity_type}
    type_clause = "AND entity_type = %(entity_type)s" if entity_type else ""
    sql = f"""
        SELECT id, entity_type, canonical_name, jurisdiction_code, status,
               similarity(normalized_name, %(q)s) AS similarity
        FROM entities
        WHERE (normalized_name %% %(q)s OR normalized_name LIKE '%%' || %(q)s || '%%')
          {type_clause}
        ORDER BY similarity DESC, canonical_name
        LIMIT %(limit)s
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def get_entity(entity_id: UUID):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, entity_type, canonical_name, jurisdiction_code, status FROM entities WHERE id=%s",
                (entity_id,),
            )
            entity = await cur.fetchone()
            if not entity:
                return None
            await cur.execute(
                """SELECT scheme, identifier_value, country_code, verified
                   FROM entity_identifiers WHERE entity_id=%s ORDER BY scheme, identifier_value""",
                (entity_id,),
            )
            entity["identifiers"] = await cur.fetchall()
            return entity
