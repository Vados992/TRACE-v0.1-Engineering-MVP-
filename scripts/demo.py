"""Offline end-to-end scenario. No request is made to an external registry."""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def run(client):
    results = {}
    for name in ["ocds", "bods", "roles", "ppds"]:
        payload = json.loads(
            (ROOT / "fixtures" / "demo" / f"{name}.json").read_text(encoding="utf-8")
        )
        response = client.post("/api/internal/imports", json=payload)
        response.raise_for_status()
        results[name] = response.json()
    official = results["bods"]["entity_ids"]["person-1"]
    supplier = results["bods"]["entity_ids"]["company-1"]
    city = results["roles"]["entity_ids"]["city"]
    path = client.post(
        "/api/v1/graph/path",
        json={
            "source_entity_id": official,
            "target_entity_id": supplier,
            "max_depth": 4,
            "verified_only": False,
            "from_time": "2025-06-01T00:00:00Z",
            "to_time": "2025-06-01T00:00:00Z",
        },
    )
    path.raise_for_status()
    assert path.json()["paths"], "Synthetic evidence path missing"
    wealth = json.loads((ROOT / "fixtures" / "demo" / "wealth.json").read_text(encoding="utf-8"))
    wealth["entity_id"] = official
    bridge = client.post("/api/internal/wealth/reconcile", json=wealth)
    bridge.raise_for_status()
    assert bridge.json()["status"] == "REVIEW_REQUIRED"
    assert bridge.json()["residual"] == "50000.00"
    scan = client.post("/api/internal/conflicts/scan?include_demo=true", json={})
    scan.raise_for_status()
    assert scan.json()["count"] >= 1
    return {
        "demo": True,
        "person_id": official,
        "supplier_id": supplier,
        "city_id": city,
        "imports": results,
        "path_count": len(path.json()["paths"]),
        "wealth": bridge.json(),
        "conflicts": scan.json(),
    }


if __name__ == "__main__":
    with httpx.Client(
        base_url=os.getenv("TRACE_API_URL", "http://127.0.0.1:8000"),
        timeout=45,
        headers={
            "Authorization": "Bearer " + os.getenv("TRACE_API_TOKEN", "trace-dev-analyst-only")
        },
    ) as client:
        print(json.dumps(run(client), indent=2))
