from html.parser import HTMLParser
from typing import Any


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def extract_html_title(html: str) -> str | None:
    parser = _TitleParser()
    parser.feed(html)
    title = " ".join(" ".join(parser.parts).split())
    return title or None


def parse_gleif_record(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list):
        if not data:
            raise ValueError("GLEIF payload contains no data")
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("GLEIF payload does not contain a record")

    attrs = data.get("attributes") or {}
    entity = attrs.get("entity") or {}
    legal_name = entity.get("legalName") or {}
    legal_address = entity.get("legalAddress") or {}

    lei = data.get("id") or attrs.get("lei")
    name = legal_name.get("name")
    if not lei or not name:
        raise ValueError("GLEIF record is missing LEI or legal name")

    return {
        "lei": str(lei),
        "legal_name": str(name),
        "jurisdiction": entity.get("legalJurisdiction") or legal_address.get("country"),
        "status": entity.get("status"),
        "legal_address": legal_address,
    }
