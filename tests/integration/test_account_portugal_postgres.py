"""Real PostgreSQL TRACE integration: official bytes -> TRACE refs -> assessment -> review.

Runs in CI's PostgreSQL service after migrations; official HTTP and EVIDENCE-X
transport are mocked, NEVER described as live provider/production integration.
"""
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.account_portugal import CATALOG_URL, DATASET_SLUG
from app.main import app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_capture_to_trace_account_and_evidence_x_bridge(monkeypatch):
    from app import account_api
    from app.account_connectors import EvidenceXClient
    from app.account_portugal import PortugalBaseClient

    resource = 'https://www.base.gov.pt/resources/contracts-2026.json'
    catalog = {'slug': DATASET_SLUG, 'resources': [
        {'id': '2026-fixture', 'url': resource, 'format': 'json', 'size': 999}
    ]}

    def pt_server(req):
        if str(req.url) == CATALOG_URL:
            return httpx.Response(200, json=catalog)
        if str(req.url) == resource:
            return httpx.Response(200, json=[{'idContrato': 'PT-CI-1', 'valorContrato': '9000'}])
        return httpx.Response(404)

    pt_transport = httpx.MockTransport(pt_server)
    monkeypatch.setattr(account_api, 'PortugalBaseClient', lambda: PortugalBaseClient(transport=pt_transport))

    def ex_server(req):
        if req.url.path == '/sources':
            assert req.url.params['limit'] == '25'
            assert req.headers.get('x-evidence-key') == 'scoped-test-key'
            return httpx.Response(200, json=[
                {'id': 'ex001', 'source_url': 'https://www.eca.europa.eu/official.pdf',
                 'sha256': 'a' * 64}
            ])
        return httpx.Response(404)

    monkeypatch.setattr(account_api.settings, 'account_evidence_x_base_url', 'https://evidence.example')
    from pydantic import SecretStr
    monkeypatch.setattr(account_api.settings, 'account_evidence_x_key', SecretStr('scoped-test-key'))
    monkeypatch.setattr(account_api, 'EvidenceXClient', lambda base, key: EvidenceXClient(
        base, key, transport=httpx.MockTransport(ex_server)))

    with TestClient(app) as client:
        a = {'Authorization': 'Bearer trace-dev-analyst-only'}
        r = {'Authorization': 'Bearer trace-dev-reviewer-only'}
        assert client.post('/api/internal/accountability/portugal/refresh').status_code == 401
        first = client.post('/api/internal/accountability/portugal/refresh', headers=a)
        assert first.status_code == 200, first.text
        captured = first.json()
        assert captured['data_status'] == 'raw_official_records_captured_unreviewed'
        assert captured['records']['row_count'] == 1
        second = client.post('/api/internal/accountability/portugal/refresh', headers=a)
        assert second.status_code == 200 and second.json()['records']['reused']
        bridge = client.get('/api/internal/accountability/evidence-x/sources', headers=r)
        assert bridge.status_code == 200 and bridge.json()[0]['verification'] == 'unverified'
        payload = json.loads((ROOT / 'fixtures/accountability/kastoria_eca2014.json').read_text())
        payload['project_id'] = 'CI-' + uuid4().hex
        payload['evidence'].append({
            'id': 'pt-primary', 'url': resource, 'locator': 'JSON row PT-CI-1',
            'trace_source_record_id': captured['records']['trace_source_record_id'],
            'verification': 'unverified', 'declared_type': 'official',
        })
        payload['evidence'].append({
            'id': 'ex:ex001', 'url': bridge.json()[0]['url'],
            'locator': 'EVIDENCE-X /sources ex001', 'sha256': 'a' * 64,
            'evidence_x_source_id': 'ex001', 'declared_type': 'external_evidence_x',
            'verification': 'unverified',
        })
        submitted = client.post('/api/internal/accountability/submit', headers=a, json=payload)
        assert submitted.status_code == 201, submitted.text
        uid = submitted.json()['assessment_id']
        reviewer = client.post(f'/api/internal/accountability/assessments/{uid}/review',
                               headers=r, json={'verdict': 'NEEDS_INFORMATION',
                                                'note': 'More independent source verification is needed.'})
        assert reviewer.status_code == 201, reviewer.text
        detail = client.get(f'/api/internal/accountability/assessments/{uid}', headers=r)
        assert detail.status_code == 200 and detail.json()['reviews']
        integrity = client.get(
            '/api/internal/accountability/portugal/snapshots/' + captured['records']['snapshot_id']
            + '/verify', headers=r)
        assert integrity.status_code == 200 and integrity.json()['integrity_ok']
