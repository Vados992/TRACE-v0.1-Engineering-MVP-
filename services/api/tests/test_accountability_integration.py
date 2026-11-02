"""PostgreSQL/API integration test; execute only on migrated disposable TRACE DB."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.main import app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_accountability_submission_replay_and_independent_review():
    sample = json.loads(
        (ROOT / "fixtures/accountability/kastoria_eca2014.json").read_text()
    )
    sample["project_id"] += "-" + uuid4().hex
    with TestClient(app) as client:
        missing = client.post("/api/internal/accountability/preview", json=sample)
        assert missing.status_code == 401
        analyst = {"Authorization": "Bearer trace-dev-analyst-only"}
        reviewer = {"Authorization": "Bearer trace-dev-reviewer-only"}
        preview = client.post("/api/internal/accountability/preview", json=sample, headers=analyst)
        assert preview.status_code == 200, preview.text
        assert preview.json()["metrics"]["operating_gap_amount"] == "7524000"
        first = client.post("/api/internal/accountability/submit", json=sample, headers=analyst)
        assert first.status_code == 201, first.text
        uid = first.json()["assessment_id"]
        replay = client.post("/api/internal/accountability/submit", json=sample, headers=analyst)
        assert replay.status_code == 201 and replay.json()["reused"] is True
        assert replay.json()["assessment_id"] == uid
        denied = client.post(f"/api/internal/accountability/assessments/{uid}/review",
                             headers=analyst,
                             json={"verdict": "NEEDS_INFORMATION",
                                   "note": "Source chain requires more evidence and review."})
        assert denied.status_code == 403
        reviewed = client.post(f"/api/internal/accountability/assessments/{uid}/review",
                               headers=reviewer,
                               json={"verdict": "NEEDS_INFORMATION",
                                     "note": "Source chain requires more evidence and review."})
        assert reviewed.status_code == 201, reviewed.text
        assert reviewed.json()["status"] == "reviewed_not_published"
        detail = client.get(f"/api/internal/accountability/assessments/{uid}", headers=reviewer)
        assert detail.status_code == 200 and len(detail.json()["reviews"]) >= 1
