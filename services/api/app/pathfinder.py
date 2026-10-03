import time
from collections import deque
from datetime import datetime
from uuid import UUID

from .settings import settings


class GraphBudgetExceeded(ValueError):
    pass


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

    queue = deque([(source_id, [source_id], [], from_time, to_time)])
    paths: list[dict] = []
    frontier_cache = {}
    expanded = 0
    started = time.monotonic()

    while queue and len(paths) < limit:
        current, nodes, edges, common_from, common_to = queue.popleft()
        expanded += 1
        if (
            expanded > settings.graph_max_expansions
            or time.monotonic() - started > settings.graph_timeout_seconds
        ):
            raise GraphBudgetExceeded("Graph search budget exceeded; narrow the interval or depth")
        depth = len(edges)
        if depth >= max_depth:
            continue

        if current not in frontier_cache:
            frontier_cache[current] = await fetch_relationship_frontier(
                [current], from_time=from_time, to_time=to_time, verified_only=verified_only
            )
        rows = frontier_cache[current]
        if len(rows) > 1000:
            raise GraphBudgetExceeded("Frontier exceeds 1000 edges; narrow the query")
        used_edges = {_edge_key(edge) for edge in edges}
        for row in rows:
            if _edge_key(row) in used_edges:
                continue
            subject = row["subject_entity_id"]
            obj = row["object_entity_id"]
            next_id = obj if subject == current else subject
            if next_id in nodes:
                continue
            starts = [v for v in [common_from, row["valid_from"]] if v is not None]
            ends = [v for v in [common_to, row["valid_to"]] if v is not None]
            next_from, next_to = max(starts) if starts else None, min(ends) if ends else None
            if next_from and next_to and next_from > next_to:
                continue  # Edges must share a common interval, not merely match separately.

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
                                "valid_to": e["valid_to"].isoformat() if e["valid_to"] else None,
                                "verification_status": e["verification_status"],
                                "claim_type": e["claim_type"],
                                "observation_count": int(e.get("observation_count", 0) or 0),
                            }
                            for e in next_edges
                        ],
                        "hops": len(next_edges),
                        "common_valid_from": next_from.isoformat() if next_from else None,
                        "common_valid_to": next_to.isoformat() if next_to else None,
                        "temporal_uncertainty": any(
                            e["valid_from"] is None or e["valid_to"] is None for e in next_edges
                        ),
                        "traversal": "undirected connectivity; edge direction is retained",
                        "supporting_observations": sum(
                            int(e.get("observation_count", 0) or 0) for e in next_edges
                        ),
                    }
                )
                if len(paths) >= limit:
                    break
                continue

            queue.append((next_id, next_nodes, next_edges, next_from, next_to))
            if len(queue) > settings.graph_max_expansions:
                raise GraphBudgetExceeded("Graph queue budget exceeded; narrow the query")

    return sorted(paths, key=lambda p: (p["hops"], -p.get("supporting_observations", 0)))
