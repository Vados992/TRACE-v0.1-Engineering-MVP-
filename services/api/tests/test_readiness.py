import app.system_status as status
import pytest


@pytest.mark.asyncio
async def test_dependency_failure_is_not_ready_and_hides_credentials(monkeypatch):
    async def broken():
        raise RuntimeError("postgresql://secret:password@db")

    async def good():
        return {}

    monkeypatch.setattr(status, "database_check", broken)
    monkeypatch.setattr(status, "evidence_check", good)
    result = await status.readiness()
    assert result["status"] == "unavailable"
    assert "password" not in str(result)


@pytest.mark.asyncio
async def test_optional_services_report_failure_without_masking_core(monkeypatch):
    async def good():
        return {}

    async def broken():
        raise RuntimeError("unavailable")

    monkeypatch.setattr(status, "database_check", good)
    monkeypatch.setattr(status, "evidence_check", good)
    for name in ["redis_check", "search_check", "graph_check"]:
        monkeypatch.setattr(status, name, broken)
    result = await status.readiness(full=True)
    assert result["status"] == "ready"
    assert result["components"]["neo4j"]["status"] == "error"
