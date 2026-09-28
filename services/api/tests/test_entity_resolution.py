from datetime import date

from app.entity_resolution.scorer import score_records
from app.models import ResolutionRecord


def org(**kwargs):
    return ResolutionRecord(entity_type="ORGANIZATION", **kwargs)


def test_exact_lei_auto_merge():
    left = org(name="Example AG", jurisdiction_code="DE", identifiers={"LEI": "529900TESTTESTTEST00"})
    right = org(name="Example Aktiengesellschaft", jurisdiction_code="DE", identifiers={"LEI": "529900TESTTESTTEST00"})
    result = score_records(left, right)
    assert result.decision == "AUTO_MERGE"
    assert result.score >= 0.98


def test_conflicting_lei_blocks_merge():
    left = org(name="Example AG", identifiers={"LEI": "AAA"})
    right = org(name="Example AG", identifiers={"LEI": "BBB"})
    result = score_records(left, right)
    assert result.decision == "KEEP_SEPARATE"


def test_org_similarity_can_trigger_review():
    left = org(
        name="Acme Holdings GmbH",
        jurisdiction_code="DE",
        address="Unter den Linden 1 Berlin",
        directors=["Anna Example"],
        incorporation_date=date(2020, 1, 2),
    )
    right = org(
        name="ACME Holdings",
        jurisdiction_code="DE",
        address="Unter den Linden 1, Berlin",
        directors=["Anna Example"],
        incorporation_date=date(2020, 1, 2),
    )
    result = score_records(left, right)
    assert result.score >= 0.90
    assert result.decision in {"HUMAN_REVIEW", "AUTO_MERGE"}


def test_person_name_only_never_auto_merges():
    left = ResolutionRecord(entity_type="PERSON", name="John Smith", jurisdiction_code="GB")
    right = ResolutionRecord(entity_type="PERSON", name="John Smith", jurisdiction_code="GB")
    result = score_records(left, right)
    assert result.decision != "AUTO_MERGE"
