from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from io import StringIO
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET


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
    headquarters_address = entity.get("headquartersAddress") or {}
    registered_at = entity.get("registeredAt") or {}

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
        "headquarters_address": headquarters_address,
        "registration_authority_id": registered_at.get("id")
        if isinstance(registered_at, dict)
        else None,
        "registered_as": entity.get("registeredAs"),
        "creation_date": entity.get("creationDate"),
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "name", "label", "text", "en"):
            if key in value:
                return _scalar(value[key])
        if len(value) == 1:
            return _scalar(next(iter(value.values())))
        return None
    if isinstance(value, list):
        if not value:
            return None
        return _scalar(value[0])
    text = str(value).strip()
    return text or None


def _strings(value: Any) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict) and not any(
            k in item for k in ("value", "name", "label", "text", "en")
        ):
            for nested in item.values():
                val = _scalar(nested)
                if val:
                    out.append(val)
        else:
            val = _scalar(item)
            if val:
                out.append(val)
    return list(dict.fromkeys(out))


def _decimal(value: Any) -> Decimal | None:
    val = _scalar(value)
    if not val:
        return None
    try:
        return Decimal(val.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    val = _scalar(value)
    if not val:
        return None
    for candidate in (val, val[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def extract_ted_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("notices", "results", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested_key in ("notices", "results", "items"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
    return []


@dataclass(frozen=True)
class TedNoticeObservation:
    publication_number: str
    notice_title: str
    procedure_identifier: str | None
    publication_date: date | None
    buyer_names: list[str]
    buyer_identifiers: list[str]
    buyer_countries: list[str]
    winner_names: list[str]
    winner_identifiers: list[str]
    winner_countries: list[str]
    decision_date: date | None
    total_value: Decimal | None
    currency: str | None


def parse_ted_notice(row: dict[str, Any]) -> TedNoticeObservation | None:
    publication_number = _scalar(row.get("publication-number")) or _scalar(
        row.get("notice-identifier")
    )
    if not publication_number:
        return None
    title = (
        _scalar(row.get("notice-title"))
        or _scalar(row.get("title-proc"))
        or f"TED notice {publication_number}"
    )
    total_value = _decimal(row.get("result-value-notice"))
    if total_value is None:
        total_value = _decimal(row.get("total-value"))
    currency = _scalar(row.get("result-value-cur-notice")) or _scalar(row.get("total-value-cur"))
    if currency:
        currency = currency.upper()[:3]
    return TedNoticeObservation(
        publication_number=publication_number,
        notice_title=title,
        procedure_identifier=_scalar(row.get("procedure-identifier")),
        publication_date=_date(row.get("publication-date")),
        buyer_names=_strings(row.get("buyer-name")),
        buyer_identifiers=_strings(row.get("buyer-identifier")),
        buyer_countries=_strings(row.get("buyer-country")),
        winner_names=_strings(row.get("winner-name")),
        winner_identifiers=_strings(row.get("winner-identifier")),
        winner_countries=_strings(row.get("winner-country")),
        decision_date=_date(row.get("winner-decision-date")),
        total_value=total_value,
        currency=currency,
    )


def pair_entities(
    names: list[str], identifiers: list[str], countries: list[str]
) -> list[dict[str, str | None]]:
    size = max(len(names), len(identifiers), len(countries), 0)
    if size == 0:
        return []
    out: list[dict[str, str | None]] = []
    for i in range(size):
        name = names[i] if i < len(names) else None
        identifier = identifiers[i] if i < len(identifiers) else None
        country = countries[i] if i < len(countries) else None
        if name or identifier:
            out.append({"name": name, "identifier": identifier, "country": country})
    return out


RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

CELLAR_RELATION_MAP = {
    "cites": "CITES",
    "cited_by": "CITED_BY",
    "work_cited_by_work": "CITED_BY",
    "amends": "AMENDS",
    "amended_by": "AMENDED_BY",
    "corrects": "CORRECTS",
    "corrected_by": "CORRECTED_BY",
    "resource_legal_corrected_by_resource_legal": "CORRECTED_BY",
    "resource_legal_corrects_resource_legal": "CORRECTS",
    "resource_legal_amended_by_resource_legal": "AMENDED_BY",
    "resource_legal_amends_resource_legal": "AMENDS",
    "basis_for": "BASIS_FOR",
    "based_on": "BASED_ON",
    "resource_legal_basis_for_resource_legal": "BASIS_FOR",
    "work_amends_work": "AMENDS",
    "work_is_amended_by_work": "AMENDED_BY",
    "work_cites_work": "CITES",
    "work_is_cited_by_work": "CITED_BY",
    "resource_legal_based_on_resource_legal": "BASED_ON",
    "resource_legal_is_basis_for_resource_legal": "BASIS_FOR",
    "work_is_logical_successor_of_work": "SUCCESSOR_OF",
    "work_has_logical_successor_work": "HAS_SUCCESSOR",
    "work_corrects_work": "CORRECTS",
    "work_is_corrected_by_work": "CORRECTED_BY",
}


def _cellar_relation(local: str) -> str | None:
    return CELLAR_RELATION_MAP.get(local)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if "#" in tag:
        return tag.rsplit("#", 1)[1]
    return tag.rsplit("/", 1)[-1]


def celex_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    marker = "/resource/celex/"
    if marker not in uri:
        return None
    tail = unquote(uri.split(marker, 1)[1]).split("?", 1)[0].split("#", 1)[0].strip("/")
    return tail or None


def parse_cellar_legal_relations(rdf_xml: str, subject_celex: str) -> list[tuple[str, str]]:
    relations = []
    try:
        context = ET.iterparse(StringIO(rdf_xml), events=("start", "end"))
        depth, root = 0, None
        for event, node in context:
            if event == "start":
                depth += 1
                if root is None:
                    root = node
                continue
            if depth == 2:
                about = node.attrib.get(f"{{{RDF_NS}}}about")
                aliases = [
                    v.attrib.get(f"{{{RDF_NS}}}resource")
                    for v in node
                    if v.tag == "{http://www.w3.org/2002/07/owl#}sameAs"
                ]
                matches = celex_from_uri(about) == subject_celex or any(
                    celex_from_uri(v) == subject_celex for v in aliases
                )
                if matches:
                    for element in node:
                        if not element.tag.startswith(
                            "{http://publications.europa.eu/ontology/cdm#}"
                        ):
                            continue
                        relation = _cellar_relation(_local_name(element.tag))
                        target = celex_from_uri(element.attrib.get(f"{{{RDF_NS}}}resource"))
                        if relation and target and target != subject_celex:
                            relations.append((relation, target))
                node.clear()
                root.clear()
            depth -= 1
    except ET.ParseError as exc:
        raise ValueError("invalid Cellar RDF/XML") from exc

    return list(dict.fromkeys(relations))
