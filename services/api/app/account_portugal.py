"""Portuguese Portal BASE / IMPIC official open-data snapshot connector.

Discovers resources from dados.gov.pt; a resource has to pass an explicit
publisher-host allowlist and size bound. No invented payment records and no
inferred liability. Snapshots are immutable and source-addressed.

Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

DATASET_SLUG = "contratos-publicos-portal-base-impic-contratos-de-2012-a-2026"
CATALOG_URL = f"https://dados.gov.pt/api/1/datasets/{DATASET_SLUG}/"
MAX_CATALOG_BYTES = 2_000_000
MAX_RESOURCE_BYTES = 16_000_000
MAX_RECORDS = 10_000
ALLOWED_RESOURCE_HOSTS = frozenset({
    "dados.gov.pt", "www.base.gov.pt", "base.gov.pt", "www.impic.pt", "impic.pt",
})


class PortugalSourceError(ValueError):
    """Official source unavailable, unsafe or not in the documented schema."""


@dataclass(frozen=True)
class Snapshot:
    kind: str
    url: str
    content: bytes
    media_format: str
    dataset_slug: str = DATASET_SLUG

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Resource:
    id: str
    url: str
    title: str
    media_format: str
    published_size: int | None


def validate_official_url(url: str, *, catalog: bool = False) -> str:
    u = urlsplit(url)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.port or u.fragment or len(url) > 2048
            or any(ord(x) < 32 for x in url)):
        raise PortugalSourceError("Official source must be a plain HTTPS URL")
    try:
        ipaddress.ip_address(u.hostname)
    except ValueError:
        pass
    else:
        raise PortugalSourceError("IP-address resource URLs are not allowed")
    if catalog and url != CATALOG_URL:
        raise PortugalSourceError("Unexpected official catalog URL")
    if not catalog and u.hostname.lower() not in ALLOWED_RESOURCE_HOSTS:
        raise PortugalSourceError("Resource host has not been explicitly approved")
    return url


def resource_options(payload: dict) -> list[Resource]:
    if not isinstance(payload, dict) or not isinstance(payload.get("resources"), list):
        raise PortugalSourceError("Unexpected Portuguese government dataset schema")
    if payload.get("slug") and payload["slug"] != DATASET_SLUG:
        raise PortugalSourceError("Dataset slug mismatch")
    options = []
    for row in payload["resources"]:
        if not isinstance(row, dict):
            continue
        media = str(row.get("format") or "").strip().lower().lstrip(".")
        if media not in {"json", "csv"}:
            continue
        url = row.get("url")
        if not isinstance(url, str):
            continue
        try:
            validate_official_url(url)
        except PortugalSourceError:
            continue
        size = row.get("filesize", row.get("size"))
        # Only explicit non-negative integer size is trusted as metadata.
        size = size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None
        options.append(Resource(
            id=str(row.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20]),
            url=url, title=str(row.get("title") or "")[:250],
            media_format=media, published_size=size,
        ))
    return options


def decode_records(snapshot: Snapshot) -> list[dict]:
    """Bounded raw records; preserve unknown fields without inventing semantics."""
    if len(snapshot.content) > MAX_RESOURCE_BYTES:
        raise PortugalSourceError("Official resource exceeds bounded ingest limit")
    if snapshot.media_format == "json":
        try:
            obj = json.loads(snapshot.content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PortugalSourceError("Invalid official JSON") from exc
        if isinstance(obj, list):
            rows = obj
        elif isinstance(obj, dict):
            rows = next((obj[key] for key in ("data", "contratos", "records", "items")
                         if isinstance(obj.get(key), list)), None)
            if rows is None:
                raise PortugalSourceError("JSON resource does not contain a recognized record array")
        else:
            raise PortugalSourceError("JSON resource must contain a record collection")
    elif snapshot.media_format == "csv":
        import csv
        import io
        try:
            raw = snapshot.content.decode("utf-8-sig")
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t")
            reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
            rows = []
            for row in reader:
                if len(rows) >= MAX_RECORDS:
                    raise PortugalSourceError("Too many rows; require partitioned ingestion")
                rows.append(row)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise PortugalSourceError("Invalid official CSV") from exc
    else:
        raise PortugalSourceError("Unsupported resource format")
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise PortugalSourceError("Record count exceeds safe bound")
    if any(not isinstance(row, dict) for row in rows):
        raise PortugalSourceError("Malformed record (expected object)")
    return rows


def row_fingerprint(row: dict) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_key(row: dict, fallback_hash: str) -> str:
    # Identifier is only scoped to an import, not proof of cross-dataset identity.
    for key in ("idContrato", "IdContrato", "IDContrato", "id_contrato", "id"):
        v = row.get(key)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            return str(v)[:160]
    return "sha256:" + fallback_hash


class PortugalBaseClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def _get(self, url: str, limit: int, catalog: bool) -> bytes:
        validate_official_url(url, catalog=catalog)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0), follow_redirects=False, trust_env=False,
                transport=self.transport,
                headers={"Accept": "application/json, text/csv;q=0.8", "User-Agent": "TRACE-ACCOUNT/0.2 (+official-public-data)"},
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    size = 0
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise PortugalSourceError("Source exceeded maximum authorized snapshot size")
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError as exc:
            raise PortugalSourceError("Official source request failed (HTTP/transport)") from exc

    async def catalog(self) -> tuple[Snapshot, dict, list[Resource]]:
        blob = await self._get(CATALOG_URL, MAX_CATALOG_BYTES, catalog=True)
        try:
            payload = json.loads(blob)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PortugalSourceError("Official catalog returned non-JSON") from exc
        options = resource_options(payload)
        return Snapshot("catalog", CATALOG_URL, blob, "json"), payload, options

    async def resource(self, option: Resource) -> tuple[Snapshot, list[dict]]:
        if option.published_size is not None and option.published_size > MAX_RESOURCE_BYTES:
            raise PortugalSourceError("Resource exceeds safe size limit in official catalog")
        blob = await self._get(option.url, MAX_RESOURCE_BYTES, catalog=False)
        snap = Snapshot("contracts", option.url, blob, option.media_format)
        return snap, decode_records(snap)
