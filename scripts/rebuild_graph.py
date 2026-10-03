import asyncio
import os

import psycopg
from neo4j import AsyncGraphDatabase
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://trace:trace_dev_only@localhost:5432/trace"
)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "trace_graph_dev_only")


async def main() -> None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        entities = conn.execute(
            "SELECT id::text, entity_type, canonical_name FROM entities"
        ).fetchall()
        relationships = conn.execute(
            """SELECT r.id::text, r.subject_entity_id::text, r.object_entity_id::text,
                      r.relationship_type, r.valid_from::text, r.valid_to::text,
                      r.superseded_at::text, c.verification_status
               FROM relationships r
               LEFT JOIN claims c ON c.id=r.claim_id"""
        ).fetchall()

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        async with driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE"
            )
            await session.run("MATCH (n) DETACH DELETE n")
            if entities:
                await session.run(
                    """UNWIND $rows AS row
                       MERGE (e:Entity {id: row.id})
                       SET e.type=row.entity_type, e.name=row.canonical_name""",
                    rows=entities,
                )
            if relationships:
                await session.run(
                    """UNWIND $rows AS row
                       MATCH (a:Entity {id: row.subject_entity_id})
                       MATCH (b:Entity {id: row.object_entity_id})
                       MERGE (a)-[r:RELATED {id: row.id}]->(b)
                       SET r.relationship_type=row.relationship_type,
                           r.valid_from=row.valid_from,
                           r.valid_to=row.valid_to,
                           r.superseded_at=row.superseded_at,
                           r.verification_status=row.verification_status""",
                    rows=relationships,
                )
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
