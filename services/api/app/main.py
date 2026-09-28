from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
import httpx
from .connectors.base import ConnectorError
from .system_status import readiness, CONNECTORS

from .connectors.eurlex import EurLexConnector
from .connectors.gleif import GleifConnector
from .connectors.ted import TedConnector
from .db import pool
from .entity_resolution.scorer import score_records
from .ingestion import IngestionService
from .investigations import run_investigation
from .models import (
    EntityDetail,
    EntitySummary,
    GraphPathRequest,
    IngestResult,
    InvestigationRequest,
    InvestigationResult,
    LobbyingImportRequest,
    ReconciliationSummary,
    RelationshipBuildResult,
    ResolutionRequest,
    ResolutionResult,
    TedSearchRequest,
)
from .pathfinder import find_paths
from .investigation_repository import get_investigation
from .path_repository import relationship_evidence
from .relationship_intelligence import RelationshipIntelligenceService, reconciliation_summary
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
    version="0.3.0",
    summary="Provenance-first public-interest relationship explorer",
    lifespan=lifespan,
)

static_dir = Path(__file__).resolve().parents[1] / "static"
if static_dir.exists():
    app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse("/ui/")


@app.exception_handler(ConnectorError)
async def connector_error(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def network_error(request, exc):
    return JSONResponse(status_code=502, content={"detail": "External source unavailable; retry later.", "error": type(exc).__name__})


@app.get("/ready")
async def ready():
    result = await readiness()
    return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)


@app.get("/api/v1/system/status")
async def system_status():
    return {**await readiness(full=True), "connectors": CONNECTORS, "version": "0.3.0-desktop.1"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0", "environment": settings.trace_env}


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
async def gleif_search(
    name: str = Query(min_length=2),
    page_size: int = Query(default=10, ge=1, le=100),
):
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


@app.post("/api/v1/ingest/gleif/{lei}", response_model=IngestResult)
async def ingest_gleif(lei: str):
    return await IngestionService().ingest_gleif_lei(lei)


@app.post("/api/v1/ingest/eurlex/{celex}", response_model=IngestResult)
async def ingest_eurlex(celex: str, language: str = "eng"):
    return await IngestionService().ingest_eurlex(celex, language)


@app.post("/api/v1/ingest/ted/search", response_model=IngestResult)
async def ingest_ted(request: TedSearchRequest):
    return await IngestionService().ingest_ted_search(request)


@app.post(
    "/api/v1/relationship-intelligence/ownership/gleif/{lei}",
    response_model=RelationshipBuildResult,
)
async def build_ownership(lei: str):
    return await RelationshipIntelligenceService().build_gleif_ownership(lei)


@app.post(
    "/api/v1/relationship-intelligence/procurement/ted/search",
    response_model=RelationshipBuildResult,
)
async def build_procurement(request: TedSearchRequest):
    return await RelationshipIntelligenceService().build_ted_procurement(request)


@app.post(
    "/api/v1/relationship-intelligence/lobbying/import",
    response_model=RelationshipBuildResult,
)
async def build_lobbying(request: LobbyingImportRequest):
    return await RelationshipIntelligenceService().import_lobbying(request)


@app.post(
    "/api/v1/relationship-intelligence/policy/eurlex/{celex}",
    response_model=RelationshipBuildResult,
)
async def build_policy_lifecycle(celex: str):
    return await RelationshipIntelligenceService().build_policy_lifecycle(celex)


@app.get("/api/v1/reconciliation/summary", response_model=ReconciliationSummary)
async def reconciliation_status():
    return await reconciliation_summary()


@app.post("/api/v1/graph/path")
async def graph_path(request: GraphPathRequest):
    return {
        "paths": await find_paths(
            request.source_entity_id,
            request.target_entity_id,
            from_time=request.from_time,
            to_time=request.to_time,
            max_depth=request.max_depth,
            limit=request.limit,
            verified_only=request.verified_only,
        )
    }


@app.get("/api/v1/relationships/{relationship_id}/why")
async def why_relationship(relationship_id: UUID):
    result = await relationship_evidence(relationship_id)
    if not result:
        raise HTTPException(status_code=404, detail="relationship not found")
    return result


@app.post("/api/v1/investigations", response_model=InvestigationResult)
async def investigate(request: InvestigationRequest):
    try:
        return await run_investigation(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/investigations/{investigation_id}")
async def investigation_detail(investigation_id: UUID):
    result = await get_investigation(investigation_id)
    if not result:
        raise HTTPException(status_code=404, detail="investigation not found")
    return result
