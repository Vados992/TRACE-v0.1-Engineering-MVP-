from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from .connectors.eurlex import EurLexConnector
from .connectors.gleif import GleifConnector
from .connectors.ted import TedConnector
from .db import pool
from .entity_resolution.scorer import score_records
from .models import EntityDetail, EntitySummary, ResolutionRequest, ResolutionResult, TedSearchRequest
from .repository import get_entity, search_entities
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(
    title="TRACE API",
    version="0.1.0",
    summary="Provenance-first public-interest relationship explorer",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "environment": settings.trace_env}


@app.get("/api/v1/entities/search", response_model=list[EntitySummary])
async def entity_search(
    q: str = Query(min_length=1),
    entity_type: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
):
    return await search_entities(q, entity_type, limit)


@app.get("/api/v1/entities/{entity_id}", response_model=EntityDetail)
async def entity_detail(entity_id: UUID):
    entity = await get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="entity not found")
    return entity


@app.post("/api/v1/resolve/compare", response_model=ResolutionResult)
async def resolve_compare(request: ResolutionRequest):
    return score_records(request.left, request.right)


@app.post("/api/v1/connectors/ted/search")
async def ted_search(request: TedSearchRequest):
    connector = TedConnector(settings.ted_base_url, settings.http_timeout_seconds)
    return await connector.search(request)


@app.get("/api/v1/connectors/gleif/search")
async def gleif_search(name: str = Query(min_length=2), page_size: int = Query(default=10, ge=1, le=100)):
    connector = GleifConnector(settings.gleif_base_url, settings.http_timeout_seconds)
    return await connector.search_by_name(name, page_size)


@app.get("/api/v1/connectors/gleif/{lei}")
async def gleif_record(lei: str):
    connector = GleifConnector(settings.gleif_base_url, settings.http_timeout_seconds)
    return await connector.get_lei(lei)


@app.get("/api/v1/connectors/eurlex/{celex}")
async def eurlex_document(celex: str, language: str = "eng"):
    connector = EurLexConnector(settings.cellar_base_url, settings.http_timeout_seconds)
    return await connector.fetch_by_celex(celex, language)
