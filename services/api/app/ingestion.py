import json

from .canonicalize import canonicalize_eurlex, canonicalize_gleif
from .connectors.eurlex import EurLexConnector
from .connectors.gleif import GleifConnector
from .connectors.ted import TedConnector
from .db import connection
from .models import IngestResult, TedSearchRequest
from .object_store import EvidenceStore
from .ingest_repository import (
    create_ingest_job,
    finish_ingest_job,
    get_source_id,
    upsert_raw_artifact,
    upsert_source_record,
)
from .settings import settings


class IngestionService:
    def __init__(self) -> None:
        self.store = EvidenceStore()

    async def ingest_gleif_lei(self, lei: str) -> IngestResult:
        connector = GleifConnector(settings.gleif_base_url, settings.http_timeout_seconds)
        payload = await connector.get_lei(lei)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        artifact = self.store.put_bytes("GLEIF", lei, raw, "application/json")

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, "GLEIF")
                job_id = await create_ingest_job(conn, source_id, "GLEIF_LEI", {"lei": lei})
                artifact_id = await upsert_raw_artifact(
                    conn, source_id, lei, artifact, {"connector": "GLEIF"}
                )
                source_record_id = await upsert_source_record(
                    conn,
                    source_id=source_id,
                    external_id=lei,
                    payload_hash=artifact.sha256,
                    payload_uri=self.store.uri(artifact.object_key),
                    parser_version="trace-v0.2",
                    schema_version="GLEIF_JSON_API",
                    raw_payload=None,
                )
                entity_id = await canonicalize_gleif(conn, payload, source_record_id)
                await finish_ingest_job(
                    conn, job_id, "SUCCEEDED", source_record_id, artifact_id, None
                )

        return IngestResult(
            source="GLEIF",
            external_id=lei,
            status="SUCCEEDED",
            source_record_id=source_record_id,
            raw_artifact_id=artifact_id,
            entity_ids=[entity_id],
            sha256=artifact.sha256,
        )

    async def ingest_eurlex(self, celex: str, language: str = "eng") -> IngestResult:
        connector = EurLexConnector(settings.cellar_base_url, settings.http_timeout_seconds)
        document = await connector.fetch_by_celex(celex, language)
        text = str((document.payload or {}).get("text", ""))
        raw = text.encode("utf-8")
        artifact = self.store.put_bytes(
            "EURLEX", celex, raw, document.content_type or "text/html"
        )

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, "EURLEX")
                job_id = await create_ingest_job(
                    conn,
                    source_id,
                    "EURLEX_CELEX",
                    {"celex": celex, "language": language},
                )
                artifact_id = await upsert_raw_artifact(
                    conn,
                    source_id,
                    celex,
                    artifact,
                    {"canonical_uri": document.canonical_uri},
                )
                source_record_id = await upsert_source_record(
                    conn,
                    source_id=source_id,
                    external_id=celex,
                    payload_hash=artifact.sha256,
                    payload_uri=self.store.uri(artifact.object_key),
                    parser_version="trace-v0.2",
                    schema_version="CELLAR_XHTML",
                    raw_payload=None,
                )
                entity_id, document_id = await canonicalize_eurlex(
                    conn,
                    celex=celex,
                    html=text,
                    canonical_uri=document.canonical_uri,
                    content_hash=artifact.sha256,
                    object_uri=self.store.uri(artifact.object_key),
                    source_record_id=source_record_id,
                )
                await finish_ingest_job(
                    conn, job_id, "SUCCEEDED", source_record_id, artifact_id, None
                )

        return IngestResult(
            source="EURLEX",
            external_id=celex,
            status="SUCCEEDED",
            source_record_id=source_record_id,
            raw_artifact_id=artifact_id,
            entity_ids=[entity_id],
            document_ids=[document_id],
            sha256=artifact.sha256,
        )

    async def ingest_ted_search(self, request: TedSearchRequest) -> IngestResult:
        connector = TedConnector(settings.ted_base_url, settings.http_timeout_seconds)
        payload = await connector.search(request)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        request_fingerprint = connector.stable_json_hash(
            request.model_dump(mode="json")
        )[:24]
        external_id = f"search-{request_fingerprint}"
        artifact = self.store.put_bytes("TED", external_id, raw, "application/json")

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, "TED")
                job_id = await create_ingest_job(
                    conn,
                    source_id,
                    "TED_SEARCH",
                    request.model_dump(mode="json"),
                )
                artifact_id = await upsert_raw_artifact(
                    conn,
                    source_id,
                    external_id,
                    artifact,
                    {"query": request.query},
                )
                source_record_id = await upsert_source_record(
                    conn,
                    source_id=source_id,
                    external_id=external_id,
                    payload_hash=artifact.sha256,
                    payload_uri=self.store.uri(artifact.object_key),
                    parser_version="trace-v0.2",
                    schema_version="TED_V3_SEARCH",
                    raw_payload=None,
                )
                await finish_ingest_job(
                    conn, job_id, "SUCCEEDED", source_record_id, artifact_id, None
                )

        return IngestResult(
            source="TED",
            external_id=external_id,
            status="SUCCEEDED",
            source_record_id=source_record_id,
            raw_artifact_id=artifact_id,
            sha256=artifact.sha256,
            notes=[
                "Raw TED search response persisted. Canonical notice extraction is "
                "schema-gated and is not inferred generically in v0.2."
            ],
        )
