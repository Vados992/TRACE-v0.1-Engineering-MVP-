from decimal import Decimal

import pytest
from app.statistical_verification import (
    CrossSourceInput,
    CrossSourceVerificationRequest,
    SemanticContract,
    StatisticalCalculation,
    recalculate_statistical,
)
from pydantic import ValidationError


def test_generic_recalculation_handles_nonannual_periods_and_decimal_values():
    rows = [
        {
            "geo_code": "PRT",
            "period": "2024-Q1",
            "value": "100.0",
            "dimensions": {"sex": "T"},
            "attributes": {"status": "A"},
        },
        {
            "geo_code": "PRT",
            "period": "2024-Q2",
            "value": "116.0",
            "dimensions": {"sex": "T"},
            "attributes": {"status": "A"},
        },
        {
            "geo_code": "ESP",
            "period": "2024-Q2",
            "value": "<1",
            "dimensions": {"sex": "T"},
            "attributes": {"status": "A"},
        },
    ]
    result = recalculate_statistical(
        rows,
        StatisticalCalculation(
            operation="percent_change",
            dimension_filters={"sex": "T"},
            baseline_period="2024-Q1",
            comparison_period="2024-Q2",
            aggregation="sum",
        ),
    )
    assert Decimal(result["result"]) == Decimal("16")
    assert result["numeric_observations_used"] == 2


def test_generic_recalculation_counts_geographies_without_inventing_missing_codes():
    rows = [
        {"geo_code": "PRT", "period": "2024", "value": "1"},
        {"geo_code": "ESP", "period": "2024", "value": "2"},
        {"geo_code": None, "period": "2024", "value": "3"},
    ]
    result = recalculate_statistical(
        rows, StatisticalCalculation(operation="count_distinct_geographies")
    )
    assert result["result"] == "2"


def test_cross_source_contract_requires_distinct_providers():
    contract = SemanticContract(
        concept_id="population.total",
        label="Resident population",
        unit="persons",
        frequency="A",
        geography_scope="Portugal",
        period_start="2024",
        period_end="2024",
        transformation="level",
        comparability_note=(
            "Operator confirms that each selected source represents the same annual "
            "resident-population concept and geography."
        ),
    )
    source = CrossSourceInput(
        provider="WORLD_BANK",
        query={"indicator": "SP.POP.TOTL", "countries": ["PRT"]},
        calculation=StatisticalCalculation(operation="mean_values"),
        mapping_note="World Bank population indicator mapped to the declared concept.",
    )
    with pytest.raises(ValidationError, match="unique providers"):
        CrossSourceVerificationRequest(
            sources=[source, source],
            semantic_contract=contract,
            asserted_value=Decimal("1"),
            assertion_text="Population equals one person in this synthetic validation input.",
            legal_basis="Internal technical validation of public statistical data",
        )


def test_qualified_values_are_not_silently_numeric():
    rows = [
        {"geo_code": "A", "period": "2024", "value": "<0.1"},
        {"geo_code": "B", "period": "2024", "value": "2.50"},
    ]
    result = recalculate_statistical(
        rows, StatisticalCalculation(operation="sum_values")
    )
    assert result["result"] == "2.5"
    assert result["numeric_observations_used"] == 1
