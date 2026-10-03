import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..settings import settings


class ConnectorError(RuntimeError):
    pass


class BaseConnector:
    source_code: str

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.responses = []
        self.max_response_bytes = None
        self.capture_responses = True

    @staticmethod
    async def validate_url(url):
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ConnectorError(
                "External connectors require an HTTPS URL without embedded credentials"
            )
        if parsed.port not in (None, 443):
            raise ConnectorError("External connectors require port 443")
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo, parsed.hostname, 443, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise ConnectorError("External source DNS lookup failed") from exc
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ConnectorError(
                "External connectors cannot access private or reserved network addresses"
            )

    async def _raw_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        timeout = httpx.Timeout(self.timeout)
        await self.validate_url(url)
        # No silent retry of non-idempotent upstream POSTs. Operators can replay bounded jobs.
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client:
            for hop in range(6):
                await self.validate_url(url)
                async with client.stream(method, url, **kwargs) as response:
                    if response.is_redirect:
                        target = urljoin(str(response.url), response.headers.get("location", ""))
                        # Cellar publishes same-host http URI redirects. Fetch the HTTPS equivalent,
                        # never downgrade transport and never upgrade an unrelated destination implicitly.
                        parsed_target = urlsplit(target)
                        if (
                            parsed_target.scheme == "http"
                            and parsed_target.hostname == urlsplit(str(response.url)).hostname
                        ):
                            target = parsed_target._replace(scheme="https").geturl()
                        if hop == 5 or method != "GET":
                            raise ConnectorError("Unsupported upstream redirect")
                        if kwargs.get("auth") or any(
                            k.lower() == "authorization" for k in kwargs.get("headers", {})
                        ):
                            raise ConnectorError("Credentialed upstream redirects are forbidden")
                        url = target
                        kwargs.pop("params", None)
                        continue
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > (
                            self.max_response_bytes or settings.http_max_response_bytes
                        ):
                            raise ConnectorError("External response exceeds configured byte limit")
                    loaded = httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=bytes(content),
                        request=response.request,
                    )
                    break
        # Exact response bytes are retained inside the private evidence envelope for mapped datasets.
        if self.capture_responses:
            self.responses.append(
                {
                    "url": str(loaded.request.url),
                    "retrieved_at": self.now().isoformat(),
                    "status": loaded.status_code,
                    "content_range": loaded.headers.get("content-range"),
                    "sha256": self.sha256_bytes(loaded.content),
                    "body_base64": base64.b64encode(loaded.content).decode(),
                }
            )
        return loaded

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        response = await self._raw_request(method, url, **kwargs)
        if response.status_code >= 400:
            raise ConnectorError(f"{self.source_code} returned HTTP {response.status_code}")
        return response

    async def request_optional(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        response = await self._raw_request(method, url, **kwargs)
        if response.status_code in {404, 410}:
            return None
        if response.status_code >= 400:
            raise ConnectorError(f"{self.source_code} returned HTTP {response.status_code}")
        return response

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def stable_json_hash(payload: Any) -> str:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(raw).hexdigest()
