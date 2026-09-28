from app.parsers import extract_html_title, parse_gleif_record


def test_extract_html_title():
    assert (
        extract_html_title("<html><head><title> Regulation  Test </title></head></html>")
        == "Regulation Test"
    )


def test_parse_gleif_record():
    payload = {
        "data": {
            "id": "529900TESTTESTTEST00",
            "attributes": {
                "entity": {
                    "legalName": {"name": "Example AG"},
                    "legalJurisdiction": "DE",
                    "status": "ACTIVE",
                    "legalAddress": {"country": "DE"},
                }
            },
        }
    }
    parsed = parse_gleif_record(payload)
    assert parsed["lei"] == "529900TESTTESTTEST00"
    assert parsed["legal_name"] == "Example AG"
    assert parsed["jurisdiction"] == "DE"
