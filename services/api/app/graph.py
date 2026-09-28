from neo4j import AsyncGraphDatabase

from .settings import settings


class GraphService:
    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    async def close(self):
        await self.driver.close()

    async def find_paths(self, source_id: str, target_id: str, max_depth: int = 6, limit: int = 10):
        # Relationship type is stored as a property on generic RELATED edges.
        # A generic edge avoids unsafe dynamic Cypher relationship interpolation.
        depth = max(1, min(max_depth, 8))
        query = f"""
        MATCH p=(a:Entity {{id: $source_id}})-[:RELATED*1..{depth}]-(b:Entity {{id: $target_id}})
        WHERE ALL(r IN relationships(p) WHERE coalesce(r.superseded_at, '') = '')
        RETURN [n IN nodes(p) | {{id:n.id, name:n.name, type:n.type}}] AS nodes,
               [r IN relationships(p) | {{id:r.id, type:r.relationship_type,
                    verification_status:r.verification_status,
                    valid_from:r.valid_from, valid_to:r.valid_to}}] AS edges,
               length(p) AS hops
        ORDER BY hops ASC
        LIMIT $limit
        """
        async with self.driver.session() as session:
            result = await session.run(query, source_id=source_id, target_id=target_id, limit=limit)
            return [record.data() async for record in result]
