"""TRACE-ACCOUNT v0.1: deterministic, source-anchored public investment screening.

No legal conclusions. No inference of personal liability. Money flows are not
interchangeable: commitments, awards, payments, operating costs and revenues
are distinct measurements.

Copyright (c) 2026 Vadym Tsinderhoz. All rights reserved.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


Kind = Literal[
    "original_budget", "revised_budget", "awarded_total", "paid_total",
    "target_output", "actual_output", "operating_cost", "operating_revenue",
    "investment_amount", "eu_funding",
]
MONEY = {
    "original_budget", "revised_budget", "awarded_total", "paid_total",
    "operating_cost", "operating_revenue", "investment_amount", "eu_funding",
}


class EvidenceRef(Strict):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_:.\-]+$")
    url: str = Field(max_length=2048)
    locator: str = Field(min_length=2, max_length=500)
    # A caller's classification is not proof of independent verification.
    declared_type: Literal["official", "other", "external_evidence_x"] = "other"
    verification: Literal["unverified", "human_checked"] = "unverified"
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trace_source_record_id: UUID | None = None
    evidence_x_source_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def safe_url(self):
        u = urlsplit(self.url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.port or any(ord(x) < 32 for x in self.url)):
            raise ValueError("Evidence URL must be HTTPS with no credentials or port")
        return self


class Observation(Strict):
    kind: Kind
    value: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    unit: str = Field(min_length=3, max_length=16, pattern=r"^[A-Z][A-Z0-9_]*$")
    evidence_id: str
    period_start: date | None = None
    period_end: date | None = None

    @model_validator(mode="after")
    def validate_unit_period(self):
        if self.kind in MONEY and not re.fullmatch(r"[A-Z]{3}", self.unit):
            raise ValueError("Monetary observations need ISO 4217-style currency")
        if self.kind not in MONEY and self.unit in {"EUR", "USD", "GBP"}:
            raise ValueError("Output observations require a non-currency unit")
        if bool(self.period_start) != bool(self.period_end):
            raise ValueError("Observation periods require both boundaries")
        if self.period_start and self.period_end < self.period_start:
            raise ValueError("Period end must not precede start")
        return self


class DecisionLink(Strict):
    role_title: str = Field(min_length=2, max_length=200)
    act_reference: str = Field(min_length=2, max_length=250)
    action: str = Field(min_length=5, max_length=500)
    evidence_id: str
    # No asserted personal guilt, private personal attributes, or automatic scoring.


class ProjectAssessmentInput(Strict):
    project_id: str = Field(min_length=2, max_length=160)
    title: str = Field(min_length=3, max_length=500)
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    source_system: Literal["manual", "oc4ids", "trace", "evidence_x"] = "manual"
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=100)
    observations: list[Observation] = Field(min_length=1, max_length=100)
    decisions: list[DecisionLink] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def verify_refs(self):
        ids = [x.id for x in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evidence ID")
        references = set(ids)
        if any(o.evidence_id not in references for o in self.observations):
            raise ValueError("Each observation must cite included evidence")
        if any(d.evidence_id not in references for d in self.decisions):
            raise ValueError("Each decision must cite included evidence")
        keys = [o.kind for o in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("Ambiguous duplicate metric; supply one scoped observation per kind")
        return self


class Signal(Strict):
    code: str
    description: str
    evidence_ids: list[str]
    interpretation: Literal["review_required", "insufficient_data"]


class AssessmentResult(Strict):
    engine: str = "trace-account-0.1.0"
    input_sha256: str
    project_id: str
    metrics: dict[str, str | None]
    signals: list[Signal]
    evidence_count: int
    decision_count: int
    review_state: Literal["ANALYTICAL_LEAD_ONLY"] = "ANALYTICAL_LEAD_ONLY"
    limitations: list[str] = Field(default_factory=lambda: [
        "A signal is not evidence of illegality, causation, personal culpability, or fiscal damage.",
        "Declared official sources and imported external IDs are not independently verified by this engine.",
        "Missing values are unknown, never treated as zero; no automatic publication or sanctions.",
    ])


def canonical_digest(payload: ProjectAssessmentInput) -> str:
    blob = json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def assess(data: ProjectAssessmentInput) -> AssessmentResult:
    """Screen a source-anchored project without a normative guilt or corruption score."""
    obs = {o.kind: o for o in data.observations}
    metrics: dict[str, str | None] = {
        "budget_variance_amount": None, "budget_variance_percent": None,
        "target_realization_percent": None, "operating_gap_amount": None,
    }
    signals: list[Signal] = []

    def compatible(a: Observation, b: Observation) -> bool:
        return (a.unit == b.unit and a.period_start == b.period_start
                and a.period_end == b.period_end)

    def flag(code: str, message: str, group: list[Observation], status="review_required"):
        signals.append(Signal(code=code, description=message,
                              evidence_ids=list(dict.fromkeys(x.evidence_id for x in group)),
                              interpretation=status))

    baseline = obs.get("revised_budget") or obs.get("original_budget")
    paid = obs.get("paid_total")
    if baseline and paid:
        if compatible(baseline, paid):
            delta = paid.value - baseline.value
            metrics["budget_variance_amount"] = str(delta)
            if baseline.value > 0:
                metrics["budget_variance_percent"] = str(
                    (delta / baseline.value * 100).quantize(Decimal("0.01"))
                )
            if delta > 0:
                flag("PAYMENTS_ABOVE_BUDGET", "Payments exceed the documented budget baseline; examine approved scope and amendments.", [baseline, paid])
        else:
            flag("INCOMPARABLE_BUDGET_PERIOD", "Budget and payment currency or periods differ; no variance calculated.", [baseline, paid], "insufficient_data")
    elif paid or baseline:
        flag("MISSING_BUDGET_OR_PAYMENTS", "Budget-to-payment variance cannot be calculated from available observations.", [x for x in (baseline, paid) if x], "insufficient_data")

    expected, actual = obs.get("target_output"), obs.get("actual_output")
    if expected and actual:
        if compatible(expected, actual) and expected.value > 0:
            ratio = (actual.value / expected.value * 100).quantize(Decimal("0.01"))
            metrics["target_realization_percent"] = str(ratio)
            if ratio < 75:
                flag("LOW_TARGET_REALIZATION", "Observed output is below 75% of the specified target; investigate causes.", [expected, actual])
        else:
            flag("INCOMPARABLE_OUTPUT", "Target and actual output are not comparable or target is zero.", [expected, actual], "insufficient_data")

    cost, income = obs.get("operating_cost"), obs.get("operating_revenue")
    if cost and income:
        if compatible(cost, income):
            gap = cost.value - income.value
            metrics["operating_gap_amount"] = str(gap)
            if gap > 0:
                flag("OPERATING_COST_EXCEEDS_REVENUE", "Operating cost exceeds reported revenue; social benefits and public-service mandate are not measured.", [cost, income])
        else:
            flag("INCOMPARABLE_OPERATING_PERIOD", "Costs and revenue cover different periods/currencies.", [cost, income], "insufficient_data")

    if not data.decisions:
        signals.append(Signal(code="NO_DECISION_CHAIN", description="No sourced decision links provided; do not infer individual responsibility.", evidence_ids=[], interpretation="insufficient_data"))
    if not any(e.verification == "human_checked" for e in data.evidence):
        signals.append(Signal(code="EVIDENCE_UNREVIEWED", description="Source assertions have not been independently checked by a reviewer.", evidence_ids=[], interpretation="insufficient_data"))

    return AssessmentResult(input_sha256=canonical_digest(data), project_id=data.project_id,
                            metrics=metrics, signals=signals, evidence_count=len(data.evidence),
                            decision_count=len(data.decisions))


def from_evidence_x_source(record: dict, locator: str) -> EvidenceRef:
    """Read-only metadata bridge; EVIDENCE-X source entries are never auto-trusted."""
    for key in ("id", "source_url", "sha256"):
        if not record.get(key):
            raise ValueError(f"EVIDENCE-X source missing: {key}")
    return EvidenceRef(id=f"ex:{record['id']}", url=record["source_url"],
                       locator=locator, declared_type="external_evidence_x",
                       sha256=record["sha256"], evidence_x_source_id=str(record["id"]),
                       verification="unverified")
