import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import httpx


class ConnectorError(RuntimeError):
    pass


class BaseConnector:
    source_code: str

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _raw_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await client.request(method, url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        response = await self._raw_request(method, url, **kwargs)
        if response.status_code >= 400:
            raise ConnectorError(
                f"{self.source_code} returned HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    async def request_optional(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        response = await self._raw_request(method, url, **kwargs)
        if response.status_code in {404, 410}:
            return None
        if response.status_code >= 400:
            raise ConnectorError(
                f"{self.source_code} returned HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def stable_json_hash(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()
