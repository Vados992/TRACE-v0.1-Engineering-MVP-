"""Network-mocked contract tests: NO claim of live IMPIC or PostgreSQL availability."""
import hashlib
import io
import json
import zipfile
from decimal import Decimal

import httpx
import pytest

from app.account_connectors import EvidenceXClient
from app.account_engine import Observation, ProjectAssessmentInput, assess
from app.account_impic import (
    DATASET_URL,
    ImpicError,
    contract_from_row,
    fetch_snapshot,
    money,
    parse_rows,
    select_resource,
    unpack_json,
    verified_url,
)


RESOURCE = "https://dados.gov.pt/downloads/contratos2026.json"
RECORD = {"idContrato": "1001", "objectoContrato": "Construção de edifício público",
          "precoContratual": "123.456,78"}
METADATA = {"organization": {"name": "IMPIC - Instituto dos Mercados Públicos"},
            "resources": [{"title": "contratos2026.json", "format": "json", "url": RESOURCE}]}


def fake_transport(request):
    if str(request.url) == DATASET_URL:
        return httpx.Response(200, json=METADATA)
    if str(request.url) == RESOURCE:
        return httpx.Response(200, json=[RECORD])
    raise AssertionError("Unexpected call " + str(request.url))


@pytest.mark.asyncio
async def test_official_manifest_download_and_deterministic_contract():
    snap = await fetch_snapshot(2026, transport=httpx.MockTransport(fake_transport))
    assert snap.rows_total == 1 and snap.invalid_count == 0
    assert snap.contracts[0].price_eur == Decimal("123456.78")
    assert snap.raw_sha256 == hashlib.sha256(snap.raw).hexdigest()
    assert snap.contracts[0].contract_id == "1001"


def test_host_rejection_and_publisher_validation():
    for url in ("https://evil.example/contratos2026.json", "http://dados.gov.pt/file",
                "https://dados.gov.pt.evil.com/file", "https://dados.gov.pt:8443/a"):
        with pytest.raises(ImpicError):
            verified_url(url)
    with pytest.raises(ImpicError):
        select_resource({"organization": {"name": "Other"},
                         "resources": METADATA["resources"]}, 2026)


@pytest.mark.asyncio
async def test_redirect_refused():
    def redirected(request):
        if str(request.url) == DATASET_URL:
            return httpx.Response(302, headers={"location": "https://evil.example/file"})
        raise AssertionError("Unexpected request")
    with pytest.raises(ImpicError):
        await fetch_snapshot(2026, transport=httpx.MockTransport(redirected))


@pytest.mark.asyncio
async def test_large_download_refused():
    with pytest.raises(ImpicError):
        await fetch_snapshot(2026, transport=httpx.MockTransport(fake_transport), max_bytes=10)


def test_archive_rejects_multiple_json_and_expansion():
    f = io.BytesIO()
    with zipfile.ZipFile(f, "w") as archive:
        archive.writestr("a.json", "[]")
        archive.writestr("b.json", "[]")
    with pytest.raises(ImpicError):
        unpack_json(f.getvalue(), "zip")


def test_unknown_schema_rejected():
    with pytest.raises(ImpicError):
        parse_rows(json.dumps({"unexpected": [{"id": 1}]}).encode())


def test_monetary_fields_are_not_payments():
    assert money("1.234,56") == money("1234.56")
    assert contract_from_row(RECORD).price_eur == money("123456.78")
    with pytest.raises(ImpicError):
        money("1,2,3")


@pytest.mark.asyncio
async def test_trace_account_evidence_x_contract_chain():
    """In-process end-to-end *contract* mock, not an external EVIDENCE-X instance."""
    snap = await fetch_snapshot(2026, transport=httpx.MockTransport(fake_transport))
    digest = hashlib.sha256(b"official evidence fixture").hexdigest()

    def evidence_x_mock(request):
        assert request.url.path == "/sources"
        assert request.headers["x-evidence-key"] == "test-secret"
        return httpx.Response(200, json=[{
            "id": "src-1", "source_url": "https://www.base.gov.pt/contratos/1001",
            "sha256": digest,
        }])

    bridge = EvidenceXClient("https://evidence.internal.test", "test-secret",
                             httpx.MockTransport(evidence_x_mock))
    refs = await bridge.list_sources()
    assert refs[0].verification == "unverified"
    contract = snap.contracts[0]
    input_data = ProjectAssessmentInput(
        project_id="impic:1001", title=contract.title, jurisdiction="PT",
        source_system="trace", evidence=[refs[0]],
        observations=[Observation(kind="awarded_total", value=contract.price_eur,
                                  unit="EUR", evidence_id=refs[0].id)],
    )
    result = assess(input_data)
    assert result.metrics["budget_variance_amount"] is None
    assert result.review_state == "ANALYTICAL_LEAD_ONLY"
    assert "EVIDENCE_UNREVIEWED" in [s.code for s in result.signals]


def test_does_not_confuse_dataset_year_range_with_a_yearly_resource():
    incorrect = {"organization": {"name": "IMPIC"}, "resources": [{
        "title": "contratos2019.json", "format": "json",
        "url": "https://dados.gov.pt/datasets/2012-a-2026/contratos2019.json",
    }]}
    with pytest.raises(ImpicError):
        select_resource(incorrect, 2026)
