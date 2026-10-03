import os

import httpx
from dotenv import load_dotenv

load_dotenv()
base = os.getenv("TRACE_API_URL", "http://127.0.0.1:8000")
token = os.getenv("TRACE_API_TOKEN", "trace-dev-analyst-only")
with httpx.Client(base_url=base, timeout=15) as client:
    for path in ["/health", "/ready", "/public/", "/ui/", "/openapi.json", "/api/public/releases"]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
    assert client.get("/api/internal/cases").status_code == 401
    assert client.get("/api/v1/entities/search?q=Demo").status_code == 401
    client.headers["Authorization"] = "Bearer " + token
    assert client.get("/api/internal/me").status_code == 200
    print("Smoke passed: readiness, portals, OpenAPI, public boundary and authentication")
