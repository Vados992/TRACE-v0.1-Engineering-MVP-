from psycopg.types.json import Jsonb


async def record(conn, actor: str, action: str, resource: str, details: dict | None = None):
    # DB trigger serializes and chains events. Bodies, credentials and source secrets are excluded.
    await conn.execute(
        "INSERT INTO audit_events(actor,action,resource,details) VALUES (%s,%s,%s,%s)",
        (actor, action, resource, Jsonb(details or {})),
    )
