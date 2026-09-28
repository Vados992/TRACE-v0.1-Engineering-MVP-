from uuid import UUID

import pytest

import app.pathfinder as pathfinder


A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")
C = UUID("00000000-0000-0000-0000-000000000003")


@pytest.mark.asyncio
async def test_finds_two_hop_path(monkeypatch):
    edges = {
        A: [
            {
                "id": UUID("10000000-0000-0000-0000-000000000001"),
                "subject_entity_id": A,
                "object_entity_id": B,
                "relationship_type": "OWNS",
                "valid_from": None,
                "valid_to": None,
                "verification_status": "VERIFIED_PRIMARY",
                "claim_type": "FACT",
            }
        ],
        B: [
            {
                "id": UUID("10000000-0000-0000-0000-000000000001"),
                "subject_entity_id": A,
                "object_entity_id": B,
                "relationship_type": "OWNS",
                "valid_from": None,
                "valid_to": None,
                "verification_status": "VERIFIED_PRIMARY",
                "claim_type": "FACT",
            },
            {
                "id": UUID("10000000-0000-0000-0000-000000000002"),
                "subject_entity_id": B,
                "object_entity_id": C,
                "relationship_type": "RECEIVED_CONTRACT",
                "valid_from": None,
                "valid_to": None,
                "verification_status": "VERIFIED_PRIMARY",
                "claim_type": "FACT",
            },
        ],
    }

    async def fake_frontier(entity_ids, **kwargs):
        return edges.get(entity_ids[0], [])

    monkeypatch.setattr(pathfinder, "fetch_relationship_frontier", fake_frontier)
    paths = await pathfinder.find_paths(A, C, max_depth=3)
    assert len(paths) == 1
    assert paths[0]["hops"] == 2
    assert paths[0]["nodes"] == [str(A), str(B), str(C)]
