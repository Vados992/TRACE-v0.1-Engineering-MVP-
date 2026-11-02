"""Deterministic source-contract tests; HTTP mocks aren't claims of live source availability."""
import hashlib
import json

import httpx
import pytest
from app.account_portugal import (
    CATALOG_URL,
    DATASET_SLUG,
    MAX_RESOURCE_BYTES,
    PortugalBaseClient,
    PortugalSourceError,
    decode_records,
    resource_options,
    row_fingerprint,
    source_key,
    validate_official_url,
)

RESOURCE_URL = 'https://www.base.gov.pt/resources/impic-contracts-2026.json'
DATASET = {
    'slug': DATASET_SLUG, 'organization': {'name': 'IMPIC'},
    'resources': [
        {'id': 'public-json', 'title': 'Public contracts 2026', 'format': 'json',
         'url': RESOURCE_URL, 'filesize': 2048},
        {'id': 'blocked', 'format': 'json', 'url': 'http://127.0.0.1/secret'},
    ],
}


def mock_source(req):
    if str(req.url) == CATALOG_URL:
        return httpx.Response(200, json=DATASET)
    if str(req.url) == RESOURCE_URL:
        return httpx.Response(200, json=[
            {'idContrato': 'PT-2026-0001', 'valorContrato': '4000.00', 'tipo': 'contrato'},
            {'idContrato': 'PT-2026-0002', 'valorContrato': '8000.00', 'tipo': 'contrato'},
        ])
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_catalog_resource_capture_and_raw_integrity():
    client = PortugalBaseClient(transport=httpx.MockTransport(mock_source))
    meta, dataset, options = await client.catalog()
    assert dataset['organization']['name'] == 'IMPIC'
    assert len(options) == 1 and options[0].media_format == 'json'
    assert meta.sha256 == hashlib.sha256(meta.content).hexdigest()
    snapshot, rows = await client.resource(options[0])
    assert len(rows) == 2
    assert source_key(rows[0], row_fingerprint(rows[0])) == 'PT-2026-0001'
    assert snapshot.sha256 == hashlib.sha256(snapshot.content).hexdigest()
    assert all('paid_total' not in row for row in rows)


@pytest.mark.asyncio
async def test_redirect_never_followed():
    client = PortugalBaseClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={'Location': 'http://127.0.0.1/'})))
    with pytest.raises(PortugalSourceError):
        await client.catalog()


@pytest.mark.asyncio
async def test_catalog_payload_rejects_wrong_dataset():
    fake = {**DATASET, 'slug': 'wrong-dataset'}
    client = PortugalBaseClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=fake)))
    with pytest.raises(PortugalSourceError):
        await client.catalog()


def test_ssrf_and_unapproved_host_denied():
    for url in ('https://127.0.0.1/', 'http://dados.gov.pt/', 'https://example.com/file.json',
                'https://dados.gov.pt.evil.org/a', 'https://user:password@dados.gov.pt/a'):
        with pytest.raises(PortugalSourceError):
            validate_official_url(url)


def test_missing_recognized_rows_rejected():
    from app.account_portugal import Snapshot
    snapshot = Snapshot('contracts', RESOURCE_URL, json.dumps({'other': []}).encode(), 'json')
    with pytest.raises(PortugalSourceError):
        decode_records(snapshot)


def test_oversized_data_rejected():
    from app.account_portugal import Snapshot
    snapshot = Snapshot('contracts', RESOURCE_URL, b'x' * (MAX_RESOURCE_BYTES + 1), 'json')
    with pytest.raises(PortugalSourceError):
        decode_records(snapshot)


def test_unspecified_amount_stays_unclassified():
    rows = [{'valorContrato': '200.00'}]
    assert 'paid_total' not in rows[0]
    assert resource_options(DATASET)[0].url == RESOURCE_URL


@pytest.mark.asyncio
async def test_external_500_is_explicit_error():
    client = PortugalBaseClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(500)))
    with pytest.raises(PortugalSourceError):
        await client.catalog()
