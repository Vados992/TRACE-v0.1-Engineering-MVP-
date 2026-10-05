from decimal import Decimal

import httpx
import pytest
from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.unsdg import UnSdgConnector
from app.sdg_verification import RecalculationSpec, recalculate


@pytest.mark.asyncio
async def test_unsdg_fetches_every_page_and_rejects_partial_queries(monkeypatch):
    factory = httpx.AsyncClient

    def responder(request):
        page = int(request.url.params.get("page", "1"))
        rows = {
            1: [
                {
                    "series": "TEST_SERIES",
                    "geoAreaCode": "620",
                    "geoAreaName": "Portugal",
                    "timePeriodStart": 2020,
                    "value": "100",
                },
                {
                    "series": "TEST_SERIES",
                    "geoAreaCode": "724",
                    "geoAreaName": "Spain",
                    "timePeriodStart": 2020,
                    "value": "200",
                },
            ],
            2: [
                {
                    "series": "TEST_SERIES",
                    "geoAreaCode": "620",
                    "geoAreaName": "Portugal",
                    "timePeriodStart": 2021,
                    "value": "116",
                }
            ],
        }[page]
        return httpx.Response(
            200,
            json={
                "size": len(rows),
                "totalElements": 3,
                "totalPages": 2,
                "pageNumber": page,
                "attributes": [],
                "dimensions": [],
                "data": rows,
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(responder), **kw)
    )

    async def accepted(url):
        assert str(url).startswith("https://unstats.un.org/")

    monkeypatch.setattr(BaseConnector, "validate_url", staticmethod(accepted))
    connector = UnSdgConnector("https://unstats.un.org/SDGAPI")
    payload = await connector.series_data(series_code="TEST_SERIES", page_size=2, max_pages=2)
    assert payload["total_elements"] == 3
    assert len(payload["data"]) == 3
    assert len(connector.responses) == 2

    bounded = UnSdgConnector("https://unstats.un.org/SDGAPI")
    with pytest.raises(ConnectorError, match="complete-query page bound"):
        await bounded.series_data(series_code="TEST_SERIES", page_size=2, max_pages=1)


def test_recalculation_is_decimal_deterministic_and_filterable():
    rows = [
        {
            "geoAreaCode": "620",
            "timePeriodStart": 2020,
            "value": "100",
            "dimensions": {"Sex": "ALL"},
            "attributes": {"Nature": "C"},
        },
        {
            "geoAreaCode": "620",
            "timePeriodStart": 2021,
            "value": "116",
            "dimensions": {"Sex": "ALL"},
            "attributes": {"Nature": "C"},
        },
        {
            "geoAreaCode": "724",
            "timePeriodStart": 2020,
            "value": "50.5",
            "dimensions": {"Sex": "FEMALE"},
            "attributes": {"Nature": "C"},
        },
        {
            "geoAreaCode": "724",
            "timePeriodStart": 2021,
            "value": "<1",
            "dimensions": {"Sex": "FEMALE"},
            "attributes": {"Nature": "C"},
        },
    ]

    count = recalculate(
        rows,
        RecalculationSpec(
            operation="count_distinct_geographies",
            attribute_filters={"Nature": "C"},
        ),
    )
    assert count["result"] == "2"

    total = recalculate(
        rows,
        RecalculationSpec(
            operation="sum_values",
            dimension_filters={"Sex": "ALL"},
        ),
    )
    assert Decimal(total["result"]) == Decimal("216")

    change = recalculate(
        rows,
        RecalculationSpec(
            operation="percent_change",
            dimension_filters={"Sex": "ALL"},
            baseline_period=2020,
            comparison_period=2021,
            aggregation="sum",
        ),
    )
    assert Decimal(change["result"]) == Decimal("16")


def test_recalculation_does_not_coerce_qualified_or_missing_values():
    rows = [
        {"geoAreaCode": "1", "timePeriodStart": 2024, "value": "<0.1"},
        {"geoAreaCode": "2", "timePeriodStart": 2024, "value": None},
        {"geoAreaCode": "3", "timePeriodStart": 2024, "value": "2.50"},
    ]
    result = recalculate(rows, RecalculationSpec(operation="sum_values"))
    assert result["result"] == "2.5"
    assert result["numeric_observations_used"] == 1


def test_percent_change_zero_baseline_is_explicit():
    rows = [
        {"geoAreaCode": "1", "timePeriodStart": 2020, "value": "0"},
        {"geoAreaCode": "1", "timePeriodStart": 2021, "value": "5"},
    ]
    with pytest.raises(ValueError, match="zero baseline"):
        recalculate(
            rows,
            RecalculationSpec(
                operation="percent_change",
                baseline_period=2020,
                comparison_period=2021,
            ),
        )
