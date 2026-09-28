from .models import InvestigationRequest, InvestigationResult
from .pathfinder import find_paths
from .investigation_repository import create_investigation, finish_investigation
from .repository import get_entity


async def run_investigation(request: InvestigationRequest) -> InvestigationResult:
    source = await get_entity(request.source_entity_id)
    target = await get_entity(request.target_entity_id)
    if not source or not target:
        missing = []
        if not source:
            missing.append(str(request.source_entity_id))
        if not target:
            missing.append(str(request.target_entity_id))
        raise ValueError(f"unknown entity id(s): {', '.join(missing)}")

    investigation_id = await create_investigation(request)
    try:
        paths = await find_paths(
            request.source_entity_id,
            request.target_entity_id,
            from_time=request.from_time,
            to_time=request.to_time,
            max_depth=request.max_depth,
            limit=request.limit,
            verified_only=request.verified_only,
        )
        unknowns = []
        if not paths:
            unknowns.append(
                "No qualifying path was found in the current canonical relationship graph. "
                "This is not evidence that no real-world relationship exists."
            )
        result = InvestigationResult(
            investigation_id=investigation_id,
            status="SUCCEEDED",
            source_entity=source,
            target_entity=target,
            paths=paths,
            unknowns=unknowns,
            warnings=[
                "Temporal proximity does not establish causation.",
                "TRACE reports documented relationships; it does not assign guilt or intent.",
            ],
        )
        await finish_investigation(investigation_id, result.model_dump(mode="json"))
        return result
    except Exception as exc:
        await finish_investigation(investigation_id, None, error=str(exc))
        raise
