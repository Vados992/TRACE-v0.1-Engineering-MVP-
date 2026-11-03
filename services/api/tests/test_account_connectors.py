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
    assert seen == [("https://evidence.internal.example/sources?limit=100", "unit-test-key")]
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


@pytest.mark.parametrize("url", ["https://[invalid", "https://evidence.test:bad"])
def test_evidence_x_invalid_url_is_classified_unavailable(url):
    with pytest.raises(EvidenceXUnavailable):
        EvidenceXClient(url, "key")


@pytest.mark.asyncio
async def test_evidence_x_malformed_response_rejected():
    client = EvidenceXClient("https://evidence.internal.example", "key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"sources": []})))
    with pytest.raises(EvidenceXUnavailable):
        await client.list_sources()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[None], ["invalid"], [42], [["nested"]]])
async def test_evidence_x_invalid_rows_fail_closed(payload):
    client = EvidenceXClient("https://evidence.internal.example", "key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    with pytest.raises(EvidenceXUnavailable):
        await client.list_sources()


@pytest.mark.asyncio
async def test_evidence_x_stream_cap_closes_response_before_exhaustion():
    class OversizedStream(httpx.AsyncByteStream):
        consumed = 0
        closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.consumed += 1
                yield b'x' * 65536

        async def aclose(self):
            self.closed = True

    stream = OversizedStream()
    client = EvidenceXClient("https://evidence.internal.example", "key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)))
    with pytest.raises(EvidenceXUnavailable, match="size limit"):
        await client.list_sources(3)
    assert stream.consumed == 16
    assert stream.closed
