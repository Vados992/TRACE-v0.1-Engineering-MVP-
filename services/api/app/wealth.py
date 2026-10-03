"""Deterministic balance bridge in one currency; a residual is a review signal."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator

from .adapters import StrictModel

ENGINE_VERSION = "wealth-bridge/1"
COMPONENTS = (
    "opening_net_worth",
    "closing_net_worth",
    "income",
    "gifts",
    "realized_gains",
    "unrealized_gains",
    "expenses",
    "taxes",
    "other_net",
)


class WealthInput(StrictModel):
    entity_id: UUID
    dataset_id: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    opening_net_worth: Decimal | None = Field(default=None, max_digits=24, decimal_places=6)
    closing_net_worth: Decimal | None = Field(default=None, max_digits=24, decimal_places=6)
    income: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=6)
    gifts: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=6)
    realized_gains: Decimal | None = Field(default=None, max_digits=24, decimal_places=6)
    unrealized_gains: Decimal | None = Field(default=None, max_digits=24, decimal_places=6)
    expenses: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=6)
    taxes: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=6)
    other_net: Decimal | None = Field(default=None, max_digits=24, decimal_places=6)
    tolerance: Decimal = Field(default=Decimal("0.01"), ge=0, max_digits=24, decimal_places=6)
    license: str = Field(min_length=1, max_length=1000)
    legal_basis: str = Field(min_length=1, max_length=2000)
    locators: dict[str, str] = Field(default_factory=dict)
    demo: bool = False

    @model_validator(mode="after")
    def dates_and_provenance(self):
        if self.period_end <= self.period_start:
            raise ValueError("period_end must follow period_start")
        supplied = [key for key in COMPONENTS if getattr(self, key) is not None]
        if any(not self.locators.get(key) for key in supplied):
            raise ValueError("Each supplied component needs a source locator")
        return self


def reconcile(data: WealthInput) -> dict:
    missing = [name for name in COMPONENTS if getattr(data, name) is None]
    base = {
        "engine_version": ENGINE_VERSION,
        "currency": data.currency,
        "missing_components": missing,
        "is_legal_conclusion": False,
        "warnings": [
            "One currency only; no implicit FX, inflation adjustment or missing-value imputation",
            "A discrepancy does not establish wrongdoing; verify valuations and source completeness",
        ],
        "formula": "closing - opening - (income + gifts + realized_gains + unrealized_gains - expenses - taxes + other_net)",
    }
    if missing:
        return {
            **base,
            "status": "INCOMPLETE",
            "residual": None,
            "expected_closing_net_worth": None,
        }
    expected = (
        data.opening_net_worth
        + data.income
        + data.gifts
        + data.realized_gains
        + data.unrealized_gains
        - data.expenses
        - data.taxes
        + data.other_net
    )
    residual = data.closing_net_worth - expected
    return {
        **base,
        "status": "RECONCILED" if abs(residual) <= data.tolerance else "REVIEW_REQUIRED",
        "residual": str(residual),
        "expected_closing_net_worth": str(expected),
        "tolerance": str(data.tolerance),
        "demo": data.demo,
    }
