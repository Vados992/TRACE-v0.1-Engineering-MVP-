"""Readiness and inventory; availability does not imply an upstream refresh."""

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from neo4j import AsyncGraphDatabase

from .db import pool
from .object_store import EvidenceStore
from .settings import settings


async def database_check():
    async with pool.connection(timeout=4) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS count FROM schema_migrations")
            count = (await cur.fetchone())["count"]
            if count < 12:
                raise RuntimeError("missing migrations")
            await cur.execute("SHOW track_commit_timestamp")
            if (await cur.fetchone())["track_commit_timestamp"] != "on":
                raise RuntimeError("commit timestamp tracking disabled")
            await cur.execute("SELECT trace_finalize_temporal_commits()")
    return {"migrations": count}


async def evidence_check():
    await asyncio.to_thread(EvidenceStore().check)
    return {"backend": settings.evidence_backend}


async def redis_check():
    address = urlsplit(settings.redis_url)
    reader, writer = await asyncio.open_connection(address.hostname, address.port or 6379)
    try:
        writer.write(b"*1\r\n$4\r\nPING\r\n")
        await writer.drain()
        if (await reader.readline()).strip() != b"+PONG":
            raise RuntimeError("Redis did not return PONG")
    finally:
        writer.close()
        await writer.wait_closed()
    return {"role": "reserved; no background ingestion worker in v0.3"}


async def graph_check():
    async with AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        connection_timeout=3,
    ) as driver:
        await driver.verify_connectivity()
    return {"role": "optional projection; Path Finder reads PostgreSQL"}


async def search_check():
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(settings.opensearch_url + "/_cluster/health")
        response.raise_for_status()
        state = response.json()["status"]
        if state not in {"green", "yellow"}:
            raise RuntimeError("OpenSearch cluster is not available")
    return {"role": "reserved; entity search currently reads PostgreSQL", "cluster": state}


async def checked(name, function, required):
    try:
        details = await asyncio.wait_for(function(), timeout=6)
        return name, {"status": "ok", "required": required, **details}
    except Exception as exc:
        return name, {"status": "error", "required": required, "error": type(exc).__name__}


async def readiness(full=False):
    probes = [("postgres", database_check, True), ("evidence", evidence_check, True)]
    if full:
        probes += [
            ("neo4j", graph_check, False),
            ("redis", redis_check, False),
            ("opensearch", search_check, False),
        ]
    components = dict(await asyncio.gather(*(checked(*item) for item in probes)))
    ready = all(v["status"] == "ok" for v in components.values() if v["required"])
    return {
        "status": "ready" if ready else "unavailable",
        "components": components,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


CONNECTORS = [
    {
        "code": "EUROSTAT",
        "mode": "live_https",
        "scope": "official Eurostat Statistics API observations with canonical evidence",
    },
    {
        "code": "WORLD_BANK",
        "mode": "live_https",
        "scope": "official World Bank Indicators API v2 observations",
    },
    {
        "code": "OECD",
        "mode": "live_https",
        "scope": "official OECD Data Explorer SDMX observations",
    },
    {
        "code": "IMF",
        "mode": "live_https",
        "scope": "official IMF DataMapper v2 time series",
    },
    {
        "code": "INE_ES",
        "mode": "live_https",
        "scope": "Spain INEbase official JSON API tables",
    },
    {
        "code": "ONS_UK",
        "mode": "live_https",
        "scope": "UK ONS official v1 API explicit observations",
    },
    {
        "code": "UN_SDG",
        "mode": "live_https",
        "scope": "official UNSD SDG observations; complete bounded snapshots with provenance",
    },
    {
        "code": "GLEIF",
        "mode": "live_https",
        "scope": "LEI and accounting parent relationships; not natural-person beneficial ownership",
    },
    {
        "code": "TED",
        "mode": "live_https",
        "scope": "procurement notices and explicit award amounts; access not certified",
    },
    {
        "code": "EURLEX",
        "mode": "live_https",
        "scope": "Cellar legal metadata and CELEX relations",
    },
    {
        "code": "EU_TRANSPARENCY",
        "mode": "file_import",
        "scope": "official exports normalized to documented JSON",
    },
    {
        "code": "OCDS",
        "mode": "live_https_and_file",
        "scope": "Find a Tender and OCDS 1.1 release package subset",
    },
    {
        "code": "BODS",
        "mode": "live_publisher_snapshot_and_file",
        "scope": "Open Ownership bounded real ZIP prefix; BODS 0.3/0.4 subsets; not a complete/current registry",
    },
    {
        "code": "PPDS",
        "mode": "configured_https_and_file",
        "scope": "operator mapping; credentials/legal access required for institutional sources",
    },
]
