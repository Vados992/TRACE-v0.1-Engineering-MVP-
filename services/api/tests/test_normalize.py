from app.entity_resolution.normalize import normalize_identifier, normalize_org_name, normalize_text


def test_org_suffix_removed():
    assert normalize_org_name("Example Holdings GmbH") == "example holdings"


def test_identifier_normalization():
    assert normalize_identifier("DE-123 456") == "DE123456"


def test_unicode_normalization():
    assert normalize_text("  Société   Générale  ") == "société générale"
