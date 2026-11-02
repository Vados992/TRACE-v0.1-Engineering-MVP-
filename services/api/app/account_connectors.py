"""Read-only authenticated EVIDENCE-X metadata bridge; no cross-database writes.

Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.
"""
from urllib.parse import urlsplit

import httpx

from .account_engine import EvidenceRef, from_evidence_x_source


class EvidenceXUnavailable(Exception):
    """Configuration or bounded remote request failed. No secrets in message."""


class EvidenceXClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        u = urlsplit(base_url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.port or u.path.strip("/") or u.query or u.fragment):
            raise EvidenceXUnavailable("EVIDENCE-X HTTPS service URL is missing or invalid")
        if not api_key or len(api_key) > 2048:
            raise EvidenceXUnavailable("EVIDENCE-X service credential is not configured")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def list_sources(self, limit: int = 100) -> list[EvidenceRef]:
        if not 1 <= limit <= 100:
            raise ValueError("Source limit must be 1..100")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0), transport=self._transport,
                follow_redirects=False, trust_env=False,
            ) as client:
                response = await client.get(
                    self.base_url + "/sources",
                    headers={"x-evidence-key": self._api_key, "accept": "application/json"},
                )
                response.raise_for_status()
                if len(response.content) > 1_000_000:
                    raise EvidenceXUnavailable("EVIDENCE-X source list exceeds size limit")
                payload = response.json()
                if not isinstance(payload, list):
                    raise EvidenceXUnavailable("EVIDENCE-X returned unexpected source format")
                return [from_evidence_x_source(row, "EVIDENCE-X /sources " + str(row.get("id", "")))
                        for row in payload[:limit]]
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise EvidenceXUnavailable("EVIDENCE-X request or schema validation failed") from exc
