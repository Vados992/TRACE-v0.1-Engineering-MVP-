from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .boundaries import BoundaryMiddleware
from .connectors.base import ConnectorError
from .connectors.eurlex import EurLexConnector
from .connectors.gleif import GleifConnector
from .connectors.ted import TedConnector
from .db import pool
from .entity_resolution.scorer import score_records
from .ingestion import IngestionService
from .investigation_repository import get_investigation
from .investigations import run_investigation
from .observability import ObservabilityMiddleware
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
from .path_repository import relationship_evidence
from .pathfinder import GraphBudgetExceeded, find_paths
from .pia_api import internal, public
from .relationship_intelligence import RelationshipIntelligenceService, reconciliation_summary
from .repository import get_entity, search_entities
from .security import validate_configuration
from .settings import settings
from .system_status import CONNECTORS, readiness
from .temporal import resolve_known_at


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_configuration()
    await pool.open()
    try:
        await pool.wait(timeout=15)
        if settings.trace_env == "production":
            async with pool.connection() as conn:
                role = await (
                    await conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
                ).fetchone()
                if role["rolsuper"]:
                    raise RuntimeError("Production API must use a non-superuser database role")
        yield
    finally:
        await pool.close()


app = FastAPI(
    title="TRACE-PIA API",
    version="0.4.0",
    summary="Provenance-first public-interest relationship explorer",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(BoundaryMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.include_router(internal)
app.include_router(public)


@app.middleware("http")
async def desktop_origin_guard(request, call_next):
    origin = request.headers.get("origin")
    if (
        settings.trace_env == "desktop"
        and origin
        and request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        parsed = urlsplit(origin)
        if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
            return JSONResponse(status_code=403, content={"detail": "Cross-origin write rejected"})
    return await call_next(request)


static_dir = Path(__file__).resolve().parents[1] / "static"
if static_dir.exists():
    app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")
    app.mount("/public", StaticFiles(directory=static_dir / "public", html=True), name="public-ui")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse("/ui/")


@app.get("/docs", include_in_schema=False)
async def docs():
    return RedirectResponse("/ui/api-docs.html")


@app.exception_handler(ConnectorError)
async def connector_error(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(GraphBudgetExceeded)
async def graph_budget_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def network_error(request, exc):
    return JSONResponse(
        status_code=502,
        content={
            "detail": "External source unavailable; retry later.",
            "error": type(exc).__name__,
        },
    )


@app.get("/ready")
async def ready():
    result = await readiness()
    return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)


@app.get("/api/v1/system/status")
async def system_status():
    return {**await readiness(full=True), "connectors": CONNECTORS, "version": "0.4.0"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.4.0", "environment": settings.trace_env}


@app.get("/api/v1/entities/search", response_model=list[EntitySummary])
async def entity_search(
    q: str = Query(min_length=1),
    entity_type: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    include_demo: bool = False,
    known_at: AwareDatetime | None = None,
):
    return await search_entities(q, entity_type, limit, include_demo, known_at)


@app.get("/api/v1/entities/{entity_id}", response_model=EntityDetail)
async def entity_detail(entity_id: UUID, known_at: AwareDatetime | None = None):
    entity = await get_entity(entity_id, known_at)
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
    known_at = await resolve_known_at(request.known_at)
    return {
        "known_at": known_at,
        "paths": await find_paths(
            request.source_entity_id,
            request.target_entity_id,
            from_time=request.from_time,
            to_time=request.to_time,
            known_at=known_at,
            max_depth=request.max_depth,
            limit=request.limit,
            verified_only=request.verified_only,
        ),
    }


@app.get("/api/v1/relationships/{relationship_id}/why")
async def why_relationship(relationship_id: UUID, known_at: AwareDatetime | None = None):
    result = await relationship_evidence(relationship_id, await resolve_known_at(known_at))
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


def documented_openapi():
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for path, operations in schema["paths"].items():
        if path.startswith("/api/v1/"):
            for operation in operations.values():
                if isinstance(operation, dict) and "responses" in operation:
                    operation["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = documented_openapi
