from .base import BaseConnector
from ..models import ExternalDocument


class EurLexConnector(BaseConnector):
    source_code = "EURLEX"

    async def fetch_by_celex(self, celex: str, language: str = "eng") -> ExternalDocument:
        url = f"{self.base_url}/{celex}"
        response = await self.request(
            "GET",
            url,
            headers={
                "Accept": "application/xhtml+xml,text/html;q=0.9,application/xml;q=0.8",
                "Accept-Language": language,
                "User-Agent": "TRACE/0.3 public-interest research connector",
            },
        )
        content_type = response.headers.get("content-type")
        raw = response.content
        return ExternalDocument(
            source="EURLEX",
            external_id=celex,
            retrieved_at=self.now(),
            content_type=content_type,
            sha256=self.sha256_bytes(raw),
            canonical_uri=str(response.url),
            payload={"text": response.text},
        )

    async def fetch_metadata_rdf(self, celex: str) -> ExternalDocument:
        url = f"{self.base_url}/{celex}"
        response = await self.request(
            "GET",
            url,
            headers={
                "Accept": "application/rdf+xml;notice=tree",
                "User-Agent": "TRACE/0.3 public-interest research connector",
            },
        )
        raw = response.content
        return ExternalDocument(
            source="EURLEX",
            external_id=f"{celex}:rdf-tree",
            retrieved_at=self.now(),
            content_type=response.headers.get("content-type") or "application/rdf+xml",
            sha256=self.sha256_bytes(raw),
            canonical_uri=str(response.url),
            payload={"text": response.text},
        )
