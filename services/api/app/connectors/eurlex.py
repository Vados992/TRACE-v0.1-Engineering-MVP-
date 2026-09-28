from .base import BaseConnector
from ..models import ExternalDocument


class EurLexConnector(BaseConnector):
    source_code = "EURLEX"

    async def fetch_by_celex(self, celex: str, language: str = "eng") -> ExternalDocument:
        # Cellar supports content negotiation on /resource/celex/{CELEX}.
        # We request XHTML where available; redirect handling is enabled in BaseConnector.
        url = f"{self.base_url}/{celex}"
        response = await self.request(
            "GET",
            url,
            headers={
                "Accept": "application/xhtml+xml,text/html;q=0.9,application/xml;q=0.8",
                "Accept-Language": language,
                "User-Agent": "TRACE/0.1 public-interest research connector",
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
