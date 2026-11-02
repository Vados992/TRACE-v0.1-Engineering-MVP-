"""Local deterministic screening tests, including a published real-world audit excerpt."""
import json
from datetime import date
from pathlib import Path

import pytest
from app.account_engine import (
    EvidenceRef,
    Observation,
    ProjectAssessmentInput,
    assess,
    from_evidence_x_source,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def base():
    return ProjectAssessmentInput(
        project_id="DEMO-1", title="Demonstration project", jurisdiction="PT",
        evidence=[EvidenceRef(id="doc", url="https://www.eca.europa.eu/a.pdf", locator="p. 1")],
        observations=[Observation(kind="original_budget", value="100", unit="EUR", evidence_id="doc"),
                      Observation(kind="paid_total", value="160", unit="EUR", evidence_id="doc")],
    )


def test_over_budget_is_not_a_criminal_verdict():
    result = assess(base())
    assert result.metrics["budget_variance_percent"] == "60.00"
    assert result.metrics["budget_variance_amount"] == "60"
    assert "PAYMENTS_ABOVE_BUDGET" in {s.code for s in result.signals}
    assert result.review_state == "ANALYTICAL_LEAD_ONLY"


def test_hash_stable_and_mutation_sensitive():
    obj = base()
    original = assess(obj).input_sha256
    assert original == assess(obj).input_sha256
    obj.observations[1].value = "159"
    assert assess(obj).input_sha256 != original


def test_missing_payment_not_assumed_zero():
    obj = base()
    obj.observations = obj.observations[:1]
    result = assess(obj)
    assert result.metrics["budget_variance_percent"] is None
    assert "MISSING_BUDGET_OR_PAYMENTS" in {s.code for s in result.signals}


def test_incompatible_period_blocks_math():
    obj = base()
    obj.observations[0] = Observation(kind="original_budget", value="100", unit="EUR",
        evidence_id="doc", period_start=date(2020, 1, 1), period_end=date(2020, 12, 31))
    result = assess(obj)
    assert result.metrics["budget_variance_amount"] is None
    assert "INCOMPARABLE_BUDGET_PERIOD" in {s.code for s in result.signals}


def test_unanchored_numbers_rejected():
    data = base().model_dump(mode="json")
    data["observations"][0]["evidence_id"] = "missing"
    with pytest.raises(ValidationError):
        ProjectAssessmentInput.model_validate(data)


def test_non_https_evidence_rejected():
    with pytest.raises(ValidationError):
        EvidenceRef(id="bad", url="http://127.0.0.1/private", locator="section 1")


def test_duplicate_metric_rejected():
    data = base().model_dump(mode="json")
    data["observations"].append(data["observations"][0])
    with pytest.raises(ValidationError):
        ProjectAssessmentInput.model_validate(data)


def test_external_evidence_x_bridge_stays_unverified():
    row = {"id": "abc123", "source_url": "https://www.eca.europa.eu/example.pdf",
           "sha256": "f" * 64, "status": "retrieved"}
    ev = from_evidence_x_source(row, "EVIDENCE-X /sources abc123")
    assert ev.evidence_x_source_id == "abc123"
    assert ev.verification == "unverified"
    assert ev.sha256 == "f" * 64


def test_real_eca_kastoria_2014():
    """Real *published* figures, manually transcribed; NOT live-provider/API integration."""
    fixture = ROOT / "fixtures/accountability/kastoria_eca2014.json"
    source = ProjectAssessmentInput.model_validate(json.loads(fixture.read_text()))
    result = assess(source)
    assert result.metrics["operating_gap_amount"] == "7524000"
    assert result.metrics["budget_variance_amount"] is None
    assert "OPERATING_COST_EXCEEDS_REVENUE" in {s.code for s in result.signals}
    assert "NO_DECISION_CHAIN" in {s.code for s in result.signals}
    assert not any("crime" in x.code.lower() for x in result.signals)


def test_output_below_target():
    obj = base()
    obj.observations.extend([
        Observation(kind="target_output", value="100", unit="PASSENGERS", evidence_id="doc"),
        Observation(kind="actual_output", value="15", unit="PASSENGERS", evidence_id="doc"),
    ])
    result = assess(obj)
    assert result.metrics["target_realization_percent"] == "15.00"
    assert "LOW_TARGET_REALIZATION" in {s.code for s in result.signals}


def test_real_eca_cordoba_forecast_2013():
    """Real published forecast-vs-observed data, not a live source connection."""
    fixture = ROOT / "fixtures/accountability/cordoba_eca2014.json"
    source = ProjectAssessmentInput.model_validate(json.loads(fixture.read_text()))
    result = assess(source)
    assert result.metrics["target_realization_percent"] == "3.89"
    assert "LOW_TARGET_REALIZATION" in {s.code for s in result.signals}
    assert result.metrics["budget_variance_amount"] is None
