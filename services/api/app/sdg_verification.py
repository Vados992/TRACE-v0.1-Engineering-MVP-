"""UN SDG snapshot ingestion, deterministic recalculation and claim verification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from . import audit
from .connectors.unsdg import UnSdgConnector
from .db import connection
from .ingest_repository import (
    create_ingest_job,
    finish_ingest_job,
    get_source_id,
    upsert_raw_artifact,
    upsert_source_record,
)
from .object_store import EvidenceStore
from .settings import settings

ENGINE_VERSION = "sdg-recalc-1.0.0"
_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


class SdgQuery(BaseModel):
    series_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-.]+$")
    area_codes: list[int] = Field(default_factory=list, max_length=250)
    time_period_start: int | None = Field(default=None, ge=1900, le=2200)
    time_period_end: int | None = Field(default=None, ge=1900, le=2200)
    page_size: int = Field(default=1000, ge=1, le=5000)
    max_pages: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def interval(self):
        if (
            self.time_period_start is not None
            and self.time_period_end is not None
            and self.time_period_end < self.time_period_start
        ):
            raise ValueError("time_period_end must be >= time_period_start")
        if any(code < 0 or code > 999 for code in self.area_codes):
            raise ValueError("area_codes must contain UN M49 numeric codes")
        return self


class RecalculationSpec(BaseModel):
    operation: Literal[
        "count_observations",
        "count_distinct_geographies",
        "sum_values",
        "mean_values",
        "percent_change",
    ]
    dimension_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    attribute_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    baseline_period: int | None = Field(default=None, ge=1900, le=2200)
    comparison_period: int | None = Field(default=None, ge=1900, le=2200)
    aggregation: Literal["sum", "mean"] = "sum"

    @model_validator(mode="after")
    def percent_change_periods(self):
        if self.operation == "percent_change":
            if self.baseline_period is None or self.comparison_period is None:
                raise ValueError("percent_change requires baseline_period and comparison_period")
            if self.baseline_period == self.comparison_period:
                raise ValueError("baseline_period and comparison_period must differ")
        return self


class VerificationRequest(BaseModel):
    query: SdgQuery
    calculation: RecalculationSpec
    asserted_value: Decimal
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    assertion_text: str = Field(min_length=1, max_length=5000)
    legal_basis: str = Field(min_length=10, max_length=2000)


class RecalculateStoredRequest(BaseModel):
    source_record_id: UUID
    calculation: RecalculationSpec


@dataclass(frozen=True)
class ImportedSnapshot:
    source_record_id: UUID
    artifact_id: UUID
    observation_count: int
    sha256: str
    external_id: str


def _stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace("\u2212", "-")
    if not _NUMERIC.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _matches(container: Any, filters: dict[str, str | list[str]]) -> bool:
    if not filters:
        return True
    if not isinstance(container, dict):
        return False
    for key, expected in filters.items():
        actual = container.get(key)
        allowed = {str(v) for v in (expected if isinstance(expected, list) else [expected])}
        if isinstance(actual, list):
            if not any(str(item) in allowed for item in actual):
                return False
        elif str(actual) not in allowed:
            return False
    return True


def filter_observations(rows: list[dict[str, Any]], spec: RecalculationSpec) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if _matches(row.get("dimensions") or {}, spec.dimension_filters)
        and _matches(row.get("attributes") or {}, spec.attribute_filters)
    ]


def _numeric_values(rows: list[dict[str, Any]]) -> list[Decimal]:
    values = [_to_decimal(row.get("value")) for row in rows]
    return [value for value in values if value is not None]


def _aggregate(values: list[Decimal], mode: str) -> Decimal:
    if not values:
        raise ValueError("No numeric observations match the requested calculation")
    total = sum(values, Decimal("0"))
    return total if mode == "sum" else total / Decimal(len(values))


def recalculate(rows: list[dict[str, Any]], spec: RecalculationSpec) -> dict[str, Any]:
    selected = filter_observations(rows, spec)
    if spec.operation == "count_observations":
        result = Decimal(len(selected))
        used = len(selected)
    elif spec.operation == "count_distinct_geographies":
        geos = {str(row.get("geoAreaCode")) for row in selected if row.get("geoAreaCode") is not None}
        result = Decimal(len(geos))
        used = len(selected)
    elif spec.operation in {"sum_values", "mean_values"}:
        values = _numeric_values(selected)
        result = _aggregate(values, "sum" if spec.operation == "sum_values" else "mean")
        used = len(values)
    else:
        baseline = [
            row for row in selected if int(row.get("timePeriodStart")) == spec.baseline_period
        ]
        comparison = [
            row for row in selected if int(row.get("timePeriodStart")) == spec.comparison_period
        ]
        base = _aggregate(_numeric_values(baseline), spec.aggregation)
        current = _aggregate(_numeric_values(comparison), spec.aggregation)
        if base == 0:
            raise ValueError("Percent change is undefined for a zero baseline")
        result = ((current - base) / abs(base)) * Decimal("100")
        used = len(baseline) + len(comparison)

    normalized = result.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN).normalize()
    return {
        "engine_version": ENGINE_VERSION,
        "operation": spec.operation,
        "result": format(normalized, "f"),
        "selected_observations": len(selected),
        "numeric_observations_used": used,
        "filters": {
            "dimensions": spec.dimension_filters,
            "attributes": spec.attribute_filters,
        },
        "baseline_period": spec.baseline_period,
        "comparison_period": spec.comparison_period,
        "aggregation": spec.aggregation if spec.operation == "percent_change" else None,
    }


class SdgVerificationService:
    def __init__(self) -> None:
        self.store = EvidenceStore()

    async def import_snapshot(self, query: SdgQuery, actor: str, legal_basis: str) -> ImportedSnapshot:
        connector = UnSdgConnector(settings.unsdg_base_url, settings.http_timeout_seconds)
        payload = await connector.series_data(**query.model_dump())
        raw = _stable_json(payload)
        query_hash = hashlib.sha256(_stable_json(query.model_dump())).hexdigest()[:24]
        external_id = f"series-{query.series_code}-{query_hash}"
        artifact = self.store.put_bytes("UN_SDG", external_id, raw, "application/json")

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, "UN_SDG")
                job_id = await create_ingest_job(
                    conn, source_id, "UN_SDG_SERIES_QUERY", query.model_dump(mode="json")
                )
                artifact_id = await upsert_raw_artifact(
                    conn,
                    source_id,
                    external_id,
                    artifact,
                    {
                        "connector": "UN_SDG",
                        "legal_basis": legal_basis,
                        "upstream": [
                            {
                                "url": response["url"],
                                "retrieved_at": response["retrieved_at"],
                                "status": response["status"],
                                "sha256": response["sha256"],
                                "content_range": response.get("content_range"),
                            }
                            for response in connector.responses
                        ],
                    },
                )
                source_record_id = await upsert_source_record(
                    conn,
                    source_id=source_id,
                    external_id=external_id,
                    payload_hash=artifact.sha256,
                    payload_uri=self.store.uri(artifact.object_key),
                    parser_version="trace-unsdg-1.0",
                    schema_version="UNSD_SDG_API_SERIES_DATA_V1",
                    raw_payload=None,
                )
                await conn.execute(
                    "UPDATE source_records SET metadata=metadata || %s WHERE id=%s",
                    (
                        Jsonb(
                            {
                                "query": query.model_dump(mode="json"),
                                "legal_basis": legal_basis,
                                "official_endpoint": settings.unsdg_base_url,
                                "complete_query": True,
                                "observation_count": len(payload["data"]),
                            }
                        ),
                        source_record_id,
                    ),
                )
                for row in payload["data"]:
                    numeric = _to_decimal(row.get("value"))
                    fingerprint = hashlib.sha256(_stable_json(row)).hexdigest()
                    await conn.execute(
                        """INSERT INTO sdg_observations(
                               source_record_id,observation_hash,series_code,series_description,
                               geo_area_code,geo_area_name,time_period_start,value_text,value_numeric,
                               goals,targets,indicators,source_text,footnotes,attributes,dimensions,raw_observation
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(source_record_id,observation_hash) DO NOTHING""",
                        (
                            source_record_id,
                            fingerprint,
                            row.get("series") or query.series_code,
                            row.get("seriesDescription"),
                            str(row.get("geoAreaCode")) if row.get("geoAreaCode") is not None else None,
                            row.get("geoAreaName"),
                            row.get("timePeriodStart"),
                            str(row.get("value")) if row.get("value") is not None else None,
                            numeric,
                            Jsonb(row.get("goal") or []),
                            Jsonb(row.get("target") or []),
                            Jsonb(row.get("indicator") or []),
                            row.get("source"),
                            Jsonb(row.get("footnotes") or []),
                            Jsonb(row.get("attributes") or {}),
                            Jsonb(row.get("dimensions") or {}),
                            Jsonb(row),
                        ),
                    )
                await finish_ingest_job(
                    conn, job_id, "SUCCEEDED", source_record_id, artifact_id, None
                )
                await audit.record(
                    conn,
                    actor,
                    "UN_SDG_SNAPSHOT_IMPORTED",
                    str(source_record_id),
                    {
                        "series_code": query.series_code,
                        "observation_count": len(payload["data"]),
                        "sha256": artifact.sha256,
                    },
                )

        return ImportedSnapshot(
            source_record_id=source_record_id,
            artifact_id=artifact_id,
            observation_count=len(payload["data"]),
            sha256=artifact.sha256,
            external_id=external_id,
        )

    async def _stored_rows(self, source_record_id: UUID) -> list[dict[str, Any]]:
        async with connection() as conn:
            source = await (
                await conn.execute(
                    """SELECT sr.id,s.code FROM source_records sr
                       JOIN sources s ON s.id=sr.source_id WHERE sr.id=%s""",
                    (source_record_id,),
                )
            ).fetchone()
            if not source or source["code"] != "UN_SDG":
                raise ValueError("source_record_id is not an imported UN SDG snapshot")
            rows = await (
                await conn.execute(
                    "SELECT raw_observation FROM sdg_observations WHERE source_record_id=%s ORDER BY id",
                    (source_record_id,),
                )
            ).fetchall()
        if not rows:
            raise ValueError("UN SDG snapshot contains no stored observations")
        return [row["raw_observation"] for row in rows]

    async def recalculate_stored(
        self, source_record_id: UUID, spec: RecalculationSpec, actor: str
    ) -> dict[str, Any]:
        rows = await self._stored_rows(source_record_id)
        result = recalculate(rows, spec)
        async with connection() as conn:
            async with conn.transaction():
                saved = await (
                    await conn.execute(
                        """INSERT INTO recalculation_runs(
                               source_record_id,engine_version,operation,input_spec,result,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,created_at""",
                        (
                            source_record_id,
                            ENGINE_VERSION,
                            spec.operation,
                            Jsonb(spec.model_dump(mode="json")),
                            Jsonb(result),
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "RECALCULATION_EXECUTED",
                    str(saved["id"]),
                    {"source_record_id": str(source_record_id), "operation": spec.operation},
                )
        return {**result, "recalculation_run_id": saved["id"], "source_record_id": source_record_id}

    async def verify(self, body: VerificationRequest, actor: str) -> dict[str, Any]:
        snapshot = await self.import_snapshot(body.query, actor, body.legal_basis)
        calculation = await self.recalculate_stored(
            snapshot.source_record_id, body.calculation, actor
        )
        calculated = Decimal(calculation["result"])
        delta = calculated - body.asserted_value
        verified = abs(delta) <= body.tolerance
        status = "VERIFIED" if verified else "REFUTED"

        async with connection() as conn:
            async with conn.transaction():
                saved = await (
                    await conn.execute(
                        """INSERT INTO claim_verification_runs(
                               source_record_id,recalculation_run_id,assertion_text,asserted_value,
                               calculated_value,tolerance,delta,status,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,created_at""",
                        (
                            snapshot.source_record_id,
                            calculation["recalculation_run_id"],
                            body.assertion_text,
                            body.asserted_value,
                            calculated,
                            body.tolerance,
                            delta,
                            status,
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "CLAIM_VERIFIED_AGAINST_UN_SDG",
                    str(saved["id"]),
                    {
                        "status": status,
                        "source_record_id": str(snapshot.source_record_id),
                        "recalculation_run_id": str(calculation["recalculation_run_id"]),
                    },
                )

        return {
            "verification_run_id": saved["id"],
            "status": status,
            "asserted_value": format(body.asserted_value, "f"),
            "calculated_value": format(calculated, "f"),
            "delta": format(delta, "f"),
            "tolerance": format(body.tolerance, "f"),
            "snapshot": {
                "source_record_id": snapshot.source_record_id,
                "artifact_id": snapshot.artifact_id,
                "observation_count": snapshot.observation_count,
                "sha256": snapshot.sha256,
            },
            "calculation": calculation,
            "is_legal_conclusion": False,
        }
