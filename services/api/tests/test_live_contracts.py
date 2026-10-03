import io
import json
import zipfile

import httpx
import pytest
from app.adapters import parse_import
from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.datasets import OpenOwnershipArchiveConnector
from app.settings import settings


def test_bods04_ranges_and_closed_history():
    def statement(key, kind, details, status="new"):
        return {
            "statementId": key + "-statement",
            "recordId": key,
            "recordType": kind,
            "recordStatus": status,
            "statementDate": "2025-01-01",
            "publicationDetails": {"bodsVersion": "0.4"},
            "recordDetails": details,
        }

    rows = [
        statement(
            "owner",
            "person",
            {"personType": "knownPerson", "names": [{"fullName": "SYNTHETIC TEST PERSON"}]},
        ),
        statement(
            "ownership",
            "relationship",
            {
                "subject": "GB-COH-12345678",
                "interestedParty": "owner",
                "interests": [
                    {
                        "type": "shareholding",
                        "beneficialOwnershipOrControl": True,
                        "share": {"minimum": 25, "maximum": 50},
                        "startDate": "2020-01-01",
                    }
                ],
            },
        ),
    ]
    result = parse_import("bods", rows)
    assert len(result.relationships) == 1 and result.relationships[0].ownership_percent is None
    assert result.relationships[0].details["interests"][0]["share"] == {
        "minimum": 25,
        "maximum": 50,
    }
    assert next(e for e in result.entities if e.key.startswith("GB-COH")).name == "GB-COH-12345678"
    closed = {
        **rows[1],
        "statementId": "closed-history",
        "statementDate": "2025-02-01",
        "recordStatus": "closed",
    }
    result = parse_import("bods", rows + [closed])
    assert not result.relationships and any("closed" in w for w in result.warnings)


def test_zip_prefix_only_complete_statements():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "publisher.json",
            json.dumps({"recordType": "person"})
            + "\n"
            + json.dumps({"recordType": "relationship"})
            + "\n",
        )
    assert len(OpenOwnershipArchiveConnector.decode_prefix(stream.getvalue(), 1)) == 1
    with pytest.raises(ConnectorError):
        OpenOwnershipArchiveConnector.decode_prefix(b"not a zip", 1)


@pytest.mark.asyncio
async def test_private_source_urls_rejected_without_request():
    with pytest.raises(ConnectorError, match="HTTPS"):
        await BaseConnector.validate_url("http://127.0.0.1")
    with pytest.raises(ConnectorError, match="private"):
        await BaseConnector.validate_url("https://127.0.0.1")


@pytest.mark.asyncio
async def test_https_redirect_upgrade_and_response_cap(monkeypatch):
    factory = httpx.AsyncClient
    seen = []

    def responder(request):
        seen.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(303, headers={"Location": "http://publisher.example/document"})
        return httpx.Response(200, content=b"x" * 100)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(responder), **kw)
    )

    async def checked(url):
        assert str(url).startswith("https://")

    monkeypatch.setattr(BaseConnector, "validate_url", staticmethod(checked))
    connector = BaseConnector("https://publisher.example")
    connector.source_code = "TEST"
    response = await connector.request("GET", "https://publisher.example/redirect")
    assert response.status_code == 200 and all(url.startswith("https://") for url in seen)
    monkeypatch.setattr(settings, "http_max_response_bytes", 10)
    with pytest.raises(ConnectorError, match="byte limit"):
        await connector.request("GET", "https://publisher.example/document")
    with pytest.raises(ConnectorError, match="Credentialed"):
        await connector.request(
            "GET",
            "https://publisher.example/redirect",
            headers={"Authorization": "Bearer test-only"},
        )
