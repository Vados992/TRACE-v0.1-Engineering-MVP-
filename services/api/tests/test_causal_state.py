from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.causal_state import (
    REALITY_BRANCH_ID,
    CausalLinkRequest,
    EventCreateRequest,
    StateSeedRequest,
    apply_merge_patch,
    canonical_hash,
)
from pydantic import ValidationError


def utc():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_canonical_hash_is_order_independent_for_objects():
    assert canonical_hash({"b": 2, "a": {"y": 2, "x": 1}}) == canonical_hash(
        {"a": {"x": 1, "y": 2}, "b": 2}
    )


def test_merge_patch_is_deterministic_nested_and_supports_deletion():
    original = {
        "economy": {"debt": 100, "gdp": 200, "inflation": 2.1},
        "policy": "A",
        "unchanged": True,
    }
    patch = {"economy": {"debt": 110, "inflation": None}, "policy": "B"}
    assert apply_merge_patch(original, patch) == {
        "economy": {"debt": 110, "gdp": 200},
        "policy": "B",
        "unchanged": True,
    }
    assert original["economy"]["debt"] == 100


def test_observed_event_requires_source_provenance():
    with pytest.raises(ValidationError):
        EventCreateRequest(
            event_key="evt:test",
            event_type="POLICY_CHANGED",
            epistemic_class="OBSERVED",
            occurred_at=utc(),
        )


def test_simulated_event_cannot_enter_reality_branch():
    with pytest.raises(ValidationError):
        EventCreateRequest(
            event_key="evt:sim",
            event_type="POLICY_CHANGED",
            epistemic_class="SIMULATED",
            branch_id=REALITY_BRANCH_ID,
            occurred_at=utc(),
            model_ref="scenario-engine/test",
        )


def test_derived_event_requires_model_reference():
    with pytest.raises(ValidationError):
        EventCreateRequest(
            event_key="evt:derived",
            event_type="DERIVED_EFFECT",
            epistemic_class="DERIVED",
            occurred_at=utc(),
        )


def test_observed_causal_edge_requires_independent_evidence_reference():
    with pytest.raises(ValidationError):
        CausalLinkRequest(
            cause_event_id=uuid4(),
            effect_event_id=uuid4(),
            edge_type="CAUSES",
            epistemic_class="OBSERVED",
            confidence="0.9",
            rationale="Explicit causal assertion in a source record.",
        )


def test_observed_state_requires_grounding_event():
    with pytest.raises(ValidationError):
        StateSeedRequest(
            entity_id=uuid4(),
            as_of=utc(),
            epistemic_class="OBSERVED",
            state={"debt": 100},
        )
