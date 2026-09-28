from collections import deque
from datetime import datetime
from uuid import UUID

async def fetch_relationship_frontier(*args, **kwargs):
    from .path_repository import fetch_relationship_frontier as repository_frontier
    return await repository_frontier(*args, **kwargs)


def _edge_key(edge: dict) -> str:
    return str(edge["id"])


async def find_paths(
    source_id: UUID,
    target_id: UUID,
    *,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    max_depth: int = 6,
    limit: int = 10,
    verified_only: bool = True,
) -> list[dict]:
    if source_id == target_id:
        return [{"nodes": [str(source_id)], "edges": [], "hops": 0}]

    queue = deque([(source_id, [source_id], [])])
    paths: list[dict] = []
    expanded_depth: dict[UUID, int] = {source_id: 0}

    while queue and len(paths) < limit:
        current, nodes, edges = queue.popleft()
        depth = len(edges)
        if depth >= max_depth:
            continue

        rows = await fetch_relationship_frontier(
            [current],
            from_time=from_time,
            to_time=to_time,
            verified_only=verified_only,
        )
        used_edges = {_edge_key(edge) for edge in edges}
        for row in rows:
            if _edge_key(row) in used_edges:
                continue
            subject = row["subject_entity_id"]
            obj = row["object_entity_id"]
            next_id = obj if subject == current else subject
            if next_id in nodes:
                continue

            next_nodes = [*nodes, next_id]
            next_edges = [*edges, row]

            if next_id == target_id:
                paths.append(
                    {
                        "nodes": [str(x) for x in next_nodes],
                        "edges": [
                            {
                                "id": str(e["id"]),
                                "relationship_type": e["relationship_type"],
                                "subject_entity_id": str(e["subject_entity_id"]),
                                "object_entity_id": str(e["object_entity_id"]),
                                "valid_from": e["valid_from"].isoformat()
                                if e["valid_from"]
                                else None,
                                "valid_to": e["valid_to"].isoformat()
                                if e["valid_to"]
                                else None,
                                "verification_status": e["verification_status"],
                                "claim_type": e["claim_type"],
                            }
                            for e in next_edges
                        ],
                        "hops": len(next_edges),
                    }
                )
                if len(paths) >= limit:
                    break
                continue

            next_depth = depth + 1
            if expanded_depth.get(next_id, 999) < next_depth:
                continue
            expanded_depth[next_id] = next_depth
            queue.append((next_id, next_nodes, next_edges))

    return sorted(paths, key=lambda p: p["hops"])
