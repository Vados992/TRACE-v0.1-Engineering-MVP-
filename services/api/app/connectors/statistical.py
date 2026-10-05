"""Official statistical-provider connectors normalized to one observation contract."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from .base import BaseConnector, ConnectorError


@dataclass(frozen=True)
class StatisticalObservation:
    provider_code: str
    dataset_code: str
    series_code: str
    geo_code: str | None
    geo_name: str | None
    period: str
    value: Any
    unit: str | None
    frequency: str | None
    measure: str | None
    dimensions: dict[str, Any]
    attributes: dict[str, Any]
    status: str | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StatisticalSnapshot:
    provider_code: str
    dataset_code: str
    observations: list[StatisticalObservation]
    metadata: dict[str, Any]


class EurostatQuery(BaseModel):
    dataset_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    filters: dict[str, str | list[str]] = Field(default_factory=dict)
    start_period: str | None = Field(default=None, max_length=32)
    end_period: str | None = Field(default=None, max_length=32)
    max_observations: int = Field(default=5000, ge=1, le=50000)


class WorldBankQuery(BaseModel):
    indicator: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    countries: list[str] = Field(min_length=1, max_length=100)
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    source_id: int | None = Field(default=None, ge=1)
    page_size: int = Field(default=1000, ge=1, le=20000)
    max_pages: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_query(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("end_year must be >= start_year")
        for code in self.countries:
            if not re.fullmatch(r"[A-Za-z0-9_-]{2,16}", code):
                raise ValueError("countries contains an invalid World Bank geography code")
        return self


class OecdQuery(BaseModel):
    agency: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    dataflow: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_@.-]+$")
    version: str = Field(default="", max_length=32, pattern=r"^[A-Za-z0-9_.-]*$")
    key: str = Field(default="all", min_length=1, max_length=1000)
    start_period: str | None = Field(default=None, max_length=32)
    end_period: str | None = Field(default=None, max_length=32)
    max_observations: int = Field(default=5000, ge=1, le=50000)


class ImfQuery(BaseModel):
    indicator: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    economies: list[str] = Field(min_length=1, max_length=100)
    periods: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def safe_codes(self):
        for code in [*self.economies, *self.periods]:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", code):
                raise ValueError("IMF query contains an invalid economy or period code")
        return self


class IneSpainQuery(BaseModel):
    table_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    nult: int = Field(default=1, ge=1, le=1000)
    detail: int = Field(default=2, ge=0, le=2)


class OnsUkQuery(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    edition: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    version: int | str = "latest"
    dimension_sets: list[dict[str, str]] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_dimensions(self):
        if isinstance(self.version, str) and self.version != "latest":
            raise ValueError("ONS version must be an integer or 'latest'")
        for dimensions in self.dimension_sets:
            if not dimensions:
                raise ValueError("Each ONS dimension set must contain explicit options")
            if any(value == "*" for value in dimensions.values()):
                raise ValueError("ONS wildcard observations are rejected; request explicit points")
            for key, value in dimensions.items():
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", key):
                    raise ValueError("Invalid ONS dimension name")
                if not re.fullmatch(r"[A-Za-z0-9_ .:+()/,-]{1,160}", value):
                    raise ValueError("Invalid ONS dimension option")
        return self


def _official_host(base_url: str, host: str, path_prefix: str = "") -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or parsed.hostname != host:
        raise ConnectorError(f"Connector must use official HTTPS host {host}")
    if path_prefix and not parsed.path.rstrip("/").startswith(path_prefix.rstrip("/")):
        raise ConnectorError(f"Connector base path must start with {path_prefix}")


def _category_codes(dimension: dict[str, Any], size: int) -> list[str]:
    category = dimension.get("category") or {}
    index = category.get("index")
    if isinstance(index, dict):
        codes = [None] * size
        for code, position in index.items():
            if not isinstance(position, int) or position < 0 or position >= size:
                raise ConnectorError("JSON-stat category index is invalid")
            codes[position] = str(code)
        if any(code is None for code in codes):
            raise ConnectorError("JSON-stat category index is incomplete")
        return [str(code) for code in codes]
    if isinstance(index, list) and len(index) == size:
        return [str(code) for code in index]
    raise ConnectorError("JSON-stat category index is missing or invalid")


def parse_jsonstat(
    payload: dict[str, Any],
    *,
    provider_code: str,
    dataset_code: str,
    max_observations: int,
) -> list[StatisticalObservation]:
    ids = payload.get("id")
    sizes = payload.get("size")
    dimensions = payload.get("dimension")
    values = payload.get("value")
    if (
        payload.get("class") != "dataset"
        or not isinstance(ids, list)
        or not isinstance(sizes, list)
        or len(ids) != len(sizes)
        or not isinstance(dimensions, dict)
        or not isinstance(values, (dict, list))
    ):
        raise ConnectorError("JSON-stat dataset schema is invalid")
    if any(not isinstance(size, int) or size < 1 for size in sizes):
        raise ConnectorError("JSON-stat dimensions contain an invalid size")

    codes = {
        str(name): _category_codes(dimensions.get(name) or {}, int(size))
        for name, size in zip(ids, sizes, strict=True)
    }
    labels = {
        str(name): ((dimensions.get(name) or {}).get("category") or {}).get("label") or {}
        for name in ids
    }
    entries = enumerate(values) if isinstance(values, list) else (
        (int(position), value) for position, value in values.items()
    )
    status_values = payload.get("status") or {}
    observations: list[StatisticalObservation] = []
    total_cells = 1
    for size in sizes:
        total_cells *= int(size)

    for position, value in entries:
        if value is None:
            continue
        if position < 0 or position >= total_cells:
            raise ConnectorError("JSON-stat value index is out of bounds")
        remainder = position
        coordinates: list[int] = []
        for size in reversed(sizes):
            coordinates.append(remainder % int(size))
            remainder //= int(size)
        coordinates.reverse()
        row_dimensions = {
            str(name): codes[str(name)][coordinate]
            for name, coordinate in zip(ids, coordinates, strict=True)
        }
        geo = row_dimensions.get("geo")
        period = row_dimensions.get("time")
        if period is None:
            raise ConnectorError("JSON-stat observation has no time dimension")
        status = None
        if isinstance(status_values, dict):
            status = status_values.get(str(position))
        elif isinstance(status_values, list) and position < len(status_values):
            status = status_values[position]
        observations.append(
            StatisticalObservation(
                provider_code=provider_code,
                dataset_code=dataset_code,
                series_code=dataset_code,
                geo_code=geo,
                geo_name=(labels.get("geo") or {}).get(geo) if geo else None,
                period=str(period),
                value=value,
                unit=row_dimensions.get("unit"),
                frequency=row_dimensions.get("freq"),
                measure=row_dimensions.get("measure") or row_dimensions.get("indic"),
                dimensions=row_dimensions,
                attributes={},
                status=str(status) if status is not None else None,
                raw={"position": position, "dimensions": row_dimensions, "value": value},
            )
        )
        if len(observations) > max_observations:
            raise ConnectorError("Provider result exceeds configured observation bound")
    return observations


class EurostatConnector(BaseConnector):
    source_code = "EUROSTAT"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(
            base_url,
            "ec.europa.eu",
            "/eurostat/api/dissemination/statistics/1.0",
        )
        super().__init__(base_url, timeout)

    async def fetch(self, query: EurostatQuery) -> StatisticalSnapshot:
        params: list[tuple[str, str]] = [("lang", "en")]
        if query.start_period:
            params.append(("sinceTimePeriod", query.start_period))
        if query.end_period:
            params.append(("untilTimePeriod", query.end_period))
        for dimension, values in query.filters.items():
            safe_name = str(dimension)
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", safe_name):
                raise ConnectorError("Eurostat filter contains an invalid dimension name")
            for value in values if isinstance(values, list) else [values]:
                params.append((safe_name, str(value)))
        response = await self.request(
            "GET",
            f"{self.base_url}/data/{query.dataset_code}",
            params=params,
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ConnectorError("Eurostat returned an unexpected schema")
        observations = parse_jsonstat(
            payload,
            provider_code=self.source_code,
            dataset_code=query.dataset_code,
            max_observations=query.max_observations,
        )
        return StatisticalSnapshot(
            self.source_code,
            query.dataset_code,
            observations,
            {
                "label": payload.get("label"),
                "updated": payload.get("updated"),
                "observation_count": len(observations),
            },
        )


class WorldBankConnector(BaseConnector):
    source_code = "WORLD_BANK"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(base_url, "api.worldbank.org", "/v2")
        super().__init__(base_url, timeout)

    async def fetch(self, query: WorldBankQuery) -> StatisticalSnapshot:
        rows: list[dict[str, Any]] = []
        page = 1
        pages: int | None = None
        total: int | None = None
        while True:
            params: dict[str, Any] = {
                "format": "json",
                "page": page,
                "per_page": query.page_size,
            }
            if query.start_year is not None or query.end_year is not None:
                start = query.start_year if query.start_year is not None else query.end_year
                end = query.end_year if query.end_year is not None else query.start_year
                params["date"] = f"{start}:{end}"
            if query.source_id is not None:
                params["source"] = query.source_id
            response = await self.request(
                "GET",
                f"{self.base_url}/country/{';'.join(query.countries)}/indicator/{query.indicator}",
                params=params,
                headers={"Accept": "application/json"},
            )
            payload = response.json()
            if (
                not isinstance(payload, list)
                or len(payload) != 2
                or not isinstance(payload[0], dict)
                or not isinstance(payload[1], list)
            ):
                raise ConnectorError("World Bank returned an unexpected indicator schema")
            metadata = payload[0]
            reported_pages = int(metadata.get("pages") or 1)
            reported_total = int(metadata.get("total") or len(payload[1]))
            reported_page = int(metadata.get("page") or page)
            if reported_page != page:
                raise ConnectorError("World Bank pagination response does not match requested page")
            if pages is None:
                pages, total = reported_pages, reported_total
                if pages > query.max_pages:
                    raise ConnectorError(
                        "World Bank query exceeds the configured complete-query page bound"
                    )
            elif pages != reported_pages or total != reported_total:
                raise ConnectorError("World Bank pagination metadata changed during retrieval")
            rows.extend(payload[1])
            if page >= pages:
                break
            page += 1
        if total is not None and len(rows) != total:
            raise ConnectorError(
                f"World Bank complete-query invariant failed: expected {total}, got {len(rows)}"
            )

        observations = []
        for row in rows:
            indicator = row.get("indicator") or {}
            country = row.get("country") or {}
            period = row.get("date")
            if period is None:
                raise ConnectorError("World Bank observation has no period")
            observations.append(
                StatisticalObservation(
                    provider_code=self.source_code,
                    dataset_code=str(row.get("source") or query.source_id or "INDICATORS"),
                    series_code=str(indicator.get("id") or query.indicator),
                    geo_code=str(row.get("countryiso3code") or country.get("id") or "") or None,
                    geo_name=country.get("value"),
                    period=str(period),
                    value=row.get("value"),
                    unit=row.get("unit") or None,
                    frequency=None,
                    measure=indicator.get("value"),
                    dimensions={
                        "indicator": str(indicator.get("id") or query.indicator),
                        "country": str(row.get("countryiso3code") or country.get("id") or ""),
                    },
                    attributes={
                        "decimal": row.get("decimal"),
                        "obs_status": row.get("obs_status"),
                    },
                    status=str(row.get("obs_status")) if row.get("obs_status") else None,
                    raw=row,
                )
            )
        return StatisticalSnapshot(
            self.source_code,
            str(query.source_id or "INDICATORS"),
            observations,
            {
                "indicator": query.indicator,
                "pages": pages or 1,
                "total": len(observations),
            },
        )


class OecdConnector(BaseConnector):
    source_code = "OECD"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(base_url, "sdmx.oecd.org", "/public/rest")
        super().__init__(base_url, timeout)

    async def fetch(self, query: OecdQuery) -> StatisticalSnapshot:
        reference = f"{query.agency},{query.dataflow},{query.version}"
        params: dict[str, str] = {"dimensionAtObservation": "AllDimensions"}
        if query.start_period:
            params["startPeriod"] = query.start_period
        if query.end_period:
            params["endPeriod"] = query.end_period
        response = await self.request(
            "GET",
            f"{self.base_url}/data/{reference}/{query.key}",
            params=params,
            headers={
                "Accept": "application/vnd.sdmx.data+csv;version=2.0.0, text/csv;q=0.9"
            },
        )
        text = response.text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "OBS_VALUE" not in reader.fieldnames:
            raise ConnectorError("OECD SDMX-CSV response has no OBS_VALUE column")
        rows = list(reader)
        if len(rows) > query.max_observations:
            raise ConnectorError("OECD result exceeds configured observation bound")
        observations = []
        for row in rows:
            period = row.get("TIME_PERIOD")
            if period is None:
                raise ConnectorError("OECD observation has no TIME_PERIOD")
            geo = (
                row.get("REF_AREA")
                or row.get("LOCATION")
                or row.get("COUNTRY")
                or row.get("GEO")
            )
            ignored = {
                "OBS_VALUE",
                "OBS_STATUS",
                "UNIT_MEASURE",
                "UNIT",
                "MEASURE",
                "TIME_PERIOD",
            }
            dimensions = {
                key: value
                for key, value in row.items()
                if key not in ignored and value not in (None, "")
            }
            observations.append(
                StatisticalObservation(
                    provider_code=self.source_code,
                    dataset_code=query.dataflow,
                    series_code=str(row.get("SERIES_KEY") or query.dataflow),
                    geo_code=geo or None,
                    geo_name=None,
                    period=str(period),
                    value=row.get("OBS_VALUE"),
                    unit=row.get("UNIT_MEASURE") or row.get("UNIT") or None,
                    frequency=row.get("FREQ") or None,
                    measure=row.get("MEASURE") or None,
                    dimensions=dimensions,
                    attributes={
                        "OBS_STATUS": row.get("OBS_STATUS"),
                        "STRUCTURE_ID": row.get("STRUCTURE_ID"),
                    },
                    status=row.get("OBS_STATUS") or None,
                    raw=row,
                )
            )
        return StatisticalSnapshot(
            self.source_code,
            query.dataflow,
            observations,
            {
                "agency": query.agency,
                "version": query.version,
                "key": query.key,
                "observation_count": len(observations),
            },
        )


class ImfDataMapperConnector(BaseConnector):
    source_code = "IMF"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(base_url, "www.imf.org", "/external/datamapper/api/v2")
        super().__init__(base_url, timeout)

    async def fetch(self, query: ImfQuery) -> StatisticalSnapshot:
        params = {"periods": ",".join(query.periods)} if query.periods else None
        response = await self.request(
            "GET",
            f"{self.base_url}/{query.indicator}/{'/'.join(query.economies)}",
            params=params,
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ConnectorError("IMF DataMapper returned an unexpected schema")
        values = payload.get("values")
        if not isinstance(values, dict) or not isinstance(values.get(query.indicator), dict):
            raise ConnectorError("IMF DataMapper response has no requested indicator values")
        by_geo = values[query.indicator]
        observations = []
        for economy, periods in by_geo.items():
            if not isinstance(periods, dict):
                raise ConnectorError("IMF DataMapper economy values are malformed")
            for period, value in periods.items():
                observations.append(
                    StatisticalObservation(
                        provider_code=self.source_code,
                        dataset_code="DATAMAPPER",
                        series_code=query.indicator,
                        geo_code=str(economy),
                        geo_name=None,
                        period=str(period),
                        value=value,
                        unit=None,
                        frequency="A",
                        measure=query.indicator,
                        dimensions={
                            "indicator": query.indicator,
                            "economy": str(economy),
                        },
                        attributes={},
                        status=None,
                        raw={
                            "indicator": query.indicator,
                            "economy": economy,
                            "period": period,
                            "value": value,
                        },
                    )
                )
        return StatisticalSnapshot(
            self.source_code,
            "DATAMAPPER",
            observations,
            {
                "indicator": query.indicator,
                "api": payload.get("api"),
                "observation_count": len(observations),
            },
        )


class IneSpainConnector(BaseConnector):
    source_code = "INE_ES"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(base_url, "servicios.ine.es", "/wstempus/js")
        super().__init__(base_url, timeout)

    async def fetch(self, query: IneSpainQuery) -> StatisticalSnapshot:
        response = await self.request(
            "GET",
            f"{self.base_url}/DATOS_TABLA/{query.table_id}",
            params={"nult": query.nult, "det": query.detail, "tip": "AM"},
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ConnectorError("Spain INE table endpoint returned an unexpected schema")
        observations = []
        for series in payload:
            if not isinstance(series, dict):
                raise ConnectorError("Spain INE series is not a JSON object")
            series_code = str(
                series.get("COD")
                or series.get("Codigo")
                or series.get("code")
                or query.table_id
            )
            data = series.get("Data") or series.get("data") or []
            if not isinstance(data, list):
                raise ConnectorError("Spain INE series data is malformed")
            for datum in data:
                if not isinstance(datum, dict):
                    raise ConnectorError("Spain INE observation is not a JSON object")
                period = (
                    datum.get("Fecha")
                    or datum.get("date")
                    or datum.get("Anyo")
                    or datum.get("Año")
                )
                if period is None:
                    raise ConnectorError("Spain INE observation has no period")
                value = (
                    datum.get("Valor")
                    if "Valor" in datum
                    else datum.get("value")
                )
                observations.append(
                    StatisticalObservation(
                        provider_code=self.source_code,
                        dataset_code=query.table_id,
                        series_code=series_code,
                        geo_code=str(
                            series.get("FK_Ambito")
                            or series.get("Ambito")
                            or series.get("Geografia")
                            or ""
                        )
                        or None,
                        geo_name=None,
                        period=str(period),
                        value=value,
                        unit=str(series.get("FK_Unidad") or series.get("Unidad") or "") or None,
                        frequency=str(
                            series.get("FK_Periodicidad") or series.get("Periodicidad") or ""
                        )
                        or None,
                        measure=series.get("Nombre") or series.get("name"),
                        dimensions={
                            key: value
                            for key, value in series.items()
                            if key not in {"Data", "data"} and not isinstance(value, (dict, list))
                        },
                        attributes={
                            key: value
                            for key, value in datum.items()
                            if key not in {"Valor", "value"}
                        },
                        status=None,
                        raw={"series": series_code, "observation": datum},
                    )
                )
        return StatisticalSnapshot(
            self.source_code,
            query.table_id,
            observations,
            {"table_id": query.table_id, "observation_count": len(observations)},
        )


class OnsUkConnector(BaseConnector):
    source_code = "ONS_UK"

    def __init__(self, base_url: str, timeout: float = 30.0):
        _official_host(base_url, "api.beta.ons.gov.uk", "/v1")
        super().__init__(base_url, timeout)

    async def _resolve_version(self, query: OnsUkQuery) -> int:
        if isinstance(query.version, int):
            if query.version < 1:
                raise ConnectorError("ONS version must be positive")
            return query.version
        response = await self.request(
            "GET",
            f"{self.base_url}/datasets/{query.dataset_id}",
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        latest = ((payload.get("links") or {}).get("latest_version") or {})
        version_id = latest.get("id")
        if version_id is not None and str(version_id).isdigit():
            return int(version_id)
        href = str(latest.get("href") or "")
        match = re.search(r"/versions/(\d+)(?:$|[/?#])", href)
        if not match:
            raise ConnectorError("ONS dataset does not expose a resolvable latest version")
        return int(match.group(1))

    async def fetch(self, query: OnsUkQuery) -> StatisticalSnapshot:
        version = await self._resolve_version(query)
        observations = []
        for dimension_set in query.dimension_sets:
            response = await self.request(
                "GET",
                (
                    f"{self.base_url}/datasets/{query.dataset_id}/editions/{query.edition}"
                    f"/versions/{version}/observations"
                ),
                params=dimension_set,
                headers={"Accept": "application/json"},
            )
            payload = response.json()
            rows = payload.get("observations")
            total = payload.get("total_observations")
            if not isinstance(rows, list) or int(total or len(rows)) != len(rows):
                raise ConnectorError("ONS observation response is incomplete or malformed")
            if len(rows) != 1:
                raise ConnectorError(
                    "ONS connector requires explicit dimensions resolving exactly one observation"
                )
            row = rows[0]
            if not isinstance(row, dict) or "observation" not in row:
                raise ConnectorError("ONS observation payload is malformed")
            returned_dimensions = {}
            for name, detail in (payload.get("dimensions") or {}).items():
                option = (detail or {}).get("option") or {}
                if option.get("id") is not None:
                    returned_dimensions[name] = str(option["id"])
            period = returned_dimensions.get("time") or dimension_set.get("time")
            if period is None:
                raise ConnectorError("ONS observation has no time dimension")
            geo = returned_dimensions.get("geography") or dimension_set.get("geography")
            observations.append(
                StatisticalObservation(
                    provider_code=self.source_code,
                    dataset_code=query.dataset_id,
                    series_code=query.dataset_id,
                    geo_code=geo,
                    geo_name=None,
                    period=str(period),
                    value=row.get("observation"),
                    unit=payload.get("unit_of_measure") or None,
                    frequency=None,
                    measure=query.dataset_id,
                    dimensions=returned_dimensions or dict(dimension_set),
                    attributes={},
                    status=None,
                    raw={
                        "version": version,
                        "dimensions": returned_dimensions or dimension_set,
                        "observation": row,
                    },
                )
            )
        return StatisticalSnapshot(
            self.source_code,
            query.dataset_id,
            observations,
            {
                "edition": query.edition,
                "version": version,
                "observation_count": len(observations),
            },
        )


QUERY_MODELS: dict[str, type[BaseModel]] = {
    "EUROSTAT": EurostatQuery,
    "WORLD_BANK": WorldBankQuery,
    "OECD": OecdQuery,
    "IMF": ImfQuery,
    "INE_ES": IneSpainQuery,
    "ONS_UK": OnsUkQuery,
}
