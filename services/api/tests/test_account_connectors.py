"""Mock-HTTP integration tests for permissioned EVIDENCE-X source bridge."""
import httpx
import pytest

from app.account_connectors import EvidenceXClient, EvidenceXUnavailable


@pytest.mark.asyncio
async def test_evidence_x_list_sends_scoped_key_and_keeps_unverified():
    seen = []

    def responder(request):
        seen.append((str(request.url), request.headers.get("x-evidence-key")))
        return httpx.Response(200, json=[{"id": "source123", "source_url": "https://www.eca.europa.eu/a.pdf",
            "sha256": "a" * 64, "status": "retrieved"}])

    client = EvidenceXClient("https://evidence.internal.example", "unit-test-key",
                             transport=httpx.MockTransport(responder))
    entries = await client.list_sources()
    assert seen == [("https://evidence.internal.example/sources", "unit-test-key")]
    assert len(entries) == 1
    assert entries[0].verification == "unverified"
    assert entries[0].evidence_x_source_id == "source123"


@pytest.mark.asyncio
async def test_evidence_x_denied_or_redirect_is_not_followed():
    for status in (302, 401, 500):
        client = EvidenceXClient("https://evidence.internal.example", "key",
            transport=httpx.MockTransport(lambda request: httpx.Response(status,
                headers={"Location": "https://unauthorised.example"})))
        with pytest.raises(EvidenceXUnavailable):
            await client.list_sources()


def test_evidence_x_rejects_plaintext_or_local_url():
    with pytest.raises(EvidenceXUnavailable):
        EvidenceXClient("http://localhost:8000", "key")
    with pytest.raises(EvidenceXUnavailable):
        EvidenceXClient("https://evidence.internal.example", "")


@pytest.mark.asyncio
async def test_evidence_x_malformed_response_rejected():
    client = EvidenceXClient("https://evidence.internal.example", "key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"sources": []})))
    with pytest.raises(EvidenceXUnavailable):
        await client.list_sources()
