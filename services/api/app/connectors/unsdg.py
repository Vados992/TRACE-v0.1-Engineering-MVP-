"""Official United Nations Statistics Division SDG API connector.

The connector never fabricates observations and refuses silently-truncated queries.
Every response is bounded by BaseConnector and the service persists the returned bytes
inside the Evidence Vault before calculation or verification.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .base import BaseConnector, ConnectorError


class UnSdgConnector(BaseConnector):
    source_code = "UN_SDG"

    def __init__(self, base_url: str, timeout: float = 30.0):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or parsed.hostname != "unstats.un.org":
            raise ConnectorError("UN SDG connector must use the official unstats.un.org HTTPS API")
        if not parsed.path.rstrip("/").lower().endswith("/sdgapi"):
            raise ConnectorError("UN SDG connector base URL must end with /SDGAPI")
        super().__init__(base_url, timeout)

    async def series_list(self) -> list[dict[str, Any]]:
        response = await self.request(
            "GET",
            self.base_url + "/v1/sdg/Series/List",
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ConnectorError("UN SDG series endpoint returned an unexpected schema")
        return payload

    async def series_data(
        self,
        *,
        series_code: str,
        area_codes: list[int] | None = None,
        time_period_start: int | None = None,
        time_period_end: int | None = None,
        page_size: int = 1000,
        max_pages: int = 20,
    ) -> dict[str, Any]:
        if not series_code or len(series_code) > 100:
            raise ConnectorError("Invalid UN SDG series code")
        if page_size < 1 or page_size > 5000:
            raise ConnectorError("UN SDG page_size must be between 1 and 5000")
        if max_pages < 1 or max_pages > 100:
            raise ConnectorError("UN SDG max_pages must be between 1 and 100")
        if area_codes and (len(area_codes) > 250 or any(code < 0 or code > 999 for code in area_codes)):
            raise ConnectorError("Invalid or excessive UN M49 area codes")
        if (
            time_period_start is not None
            and time_period_end is not None
            and time_period_end < time_period_start
        ):
            raise ConnectorError("UN SDG time period end precedes start")

        observations: list[dict[str, Any]] = []
        page = 1
        total_pages: int | None = None
        total_elements: int | None = None
        schema: dict[str, Any] = {"attributes": [], "dimensions": []}

        while True:
            params: list[tuple[str, Any]] = [
                ("seriesCode", series_code),
                ("page", page),
                ("pageSize", page_size),
            ]
            for area in area_codes or []:
                params.append(("areaCode", area))
            if time_period_start is not None:
                params.append(("timePeriodStart", time_period_start))
            if time_period_end is not None:
                params.append(("timePeriodEnd", time_period_end))

            response = await self.request(
                "GET",
                self.base_url + "/v1/sdg/Series/Data",
                params=params,
                headers={"Accept": "application/json"},
            )
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ConnectorError("UN SDG data endpoint returned an unexpected schema")

            current_page = int(payload.get("pageNumber") or page)
            reported_pages = int(payload.get("totalPages") or 0)
            reported_total = int(payload.get("totalElements") or len(payload["data"]))
            if current_page != page:
                raise ConnectorError("UN SDG pagination response does not match requested page")
            if total_pages is None:
                total_pages = max(reported_pages, 1)
                total_elements = reported_total
                schema = {
                    "attributes": payload.get("attributes") or [],
                    "dimensions": payload.get("dimensions") or [],
                }
                if total_pages > max_pages:
                    raise ConnectorError(
                        "UN SDG query exceeds the configured complete-query page bound; narrow filters"
                    )
            elif total_pages != max(reported_pages, 1) or total_elements != reported_total:
                raise ConnectorError("UN SDG pagination metadata changed during retrieval")

            for row in payload["data"]:
                if not isinstance(row, dict):
                    raise ConnectorError("UN SDG observation is not a JSON object")
                if row.get("series") not in (None, series_code):
                    raise ConnectorError("UN SDG response contains an unexpected series")
                observations.append(row)

            if page >= total_pages:
                break
            page += 1

        if total_elements is not None and len(observations) != total_elements:
            raise ConnectorError(
                f"UN SDG complete-query invariant failed: expected {total_elements}, got {len(observations)}"
            )

        return {
            "series_code": series_code,
            "total_elements": len(observations),
            "total_pages": total_pages or 1,
            "attributes": schema["attributes"],
            "dimensions": schema["dimensions"],
            "data": observations,
        }
