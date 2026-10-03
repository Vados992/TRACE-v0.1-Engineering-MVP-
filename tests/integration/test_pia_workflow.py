"""Run against a disposable migrated DB; never a database containing real people."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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


def database_clock():
    from app.settings import settings

    with psycopg.connect(settings.database_url) as conn:
        return conn.execute("SELECT clock_timestamp()").fetchone()[0]


def temporal_import(client):
    payload = fixture("roles")
    suffix = str(uuid4())
    payload["dataset_id"] = "temporal-test:" + suffix
    for entity in payload["payload"]["entities"]:
        entity["identifier"] += suffix
        entity["name"] += suffix
    before = database_clock()
    response = client.post("/api/internal/imports", headers=auth("analyst"), json=payload)
    assert response.status_code == 200, response.text
    return before, response.json()


def historical_path(client, imported, known_at=None, verified=False):
    body = {
        "source_entity_id": imported["entity_ids"]["official"],
        "target_entity_id": imported["entity_ids"]["city"],
        "from_time": "2025-06-01T00:00:00Z",
        "to_time": "2025-06-01T00:00:00Z",
        "verified_only": verified,
    }
    if known_at:
        body["known_at"] = known_at.isoformat()
    response = client.post("/api/v1/graph/path", headers=auth("analyst"), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_late_valid_fact_is_not_earlier_knowledge(client):
    before, imported = temporal_import(client)
    assert historical_path(client, imported, before)["paths"] == []
    current = historical_path(client, imported)
    assert len(current["paths"]) == 1
    assert current["paths"][0]["edges"][0]["known_from"]
    entity = imported["entity_ids"]["official"]
    self_path = client.post(
        "/api/v1/graph/path",
        headers=auth("analyst"),
        json={
            "source_entity_id": entity,
            "target_entity_id": entity,
            "known_at": before.isoformat(),
        },
    )
    assert self_path.status_code == 200 and self_path.json()["paths"] == []
    assert (
        client.get(
            f"/api/v1/entities/{entity}",
            params={"known_at": before.isoformat()},
            headers=auth("analyst"),
        ).status_code
        == 404
    )
    why = client.get(
        "/api/v1/relationships/" + imported["relationship_ids"][0] + "/why",
        params={"known_at": before.isoformat()},
        headers=auth("analyst"),
    )
    assert why.status_code == 404


def test_backdated_correction_preserves_old_valid_interval_and_identity(client):
    from app.settings import settings

    _, imported = temporal_import(client)
    before = database_clock()
    relation, person = imported["relationship_ids"][0], imported["entity_ids"]["official"]
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "UPDATE entities SET canonical_name='Corrected synthetic identity' WHERE id=%s",
            (person,),
        )
    correction = client.post(
        f"/api/internal/relationships/{relation}/correct",
        headers=auth("reviewer"),
        json={
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2025-01-01T00:00:00Z",
            "source_record_id": imported["source_record_id"],
            "note": "Synthetic fixture documents a backdated end of this role",
        },
    )
    assert correction.status_code == 200 and correction.json()["history_preserved"] is True
    assert historical_path(client, imported)["paths"] == []
    old = historical_path(client, imported, before)
    assert len(old["paths"]) == 1 and old["paths"][0]["edges"][0]["valid_to"] is None
    entity = client.get(
        f"/api/v1/entities/{person}",
        params={"known_at": before.isoformat()},
        headers=auth("analyst"),
    ).json()
    assert entity["canonical_name"].startswith("Demo Official")
    investigation = client.post(
        "/api/v1/investigations",
        headers=auth("analyst"),
        json={
            "source_entity_id": person,
            "target_entity_id": imported["entity_ids"]["city"],
            "known_at": before.isoformat(),
            "verified_only": False,
        },
    )
    assert investigation.status_code == 200, investigation.text
    assert investigation.json()["source_entity"]["canonical_name"] == entity["canonical_name"]
    saved = client.get(
        "/api/v1/investigations/" + investigation.json()["investigation_id"],
        headers=auth("analyst"),
    ).json()
    assert datetime.fromisoformat(saved["known_at"]) == datetime.fromisoformat(
        investigation.json()["known_at"]
    )


def test_review_retraction_and_supersession_do_not_rewrite_past(client):
    from app.settings import settings

    _, imported = temporal_import(client)
    initial = database_clock()
    claim, relation = imported["claim_ids"][0], imported["relationship_ids"][0]
    assert historical_path(client, imported, initial, verified=True)["paths"] == []
    # Synthetic verification is intentionally unavailable via API. Only the disposable test owner
    # sets this status to exercise the historical status filter; no real-world truth is claimed.
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "UPDATE claims SET verification_status='VERIFIED_PRIMARY' WHERE id=%s", (claim,)
        )
    verified = database_clock()
    assert historical_path(client, imported, verified, verified=True)["paths"]
    assert historical_path(client, imported, initial, verified=True)["paths"] == []
    response = client.post(
        f"/api/internal/claims/{claim}/review",
        headers=auth("reviewer"),
        json={
            "status": "RETRACTED",
            "note": "Later synthetic evidence invalidates this test assertion",
        },
    )
    assert response.status_code == 200, response.text
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "UPDATE relationships SET superseded_at=clock_timestamp(),relationship_status='SUPERSEDED' WHERE id=%s",
            (relation,),
        )
    assert historical_path(client, imported)["paths"] == []
    assert historical_path(client, imported, verified, verified=True)["paths"]
    detail = client.get(
        f"/api/internal/claims/{claim}",
        params={"known_at": verified.isoformat()},
        headers=auth("analyst"),
    ).json()
    assert detail["claim"]["verification_status"] == "VERIFIED_PRIMARY"
    with psycopg.connect(settings.database_url) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute("DELETE FROM temporal_versions WHERE record_id=%s", (relation,))


def test_later_observation_and_evidence_do_not_leak_into_old_why(client):
    from app.settings import settings

    _, imported = temporal_import(client)
    before = database_clock()
    relation = imported["relationship_ids"][0]
    claim = imported["claim_ids"][0]
    with psycopg.connect(settings.database_url) as conn:
        source = conn.execute(
            "SELECT source_id FROM source_records WHERE id=%s", (imported["source_record_id"],)
        ).fetchone()[0]
        record = conn.execute(
            "INSERT INTO source_records(source_id,external_id,payload_uri,payload_hash,parser_version) VALUES (%s,%s,'fixture://later','later-test-hash','test') RETURNING id",
            (source, str(uuid4())),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO claim_evidence(claim_id,source_record_id,extraction_method,evidence_strength) VALUES (%s,%s,'later-fixture','E0')",
            (claim, record),
        )
        conn.execute(
            "INSERT INTO relationship_observations(source_id,source_record_id,canonical_relationship_id,subject_entity_id,relationship_type,object_entity_id,valid_from,semantic_key) SELECT %s,%s,id,subject_entity_id,relationship_type,object_entity_id,valid_from,%s FROM relationships WHERE id=%s",
            (source, record, str(uuid4()), relation),
        )
    old = client.get(
        f"/api/v1/relationships/{relation}/why",
        params={"known_at": before.isoformat()},
        headers=auth("analyst"),
    ).json()
    latest = client.get(f"/api/v1/relationships/{relation}/why", headers=auth("analyst")).json()
    assert len(old["source_observations"]) == 1 and len(latest["source_observations"]) == 2
    assert (
        len(old["canonical_claim_evidence"]) == 1 and len(latest["canonical_claim_evidence"]) == 2
    )
    assert historical_path(client, imported, before)["paths"][0]["supporting_observations"] == 1


def test_transaction_start_is_not_knowledge_time(client):
    from app.settings import settings

    _, imported = temporal_import(client)
    person = str(uuid4())
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "INSERT INTO entities(id,entity_type,canonical_name,normalized_name,is_demo) VALUES (%s,'PERSON','Atomic synthetic fixture','atomic synthetic fixture',true)",
            (person,),
        )
        claim = conn.execute(
            "INSERT INTO claims(subject_entity_id,predicate,object_entity_id,valid_from,claim_type,verification_status) VALUES (%s,'OWNS',%s,'2024-01-01','FACT','UNVERIFIED') RETURNING id",
            (person, imported["entity_ids"]["city"]),
        ).fetchone()[0]
        observed = conn.execute(
            "INSERT INTO relationships(subject_entity_id,relationship_type,object_entity_id,valid_from,claim_id) VALUES (%s,'OWNS',%s,'2024-01-01',%s) RETURNING observed_at",
            (person, imported["entity_ids"]["city"], claim),
        ).fetchone()[0]
        before_commit = database_clock()
        assert observed < before_commit
    imported["entity_ids"]["official"] = person
    assert historical_path(client, imported, before_commit)["paths"] == []
    assert len(historical_path(client, imported)["paths"]) == 1


def test_restored_cluster_transaction_collision_does_not_backdate_new_facts(client):
    from app.settings import settings

    _, imported = temporal_import(client)
    person = str(uuid4())
    before = database_clock()
    with psycopg.connect(settings.database_url) as conn:
        transaction = conn.execute("SELECT pg_current_xact_id()::text").fetchone()[0]
        # A logical restore can carry an old receipt with the same XID as a new write.
        # This is confined to the disposable fixture database, never live evidence.
        conn.execute(
            "INSERT INTO temporal_commits(transaction_id,committed_at,cluster_id) VALUES (%s::xid8,'2010-01-01',%s)",
            (transaction, "isolated-foreign-cluster:" + str(uuid4())),
        )
        conn.execute(
            "INSERT INTO entities(id,entity_type,canonical_name,normalized_name,is_demo) VALUES (%s,'PERSON','Restore collision fixture','restore collision fixture',true)",
            (person,),
        )
        claim = conn.execute(
            "INSERT INTO claims(subject_entity_id,predicate,object_entity_id,valid_from,claim_type,verification_status) VALUES (%s,'OWNS',%s,'2024-01-01','FACT','UNVERIFIED') RETURNING id",
            (person, imported["entity_ids"]["city"]),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO relationships(subject_entity_id,relationship_type,object_entity_id,valid_from,claim_id) VALUES (%s,'OWNS',%s,'2024-01-01',%s)",
            (person, imported["entity_ids"]["city"], claim),
        )
    imported["entity_ids"]["official"] = person
    assert historical_path(client, imported, before)["paths"] == []
    assert len(historical_path(client, imported)["paths"]) == 1
    with psycopg.connect(settings.database_url) as conn:
        receipts = conn.execute(
            "SELECT cluster_id,committed_at FROM temporal_commits WHERE transaction_id=%s::xid8",
            (transaction,),
        ).fetchall()
        cluster = conn.execute("SELECT trace_cluster_identity()").fetchone()[0]
    assert len(receipts) == 2
    assert next(stamp for identity, stamp in receipts if identity == cluster) > before


def test_unavailable_future_and_naive_knowledge_cutoffs_are_rejected(client):
    from datetime import timedelta

    _, imported = temporal_import(client)
    body = {
        "source_entity_id": imported["entity_ids"]["official"],
        "target_entity_id": imported["entity_ids"]["city"],
    }
    body["known_at"] = "2010-01-01T00:00:00Z"
    response = client.post("/api/v1/graph/path", headers=auth("analyst"), json=body)
    assert (
        response.status_code == 409 and response.json()["detail"]["code"] == "HISTORY_UNAVAILABLE"
    )
    body["known_at"] = (database_clock() + timedelta(days=1)).isoformat()
    assert client.post("/api/v1/graph/path", headers=auth("analyst"), json=body).status_code == 422
    body["known_at"] = "2026-01-01T00:00:00"
    assert client.post("/api/v1/graph/path", headers=auth("analyst"), json=body).status_code == 422


def test_conflict_scan_excludes_information_disclosed_later(client):
    for name in ["ocds", "bods", "roles", "ppds"]:
        response = client.post("/api/internal/imports", headers=auth("analyst"), json=fixture(name))
        assert response.status_code == 200, response.text
    before = database_clock()
    old = client.post(
        "/api/internal/conflicts/scan",
        params={"known_at": before.isoformat(), "include_demo": "true"},
        headers=auth("analyst"),
    )
    assert old.status_code == 200, old.text
    disclosed = fixture("roles")
    disclosed["dataset_id"] = "later-disclosure:" + str(uuid4())
    disclosed["payload"]["relationships"][0]["valid_from"] = (
        "2025-01-01T00:00:00." + f"{uuid4().int % 1000000:06d}" + "Z"
    )
    response = client.post("/api/internal/imports", headers=auth("analyst"), json=disclosed)
    assert response.status_code == 200, response.text
    current = client.post("/api/internal/conflicts/scan?include_demo=true", headers=auth("analyst"))
    assert current.status_code == 200 and current.json()["count"] > old.json()["count"]
    repeated = client.post(
        "/api/internal/conflicts/scan",
        params={"known_at": before.isoformat(), "include_demo": "true"},
        headers=auth("analyst"),
    )
    assert repeated.json()["count"] == old.json()["count"]


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
