"""Small live initial dataset. No synthetic records or fabricated successful statuses."""

import json
from datetime import datetime, timedelta, timezone

import httpx


def main():
    sources = [
        ("GLEIF", "/api/v1/relationship-intelligence/ownership/gleif/529900T8BM49AURSDO55", None),
        (
            "TED",
            "/api/v1/relationship-intelligence/procurement/ted/search",
            {
                "query": "publication-date >= "
                + (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y%m%d"),
                "limit": 5,
            },
        ),
        ("EURLEX", "/api/v1/relationship-intelligence/policy/eurlex/32016R0679", None),
    ]
    results = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        for source, path, payload in sources:
            try:
                response = client.post(path, json=payload) if payload else client.post(path)
                response.raise_for_status()
                result = response.json()
                results.append({"source": source, "status": result["status"], "result": result})
            except Exception as exc:
                results.append({"source": source, "status": "FAILED", "error": type(exc).__name__})
    print(
        json.dumps(
            {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "sources": results,
                "lobbying": "Requires an official export in the documented import schema.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
