from decimal import Decimal

from app.parsers import (
    celex_from_uri,
    pair_entities,
    parse_cellar_legal_relations,
    parse_gleif_record,
    parse_ted_notice,
)
from app.relationship_semantics import semantic_key
from uuid import UUID
from datetime import datetime, timezone


def test_parse_ted_notice_fields():
    row = {
        "publication-number": "123456-2026",
        "notice-title": "Framework award",
        "procedure-identifier": "PROC-9",
        "publication-date": "2026-09-10",
        "buyer-name": ["Agency A"],
        "buyer-identifier": ["BUY-1"],
        "buyer-country": ["PT"],
        "winner-name": ["Supplier SA"],
        "winner-identifier": ["500000000"],
        "winner-country": ["PT"],
        "winner-decision-date": "2026-09-01",
        "result-value-notice": "1250000.50",
        "result-value-cur-notice": "EUR",
    }
    notice = parse_ted_notice(row)
    assert notice is not None
    assert notice.publication_number == "123456-2026"
    assert notice.buyer_names == ["Agency A"]
    assert notice.winner_names == ["Supplier SA"]
    assert notice.total_value == Decimal("1250000.50")
    assert notice.currency == "EUR"


def test_pair_entities_is_positional_not_cartesian():
    parties = pair_entities(
        ["A", "B"],
        ["ID-A", "ID-B"],
        ["DE", "FR"],
    )
    assert parties == [
        {"name": "A", "identifier": "ID-A", "country": "DE"},
        {"name": "B", "identifier": "ID-B", "country": "FR"},
    ]


def test_cellar_relation_allowlist():
    rdf = '''<?xml version="1.0"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns:cdm="http://publications.europa.eu/ontology/cdm#">
      <rdf:Description rdf:about="http://publications.europa.eu/resource/celex/32026R0001">
        <cdm:work_amends_work rdf:resource="http://publications.europa.eu/resource/celex/32020R0002"/>
        <cdm:unknown_relation rdf:resource="http://publications.europa.eu/resource/celex/32019R0003"/>
      </rdf:Description>
    </rdf:RDF>'''
    relations = parse_cellar_legal_relations(rdf, "32026R0001")
    assert relations == [("AMENDS", "32020R0002")]


def test_celex_from_uri():
    assert (
        celex_from_uri("http://publications.europa.eu/resource/celex/32016R0679")
        == "32016R0679"
    )
    assert celex_from_uri("https://example.com/no-celex") is None


def test_gleif_parser_registration_authority_fields():
    payload = {
        "data": {
            "id": "529900TESTTESTTEST00",
            "attributes": {
                "entity": {
                    "legalName": {"name": "Example AG"},
                    "legalJurisdiction": "DE",
                    "registeredAt": {"id": "RA000123"},
                    "registeredAs": "HRB 12345",
                    "legalAddress": {"country": "DE"},
                }
            },
        }
    }
    record = parse_gleif_record(payload)
    assert record["registration_authority_id"] == "RA000123"
    assert record["registered_as"] == "HRB 12345"


def test_semantic_key_is_source_independent_and_stable():
    a = UUID("00000000-0000-0000-0000-000000000001")
    b = UUID("00000000-0000-0000-0000-000000000002")
    first = semantic_key(a, "OWNS", b)
    second = semantic_key(a, "OWNS", b)
    assert first == second
    assert len(first) == 64


def test_semantic_key_distinguishes_periods():
    a = UUID("00000000-0000-0000-0000-000000000001")
    b = UUID("00000000-0000-0000-0000-000000000002")
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert semantic_key(a, "MET_WITH", b, t1) != semantic_key(a, "MET_WITH", b, t2)
