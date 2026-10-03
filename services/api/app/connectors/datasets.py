"""Real HTTPS dataset retrieval. Endpoint selection belongs to operator configuration."""

import json
import os
import re
import struct
import zlib

from .base import BaseConnector, ConnectorError


class OcdsConnector(BaseConnector):
    source_code = "OCDS"

    async def releases(self, limit=5):
        response = await self.request(
            "GET", self.base_url, params={"limit": limit}, headers={"Accept": "application/json"}
        )
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("releases"), list):
            raise ConnectorError("OCDS endpoint did not return a release package")
        return payload


class JsonDatasetConnector(BaseConnector):
    source_code = "CONFIGURED_DATASET"

    async def fetch(self, token_env=None):
        headers = {"Accept": "application/json"}
        if token_env:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", token_env):
                raise ConnectorError("Invalid configured credential variable")
            token = os.getenv(token_env)
            if not token:
                raise ConnectorError("Configured source requires credentials")
            headers["Authorization"] = "Bearer " + token
        return (await self.request("GET", self.base_url, headers=headers)).json()


class OpenOwnershipArchiveConnector(BaseConnector):
    """A bounded range of the actual publisher NDJSON ZIP. No whole-registry claim."""

    source_code = "OPENOWNERSHIP_ARCHIVE"

    @staticmethod
    def decode_prefix(raw, limit):
        if len(raw) < 30:
            raise ConnectorError("Truncated publisher ZIP header")
        header = struct.unpack("<IHHHHHIIIHH", raw[:30])
        signature, _, flags, method, _, _, _, _, _, name_length, extra_length = header
        offset = 30 + name_length + extra_length
        if signature != 0x04034B50 or method != 8 or flags & 1 or offset >= len(raw):
            raise ConnectorError("Unsupported publisher ZIP structure")
        # Hard bound prevents decompression bombs; only complete NDJSON statements are accepted.
        decompressed = zlib.decompressobj(-15).decompress(raw[offset:], 8 * 1024 * 1024)
        lines = decompressed.split(b"\n")
        statements = []
        for line in lines[:-1]:
            if not line.strip():
                continue
            try:
                statements.append(json.loads(line))
            except ValueError as exc:
                raise ConnectorError("Publisher NDJSON schema changed") from exc
            if len(statements) >= limit:
                break
        if not statements:
            raise ConnectorError("No complete statements in publisher range")
        return statements

    async def sample(self, limit=5):
        response = await self.request("GET", self.base_url, headers={"Range": "bytes=0-1048575"})
        if response.status_code != 206 or not response.headers.get("content-range", "").startswith(
            "bytes 0-"
        ):
            raise ConnectorError("Publisher must support bounded HTTP byte ranges")
        return {
            "statements": self.decode_prefix(response.content, limit * 20),
            "snapshot": "uk_version_0_4; publisher release 2025-03-11; bounded ZIP prefix, not complete/current registry",
            "content_range": response.headers["content-range"],
        }
