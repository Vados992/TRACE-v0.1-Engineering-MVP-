import httpx
import pytest
from app.main import app
from app.settings import settings


@pytest.mark.asyncio
async def test_cross_origin_mutation_rejected(monkeypatch):
    monkeypatch.setattr(settings, 'trace_env', 'desktop')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
        external = await client.post('/api/v1/graph/path', json={}, headers={'Origin':'https://untrusted.example'})
        assert external.status_code == 403
        same = await client.post('/api/v1/graph/path', json={}, headers={'Origin':'http://127.0.0.1:8000'})
        assert same.status_code == 422  # Reaches normal schema validation, not a database.
        live = await client.get('/health')
        assert live.status_code == 200
