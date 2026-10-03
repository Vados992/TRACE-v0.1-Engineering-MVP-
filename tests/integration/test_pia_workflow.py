"""Run against a disposable migrated DB; never a database containing real people."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("TRACE_INTEGRATION") != "1",
        reason="Set TRACE_INTEGRATION=1 and a disposable PostgreSQL DSN",
    ),
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client():
    from app.loop import selector_loop
    from app.main import app

    with TestClient(
        app, raise_server_exceptions=True, backend_options={"loop_factory": selector_loop}
    ) as client:
        yield client


def auth(role):
    return {"Authorization": f"Bearer trace-dev-{role}-only"}


def fixture(name):
    return json.loads((ROOT / "fixtures" / "demo" / f"{name}.json").read_text(encoding="utf-8"))


def test_full_workflow_and_public_boundary(client):
    assert client.get("/ready").status_code == 200
    assert client.get("/api/internal/cases").status_code == 401
    assert client.get("/api/v1/entities/search?q=demo").status_code == 401
    assert (
        client.post(
            "/api/internal/imports", headers=auth("publisher"), json=fixture("ocds")
        ).status_code
        == 403
    )
    imports = {}
    for name in ["ocds", "bods", "roles", "ppds"]:
        response = client.post("/api/internal/imports", headers=auth("analyst"), json=fixture(name))
        assert response.status_code == 200, response.text
        imports[name] = response.json()
    replay = client.post("/api/internal/imports", headers=auth("analyst"), json=fixture("ocds"))
    assert replay.json()["replayed"] is True
    assert replay.json()["claim_ids"] == imports["ocds"]["claim_ids"]
    person = imports["bods"]["entity_ids"]["person-1"]
    supplier = imports["bods"]["entity_ids"]["company-1"]
    assert supplier == imports["ocds"]["entity_ids"]["ocds-demo-001:party:supplier"]
    body = {
        "source_entity_id": person,
        "target_entity_id": supplier,
        "verified_only": False,
        "from_time": "2025-06-01T00:00:00Z",
        "to_time": "2025-06-01T00:00:00Z",
    }
    path = client.post("/api/v1/graph/path", headers=auth("analyst"), json=body)
    assert path.status_code == 200 and path.json()["paths"]
    body["verified_only"] = True
    assert (
        client.post("/api/v1/graph/path", headers=auth("analyst"), json=body).json()["paths"] == []
    )
    claim_id = imports["bods"]["claim_ids"][0]
    assert (
        client.post(
            f"/api/internal/claims/{claim_id}/review",
            headers=auth("reviewer"),
            json={"status": "VERIFIED_PRIMARY", "note": "Independent evidence validation"},
        ).status_code
        == 409
    )
    artifact = client.get(
        "/api/internal/evidence/" + imports["ocds"]["artifact_id"], headers=auth("analyst")
    )
    assert artifact.status_code == 200
    assert "X-Evidence-SHA256" in artifact.headers
    wealth = fixture("wealth")
    wealth["entity_id"] = person
    bridge = client.post("/api/internal/wealth/reconcile", headers=auth("analyst"), json=wealth)
    assert bridge.status_code == 200, bridge.text
    assert bridge.json()["residual"] == "50000.00"
    assert bridge.json()["status"] == "REVIEW_REQUIRED"
    wealth["gifts"] = None
    wealth["dataset_id"] += "-incomplete"
    incomplete = client.post("/api/internal/wealth/reconcile", headers=auth("analyst"), json=wealth)
    assert incomplete.json()["status"] == "INCOMPLETE" and incomplete.json()["residual"] is None
    scanned = client.post(
        "/api/internal/conflicts/scan?include_demo=true", headers=auth("analyst"), json={}
    )
    assert scanned.status_code == 200 and scanned.json()["count"] >= 1
    new_case = client.post(
        "/api/internal/cases",
        headers=auth("analyst"),
        json={
            "entity_id": person,
            "title": "Internal sensitive draft " + str(uuid4()),
            "reason": "Synthetic scenario for independent review",
            "claim_ids": [claim_id],
        },
    )
    assert new_case.status_code == 200, new_case.text
    case_id = new_case.json()["id"]
    actions = f"/api/internal/cases/{case_id}/actions"
    public_before = client.get("/api/public/releases").json()
    assert all(item["title"] != new_case.json()["title"] for item in public_before)
    assert (
        client.post(
            actions,
            headers=auth("analyst"),
            json={"action": "publish", "note": "Premature publication"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            actions,
            headers=auth("publisher"),
            json={"action": "publish", "note": "Premature publication"},
        ).status_code
        == 409
    )
    review = client.post(
        actions,
        headers=auth("reviewer"),
        json={
            "action": "review",
            "note": "Evidence checked and personal details removed",
            "public_title": "Synthetic demonstration " + case_id,
            "public_summary": "This is a synthetic example only. No real person is described.",
        },
    )
    assert review.status_code == 200, review.text
    publish = client.post(
        actions,
        headers=auth("publisher"),
        json={"action": "publish", "note": "Release of reviewed synthetic text"},
    )
    assert publish.status_code == 200
    public = client.get("/api/public/releases").json()
    published = next(item for item in public if item["title"].endswith(case_id))
    assert set(published) == {"id", "title", "summary", "published_at"}
    assert "Internal sensitive" not in json.dumps(public)
    assert (
        client.post(
            actions,
            headers=auth("analyst"),
            json={"action": "appeal", "note": "Correct source before further publication"},
        ).status_code
        == 200
    )
    assert all(item["id"] != published["id"] for item in client.get("/api/public/releases").json())
    audit = client.get("/api/internal/audit", headers=auth("reviewer")).json()
    assert any(row["action"] == "PUBLIC_RELEASE_CREATED" for row in audit)
    assert "trace-dev" not in json.dumps(audit)


def test_failed_import_is_atomic_and_recorded(client):
    payload = fixture("roles")
    payload["dataset_id"] = "invalid-type-" + str(uuid4())
    payload["payload"]["entities"][0]["entity_type"] = "ORGANIZATION"
    response = client.post("/api/internal/imports", headers=auth("analyst"), json=payload)
    assert response.status_code == 422
    imports = client.get("/api/internal/imports?include_demo=true", headers=auth("analyst")).json()
    assert (
        next(row for row in imports if row["dataset_id"] == payload["dataset_id"])["status"]
        == "FAILED"
    )


def test_evidence_tamper_is_rejected(client):
    from app.settings import settings

    imported = client.post(
        "/api/internal/imports", headers=auth("analyst"), json=fixture("roles")
    ).json()
    with psycopg.connect(settings.database_url) as conn:
        key = conn.execute(
            "SELECT object_key FROM raw_artifacts WHERE id=%s", (imported["artifact_id"],)
        ).fetchone()[0]
    target = Path(settings.evidence_directory) / key
    original = target.read_bytes()
    try:
        target.write_bytes(b"tampered")
        response = client.get(
            "/api/internal/evidence/" + imported["artifact_id"], headers=auth("reviewer")
        )
        assert response.status_code == 409
    finally:
        target.write_bytes(original)


def test_append_only_audit_and_chain(client):
    from app.settings import settings

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE audit_events SET actor=actor")
        with pytest.raises(psycopg.Error):
            conn.execute("TRUNCATE audit_events")
        rows = conn.execute("""SELECT id,previous_hash,event_hash,
            encode(digest(previous_hash || jsonb_build_array(id,occurred_at AT TIME ZONE 'UTC',actor,action,resource,details)::text,'sha256'),'hex')
            FROM audit_events ORDER BY id""").fetchall()
    previous = "0" * 64
    for _, prev, saved, calculated in rows:
        assert prev == previous and saved == calculated
        previous = saved
    assert rows


def test_concurrent_import_replay_and_live_separation(client):
    payload = fixture("roles")
    payload["dataset_id"] = "concurrent-" + str(uuid4())
    payload["payload"]["entities"][0]["identifier"] = payload["dataset_id"]
    payload["payload"]["entities"][0]["name"] = "SYNTHETIC CONCURRENT " + payload["dataset_id"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        replies = list(
            executor.map(
                lambda _: client.post(
                    "/api/internal/imports", headers=auth("analyst"), json=payload
                ),
                range(4),
            )
        )
    assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
    assert len({r.json()["batch_id"] for r in replies}) == 1
    assert sum(not r.json()["replayed"] for r in replies) == 1
    query = "/api/v1/entities/search?q=" + payload["dataset_id"]
    assert client.get(query, headers=auth("analyst")).json() == []
    assert client.get(query + "&include_demo=true", headers=auth("analyst")).json()
    person = replies[0].json()["entity_ids"]["official"]
    wealth = fixture("wealth")
    wealth["entity_id"] = person
    wealth["demo"] = False
    assert (
        client.post(
            "/api/internal/wealth/reconcile", headers=auth("analyst"), json=wealth
        ).status_code
        == 422
    )
