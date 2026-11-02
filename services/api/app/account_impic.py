"""IMPIC BASE open-data snapshots. Evidence leads only; not payments or findings.

Source: https://dados.gov.pt/api/1/datasets/contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/
Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import httpx

DATASET_URL = (
    "https://dados.gov.pt/api/1/datasets/"
    "contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/"
)
TRUSTED_HOSTS = frozenset({"dados.gov.pt", "base.gov.pt", "www.base.gov.pt"})
DEFAULT_MAX_BYTES = 160 * 1024 * 1024
DEFAULT_MAX_UNPACKED = 240 * 1024 * 1024


class ImpicError(ValueError):
    """A download, schema, provenance or safety precondition is not met."""


def verified_url(url: str) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in TRUSTED_HOSTS
            or p.username or p.password or p.port or p.fragment
            or len(url) > 2048 or any(ord(c) < 32 for c in url)):
        raise ImpicError("Resource is outside the explicit official HTTPS allowlist")
    return url


def select_resource(metadata: dict, year: int) -> dict:
    if not 2012 <= year <= 2026:
        raise ImpicError("Year is outside the catalogued period (2012–2026)")
    org = metadata.get("organization") or {}
    if not isinstance(org, dict) or "impic" not in (
        str(org.get("name", "")) + " " + str(org.get("slug", ""))
    ).lower():
        raise ImpicError("Dataset publisher is not identified as IMPIC")
    resources = metadata.get("resources")
    if not isinstance(resources, list):
        raise ImpicError("Dataset has no resource manifest")
    candidates = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "")
        title = str(r.get("title") or r.get("name") or "")
        filename = urlsplit(url).path.rsplit("/", 1)[-1]
        # Do not mistake a dataset title like "2012-2026" for a 2026-only file.
        label = title + " " + filename
        year_file = re.search(rf"contrat[a-z_-]*[ _-]?{year}(?![0-9])", label.lower())
        fmt = str(r.get("format") or "").lower().lstrip(".")
        if (not year_file or fmt not in {"json", "zip"} or not url):
            continue
        verified_url(url)
        candidates.append(r)
    if not candidates:
        raise ImpicError("No explicit JSON/ZIP contracts resource found for requested year")
    # Prefer JSON and newest declared publication; never silently choose an arbitrary URL.
    candidates.sort(key=lambda r: (
        str(r.get("last_modified") or r.get("modified") or ""),
        str(r.get("format") or "").lower() == "json",
    ), reverse=True)
    return candidates[0]


async def bounded_get(client: httpx.AsyncClient, url: str, cap: int) -> bytes:
    verified_url(url)
    try:
        async with client.stream("GET", url, headers={"accept": "application/json, application/zip"}) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ImpicError("Redirects from official data endpoints are not permitted")
            size = 0
            data = io.BytesIO()
            async for block in response.aiter_bytes(chunk_size=65536):
                size += len(block)
                if size > cap:
                    raise ImpicError("Official resource exceeds configured byte limit")
                data.write(block)
            return data.getvalue()
    except httpx.HTTPError as exc:
        raise ImpicError("Official source request failed") from exc


def unpack_json(raw: bytes, fmt: str, max_unpacked: int = DEFAULT_MAX_UNPACKED) -> bytes:
    if fmt.lower().lstrip(".") == "json":
        return raw
    if fmt.lower().lstrip(".") != "zip":
        raise ImpicError("Only JSON or ZIP containing a single JSON file is supported")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [x for x in archive.infolist() if not x.is_dir()]
            if (len(entries) != 1 or not entries[0].filename.lower().endswith(".json")
                    or entries[0].file_size > max_unpacked):
                raise ImpicError("Archive must contain one bounded JSON file")
            if entries[0].compress_size and entries[0].file_size / entries[0].compress_size > 250:
                raise ImpicError("Excessive ZIP expansion ratio")
            with archive.open(entries[0]) as f:
                data = f.read(max_unpacked + 1)
            if len(data) > max_unpacked:
                raise ImpicError("Expanded JSON exceeds configured byte limit")
            return data
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ImpicError("Invalid compressed JSON resource") from exc


def parse_rows(data: bytes) -> list[dict]:
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ImpicError("Resource is not valid JSON") from exc
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next((payload[key] for key in ("contratos", "contracts", "records", "data")
                     if isinstance(payload.get(key), list)), None)
    else:
        rows = None
    if not isinstance(rows, list) or not rows:
        raise ImpicError("Unknown or empty contracts schema; no records will be imported")
    if not all(isinstance(r, dict) for r in rows):
        raise ImpicError("Contracts list includes non-object records")
    return rows


def money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ImpicError("Invalid boolean monetary value")
    v = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("€", "")
    if not re.fullmatch(r"[0-9.,]+", v):
        raise ImpicError("Unrecognized monetary format")
    if "," in v and "." in v:
        dec = "," if v.rfind(",") > v.rfind(".") else "."
        v = v.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in v:
        v = v.replace(",", ".") if len(v.split(",")[-1]) <= 2 else v.replace(",", "")
    elif "." in v and len(v.split(".")[-1]) == 3:
        v = v.replace(".", "")
    try:
        out = Decimal(v)
    except InvalidOperation as exc:
        raise ImpicError("Unparseable monetary value") from exc
    if out < 0 or out > Decimal("999999999999999999.99"):
        raise ImpicError("Out-of-range monetary value")
    return out.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Contract:
    contract_id: str
    title: str
    price_eur: Decimal | None
    record_sha256: str


def contract_from_row(record: dict) -> Contract:
    cid = next((record[k] for k in ("idContrato", "IdContrato", "id_contrato", "contract_id")
                if record.get(k) is not None), None)
    title = next((record[k] for k in ("objectoContrato", "objetoContrato", "objeto", "objecto", "title")
                  if isinstance(record.get(k), str) and record[k].strip()), None)
    if not cid or not title or len(str(cid)) > 150 or len(title) > 1500:
        raise ImpicError("Contract requires a bounded official ID and title")
    value = next((record[k] for k in ("precoContratual", "precoContrato", "valorContrato", "contractPrice")
                  if record.get(k) is not None), None)
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Contract(str(cid), title, money(value), hashlib.sha256(raw.encode()).hexdigest())


@dataclass(frozen=True)
class Snapshot:
    dataset_url: str
    resource_url: str
    year: int
    raw_sha256: str
    raw: bytes
    contracts: list[Contract]
    invalid_count: int
    rows_total: int


async def fetch_snapshot(year: int, transport: httpx.AsyncBaseTransport | None = None,
                         max_bytes: int = DEFAULT_MAX_BYTES) -> Snapshot:
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False,
                                 timeout=httpx.Timeout(60.0), transport=transport) as client:
        metadata = json.loads(await bounded_get(client, DATASET_URL, 2 * 1024 * 1024))
        if not isinstance(metadata, dict):
            raise ImpicError("Metadata is not an object")
        resource = select_resource(metadata, year)
        url = verified_url(resource["url"])
        raw = await bounded_get(client, url, max_bytes)
    rows = parse_rows(unpack_json(raw, str(resource["format"])))
    unique: dict[str, Contract] = {}
    invalid = 0
    for row in rows:
        try:
            contract = contract_from_row(row)
            previous = unique.get(contract.contract_id)
            if previous and previous.record_sha256 != contract.record_sha256:
                raise ImpicError("Conflicting records for the same official contract ID")
            unique[contract.contract_id] = contract
        except ImpicError as exc:
            if "Conflicting records" in str(exc):
                raise
            invalid += 1
    if not unique:
        raise ImpicError("No usable contracts; source schema requires manual review")
    return Snapshot(DATASET_URL, url, year, hashlib.sha256(raw).hexdigest(), raw,
                    list(unique.values()), invalid, len(rows))


async def persist_snapshot(conn, snap: Snapshot, artifact_dir: Path) -> dict:
    """Write content-addressed source bytes then commit rows together in one DB transaction.

    conn is a real psycopg async connection. Never infer payments from contract price.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / (snap.raw_sha256 + ".source")
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != snap.raw_sha256:
            raise ImpicError("Local evidence artifact hash does not match recorded digest")
    else:
        temp = artifact_dir / (snap.raw_sha256 + ".partial")
        try:
            with temp.open("xb") as file:
                file.write(snap.raw)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    async with conn.transaction():
        result = await (await conn.execute(
            """INSERT INTO account_impic_snapshots
               (dataset_url,resource_url,year,raw_sha256,artifact_path,rows_total,
                imported_count,invalid_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(raw_sha256) DO NOTHING RETURNING id""",
            (snap.dataset_url, snap.resource_url, snap.year, snap.raw_sha256,
             str(target), snap.rows_total, len(snap.contracts), snap.invalid_count),
        )).fetchone()
        if result is None:
            old = await (await conn.execute(
                "SELECT id,imported_count FROM account_impic_snapshots WHERE raw_sha256=%s",
                (snap.raw_sha256,),
            )).fetchone()
            return {"snapshot_id": str(old["id"]), "reused": True,
                    "imported": old["imported_count"]}
        snapshot_id = result["id"]
        values = [(snapshot_id, c.contract_id, c.title, c.price_eur, c.record_sha256)
                  for c in snap.contracts]
        async with conn.cursor() as cur:
            for offset in range(0, len(values), 1000):
                await cur.executemany(
                    """INSERT INTO account_impic_contracts
                       (snapshot_id,contract_id,title,contract_price_eur,record_sha256)
                       VALUES (%s,%s,%s,%s,%s)""", values[offset:offset + 1000],
                )
        from . import audit
        await audit.record(conn, "impic-automated-ingest", "IMPIC_SNAPSHOT_IMPORTED",
                           str(snapshot_id), {"sha256": snap.raw_sha256,
                                              "rows_total": snap.rows_total,
                                              "imported": len(values),
                                              "invalid": snap.invalid_count})
    return {"snapshot_id": str(snapshot_id), "reused": False,
            "imported": len(snap.contracts), "invalid": snap.invalid_count}
