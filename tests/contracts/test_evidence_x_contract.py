"""Real ASGI apps and SQLite metadata; no PostgreSQL, TLS or live-source claim.

Run explicitly with TRACE_EVIDENCE_X_CHECKOUT pointing to an EVIDENCE-X checkout.
The isolated package name avoids collisions between both repositories' `app`.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from app import account_api
from app.account_connectors import EvidenceXClient
from app.boundaries import BoundaryMiddleware
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

CHECKOUT = os.getenv('TRACE_EVIDENCE_X_CHECKOUT')
pytestmark = pytest.mark.skipif(not CHECKOUT, reason='Set TRACE_EVIDENCE_X_CHECKOUT for two-repository contract')


@pytest.mark.asyncio
async def test_trace_account_reads_real_evidence_x_metadata_with_viewer_key(monkeypatch):
    package = Path(CHECKOUT).resolve() / 'app'
    spec = importlib.util.spec_from_file_location('evidence_x_contract', package / '__init__.py',
                                               submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    evidence_api = importlib.import_module('evidence_x_contract.api')
    models = importlib.import_module('evidence_x_contract.db')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    key = 'synthetic-contract-viewer-service-key'
    monkeypatch.setenv('EVIDENCE_X_API_KEY', 'synthetic-contract-admin-key-1234567890')
    monkeypatch.setenv('EVIDENCE_X_KEY_ROLES_JSON', json.dumps({hashlib.sha256(key.encode()).hexdigest():
                      {'actor': 'trace_metadata_service', 'role': 'viewer'}}))
    monkeypatch.delenv('EVIDENCE_X_REQUIRE_ENCRYPTION', raising=False)
    monkeypatch.delenv('EVIDENCE_X_EVIDENCE_KEY', raising=False)

    def temporary_session():
        with Session(engine) as db:
            yield db

    evidence_api.app.dependency_overrides[evidence_api.session] = temporary_session
    try:
        with Session(engine) as db:
            for ident in ['contract-source-one', 'contract-source-two']:
                db.add(models.Source(id=ident, provider='synthetic', external_id=ident,
                    source_url='https://example.test/' + ident, sha256='a' * 64,
                    media_type='text/plain', payload=b'synthetic bytes', source_status='retrieved'))
            db.commit()
        transport = httpx.ASGITransport(app=evidence_api.app)
        monkeypatch.setattr(account_api.settings, 'account_evidence_x_base_url', 'https://evidence.test')
        monkeypatch.setattr(account_api.settings, 'account_evidence_x_key', SecretStr(key))
        monkeypatch.setattr(account_api, 'EvidenceXClient', lambda base, secret:
                            EvidenceXClient(base, secret, transport=transport))
        trace_app = FastAPI()
        trace_app.include_router(account_api.router)
        trace_app.add_middleware(BoundaryMiddleware)
        url = '/api/internal/accountability/evidence-x/sources?limit=1'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=trace_app), base_url='https://trace.test') as client:
            assert (await client.get(url)).status_code == 401
            assert (await client.get(url, headers={'Authorization': 'Bearer trace-dev-analyst-only'})).status_code == 403
            reviewer = {'Authorization': 'Bearer trace-dev-reviewer-only'}
            response = await client.get(url, headers=reviewer)
            assert response.status_code == 200, response.text
            sources = response.json()
            assert len(sources) == 1
            assert sources[0]['verification'] == 'unverified'
            assert sources[0]['evidence_x_source_id'] == 'contract-source-two'
            assert sources[0]['sha256'] == 'a' * 64
            assert 'payload' not in sources[0]
            monkeypatch.setattr(account_api.settings, 'account_evidence_x_key', SecretStr('wrong-key'))
            assert (await client.get(url, headers=reviewer)).status_code == 503
        # A read-only service credential cannot become an investigator.
        async with httpx.AsyncClient(transport=transport, base_url='https://evidence.test') as client:
            assert (await client.post('/entities', headers={'x-evidence-key': key},
                                     json={'name': 'Synthetic', 'kind': 'authority'})).status_code == 403
        with Session(engine) as db:
            assert db.query(models.Source).count() == 2
    finally:
        evidence_api.app.dependency_overrides.clear()
        engine.dispose()
        for name in list(sys.modules):
            if name == 'evidence_x_contract' or name.startswith('evidence_x_contract.'):
                sys.modules.pop(name)
