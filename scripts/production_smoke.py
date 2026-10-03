"""Verify the production-like private/public boundary without exporting credentials."""

import argparse
import json
from pathlib import Path

import httpx

tokens = json.loads(Path(".production-keys.json").read_text())
parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--public-url", default="http://127.0.0.1:8080")
args = parser.parse_args()
with httpx.Client(base_url=args.base_url, timeout=15) as client:
    assert client.get("/ready").status_code == 200
    assert client.get("/api/internal/me").status_code == 401
    assert (
        client.get(
            "/api/internal/me", headers={"Authorization": "Bearer trace-dev-analyst-only"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/internal/me", headers={"Authorization": "Bearer " + tokens["analyst"]}
        ).status_code
        == 200
    )
with httpx.Client(base_url=args.public_url, timeout=15, follow_redirects=True) as client:
    for path in [
        "/public/",
        "/public/public.js",
        "/ui/style.css",
        "/api/public/status",
        "/api/public/releases",
    ]:
        assert client.get(path).status_code == 200, path
    for path in [
        "/api/internal/me",
        "/api/v1/entities/search?q=any",
        "/ui/",
        "/docs",
        "/openapi.json",
    ]:
        assert client.get(path).status_code in (403, 404), path
    assert client.post("/api/public/releases", json={}).status_code in (403, 405)
print("Production-like smoke passed: random scoped credentials and public gateway allowlist")
