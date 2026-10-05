"""Provider-agnostic statistical evidence, recalculation and cross-source verification."""

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
from .connectors.base import ConnectorError
from .connectors.statistical import (
    QUERY_MODELS,
    EurostatConnector,
    ImfDataMapperConnector,
    IneSpainConnector,
    OecdConnector,
    OnsUkConnector,
    StatisticalSnapshot,
    WorldBankConnector,
)
from .db import connection
from .ingest_repository import (
    create_ingest_job,
    finish_ingest_job,
    get_source_id,
    upsert_raw_artifact,
    upsert_source_record,
)
from .object_store import EvidenceStore
from .sdg_verification import SdgQuery, SdgVerificationService
from .settings import settings

ENGINE_VERSION = "statistical-recalc-1.0.0"
PROVIDER_CODES = ("UN_SDG", "EUROSTAT", "WORLD_BANK", "OECD", "IMF", "INE_ES", "ONS_UK")
ProviderCode = Literal["UN_SDG", "EUROSTAT", "WORLD_BANK", "OECD", "IMF", "INE_ES", "ONS_UK"]
_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


class StatisticalImportRequest(BaseModel):
    provider: ProviderCode
    query: dict[str, Any]
    legal_basis: str = Field(min_length=10, max_length=2000)


class StatisticalCalculation(BaseModel):
    operation: Literal[
        "count_observations",
        "count_distinct_geographies",
        "sum_values",
        "mean_values",
        "percent_change",
    ]
    dimension_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    attribute_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    baseline_period: str | int | None = None
    comparison_period: str | int | None = None
    aggregation: Literal["sum", "mean"] = "sum"

    @model_validator(mode="after")
    def percent_change_periods(self):
        if self.operation == "percent_change":
            if self.baseline_period is None or self.comparison_period is None:
                raise ValueError("percent_change requires baseline_period and comparison_period")
            if str(self.baseline_period) == str(self.comparison_period):
                raise ValueError("baseline_period and comparison_period must differ")
        return self


class StatisticalRecalculateRequest(BaseModel):
    source_record_id: UUID
    calculation: StatisticalCalculation


class StatisticalVerificationRequest(BaseModel):
    provider: ProviderCode
    query: dict[str, Any]
    calculation: StatisticalCalculation
    asserted_value: Decimal
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    assertion_text: str = Field(min_length=1, max_length=5000)
    legal_basis: str = Field(min_length=10, max_length=2000)


class SemanticContract(BaseModel):
    concept_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=500)
    unit: str = Field(min_length=1, max_length=100)
    frequency: str = Field(min_length=1, max_length=32)
    geography_scope: str = Field(min_length=1, max_length=200)
    period_start: str = Field(min_length=1, max_length=32)
    period_end: str = Field(min_length=1, max_length=32)
    transformation: str = Field(min_length=1, max_length=100)
    comparability_note: str = Field(min_length=20, max_length=3000)


class CrossSourceInput(BaseModel):
    provider: ProviderCode
    query: dict[str, Any]
    calculation: StatisticalCalculation
    mapping_note: str = Field(min_length=10, max_length=2000)


class CrossSourceVerificationRequest(BaseModel):
    sources: list[CrossSourceInput] = Field(min_length=2, max_length=7)
    semantic_contract: SemanticContract
    asserted_value: Decimal
    assertion_tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    source_spread_tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    assertion_text: str = Field(min_length=1, max_length=5000)
    legal_basis: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def unique_providers(self):
        providers = [item.provider for item in self.sources]
        if len(providers) != len(set(providers)):
            raise ValueError("cross-source verification requires unique providers")
        return self


@dataclass(frozen=True)
class ImportedStatisticalSnapshot:
    provider: str
    dataset_code: str
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
        allowed = {str(value) for value in (expected if isinstance(expected, list) else [expected])}
        if isinstance(actual, list):
            if not any(str(value) in allowed for value in actual):
                return False
        elif str(actual) not in allowed:
            return False
    return True


def _aggregate(values: list[Decimal], mode: str) -> Decimal:
    if not values:
        raise ValueError("No numeric observations match the requested calculation")
    total = sum(values, Decimal("0"))
    return total if mode == "sum" else total / Decimal(len(values))


def recalculate_statistical(
    rows: list[dict[str, Any]], spec: StatisticalCalculation
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if _matches(row.get("dimensions") or {}, spec.dimension_filters)
        and _matches(row.get("attributes") or {}, spec.attribute_filters)
    ]
    if spec.operation == "count_observations":
        result = Decimal(len(selected))
        numeric_used = len(selected)
    elif spec.operation == "count_distinct_geographies":
        geographies = {
            str(row.get("geo_code"))
            for row in selected
            if row.get("geo_code") not in (None, "")
        }
        result = Decimal(len(geographies))
        numeric_used = len(selected)
    elif spec.operation in {"sum_values", "mean_values"}:
        values = [_to_decimal(row.get("value")) for row in selected]
        numeric = [value for value in values if value is not None]
        mode = "sum" if spec.operation == "sum_values" else "mean"
        result = _aggregate(numeric, mode)
        numeric_used = len(numeric)
    else:
        baseline = [
            row for row in selected if str(row.get("period")) == str(spec.baseline_period)
        ]
        comparison = [
            row for row in selected if str(row.get("period")) == str(spec.comparison_period)
        ]
        base_values = [_to_decimal(row.get("value")) for row in baseline]
        current_values = [_to_decimal(row.get("value")) for row in comparison]
        base = _aggregate(
            [value for value in base_values if value is not None],
            spec.aggregation,
        )
        current = _aggregate(
            [value for value in current_values if value is not None],
            spec.aggregation,
        )
        if base == 0:
            raise ValueError("Percent change is undefined for a zero baseline")
        result = ((current - base) / abs(base)) * Decimal("100")
        numeric_used = len(
            [value for value in [*base_values, *current_values] if value is not None]
        )

    normalized = result.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN).normalize()
    return {
        "engine_version": ENGINE_VERSION,
        "operation": spec.operation,
        "result": format(normalized, "f"),
        "selected_observations": len(selected),
        "numeric_observations_used": numeric_used,
        "filters": {
            "dimensions": spec.dimension_filters,
            "attributes": spec.attribute_filters,
        },
        "baseline_period": (
            str(spec.baseline_period) if spec.baseline_period is not None else None
        ),
        "comparison_period": (
            str(spec.comparison_period) if spec.comparison_period is not None else None
        ),
        "aggregation": spec.aggregation if spec.operation == "percent_change" else None,
    }


class StatisticalVerificationService:
    def __init__(self) -> None:
        self.store = EvidenceStore()

    @staticmethod
    def _query(provider: str, query: dict[str, Any]) -> BaseModel:
        if provider == "UN_SDG":
            return SdgQuery.model_validate(query)
        model = QUERY_MODELS.get(provider)
        if model is None:
            raise ValueError(f"Unsupported statistical provider: {provider}")
        return model.model_validate(query)

    @staticmethod
    def _connector(provider: str):
        if provider == "EUROSTAT":
            return EurostatConnector(settings.eurostat_base_url, settings.http_timeout_seconds)
        if provider == "WORLD_BANK":
            return WorldBankConnector(settings.world_bank_base_url, settings.http_timeout_seconds)
        if provider == "OECD":
            return OecdConnector(settings.oecd_sdmx_base_url, settings.http_timeout_seconds)
        if provider == "IMF":
            return ImfDataMapperConnector(settings.imf_datamapper_base_url, settings.http_timeout_seconds)
        if provider == "INE_ES":
            return IneSpainConnector(settings.ine_es_base_url, settings.http_timeout_seconds)
        if provider == "ONS_UK":
            return OnsUkConnector(settings.ons_uk_base_url, settings.http_timeout_seconds)
        raise ValueError(f"Unsupported connector provider: {provider}")

    async def import_snapshot(
        self, provider: str, query: dict[str, Any], actor: str, legal_basis: str
    ) -> ImportedStatisticalSnapshot:
        parsed_query = self._query(provider, query)
        if provider == "UN_SDG":
            snapshot = await SdgVerificationService().import_snapshot(
                parsed_query, actor, legal_basis
            )
            return ImportedStatisticalSnapshot(
                provider="UN_SDG",
                dataset_code=parsed_query.series_code,
                source_record_id=snapshot.source_record_id,
                artifact_id=snapshot.artifact_id,
                observation_count=snapshot.observation_count,
                sha256=snapshot.sha256,
                external_id=snapshot.external_id,
            )

        connector = self._connector(provider)
        fetched: StatisticalSnapshot = await connector.fetch(parsed_query)
        normalized = [observation.to_dict() for observation in fetched.observations]
        envelope = {
            "provider": provider,
            "query": parsed_query.model_dump(mode="json"),
            "metadata": fetched.metadata,
            "upstream_responses": connector.responses,
            "observations": normalized,
        }
        raw = _stable_json(envelope)
        query_hash = hashlib.sha256(
            _stable_json(parsed_query.model_dump(mode="json"))
        ).hexdigest()[:24]
        safe_dataset = re.sub(r"[^A-Za-z0-9_.-]+", "_", fetched.dataset_code)[:100]
        external_id = f"{safe_dataset}-{query_hash}"
        artifact = self.store.put_bytes(provider, external_id, raw, "application/json")

        async with connection() as conn:
            async with conn.transaction():
                source_id = await get_source_id(conn, provider)
                job_id = await create_ingest_job(
                    conn,
                    source_id,
                    f"{provider}_STATISTICAL_QUERY",
                    parsed_query.model_dump(mode="json"),
                )
                artifact_id = await upsert_raw_artifact(
                    conn,
                    source_id,
                    external_id,
                    artifact,
                    {
                        "connector": provider,
                        "legal_basis": legal_basis,
                        "official_endpoint": connector.base_url,
                        "response_count": len(connector.responses),
                    },
                )
                source_record_id = await upsert_source_record(
                    conn,
                    source_id=source_id,
                    external_id=external_id,
                    payload_hash=artifact.sha256,
                    payload_uri=self.store.uri(artifact.object_key),
                    parser_version="trace-statistical-1.0",
                    schema_version="TRACE_CANONICAL_STATISTICAL_OBSERVATION_V1",
                    raw_payload=None,
                )
                await conn.execute(
                    "UPDATE source_records SET metadata=metadata || %s WHERE id=%s",
                    (
                        Jsonb(
                            {
                                "provider": provider,
                                "dataset_code": fetched.dataset_code,
                                "query": parsed_query.model_dump(mode="json"),
                                "legal_basis": legal_basis,
                                "official_endpoint": connector.base_url,
                                "complete_query": True,
                                "observation_count": len(normalized),
                            }
                        ),
                        source_record_id,
                    ),
                )
                for observation in fetched.observations:
                    as_dict = observation.to_dict()
                    observation_hash = hashlib.sha256(_stable_json(as_dict)).hexdigest()
                    numeric = _to_decimal(observation.value)
                    await conn.execute(
                        """INSERT INTO statistical_observations(
                               source_record_id,observation_hash,provider_code,dataset_code,
                               series_code,geo_code,geo_name,time_period,value_text,value_numeric,
                               unit,frequency,measure,observation_status,dimensions,attributes,
                               raw_observation
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(source_record_id,observation_hash) DO NOTHING""",
                        (
                            source_record_id,
                            observation_hash,
                            provider,
                            observation.dataset_code,
                            observation.series_code,
                            observation.geo_code,
                            observation.geo_name,
                            observation.period,
                            (
                                str(observation.value)
                                if observation.value is not None
                                else None
                            ),
                            numeric,
                            observation.unit,
                            observation.frequency,
                            observation.measure,
                            observation.status,
                            Jsonb(observation.dimensions),
                            Jsonb(observation.attributes),
                            Jsonb(observation.raw),
                        ),
                    )
                await finish_ingest_job(
                    conn,
                    job_id,
                    "SUCCEEDED",
                    source_record_id,
                    artifact_id,
                    None,
                )
                await audit.record(
                    conn,
                    actor,
                    "STATISTICAL_SNAPSHOT_IMPORTED",
                    str(source_record_id),
                    {
                        "provider": provider,
                        "dataset_code": fetched.dataset_code,
                        "observation_count": len(normalized),
                        "sha256": artifact.sha256,
                    },
                )

        return ImportedStatisticalSnapshot(
            provider=provider,
            dataset_code=fetched.dataset_code,
            source_record_id=source_record_id,
            artifact_id=artifact_id,
            observation_count=len(normalized),
            sha256=artifact.sha256,
            external_id=external_id,
        )

    async def _stored_rows(self, source_record_id: UUID) -> tuple[str, list[dict[str, Any]]]:
        async with connection() as conn:
            source = await (
                await conn.execute(
                    """SELECT sr.id,s.code FROM source_records sr
                       JOIN sources s ON s.id=sr.source_id WHERE sr.id=%s""",
                    (source_record_id,),
                )
            ).fetchone()
            if not source or source["code"] not in PROVIDER_CODES:
                raise ValueError("source_record_id is not a supported statistical snapshot")
            provider = source["code"]
            if provider == "UN_SDG":
                records = await (
                    await conn.execute(
                        """SELECT geo_area_code AS geo_code,time_period_start::text AS period,
                                  value_text AS value,dimensions,attributes
                           FROM sdg_observations WHERE source_record_id=%s ORDER BY id""",
                        (source_record_id,),
                    )
                ).fetchall()
            else:
                records = await (
                    await conn.execute(
                        """SELECT geo_code,time_period AS period,value_text AS value,
                                  dimensions,attributes
                           FROM statistical_observations
                           WHERE source_record_id=%s ORDER BY id""",
                        (source_record_id,),
                    )
                ).fetchall()
        if not records:
            raise ValueError("Statistical snapshot contains no stored observations")
        return provider, [dict(record) for record in records]

    async def recalculate_stored(
        self,
        source_record_id: UUID,
        spec: StatisticalCalculation,
        actor: str,
    ) -> dict[str, Any]:
        provider, rows = await self._stored_rows(source_record_id)
        result = recalculate_statistical(rows, spec)
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
                    "STATISTICAL_RECALCULATION_EXECUTED",
                    str(saved["id"]),
                    {
                        "provider": provider,
                        "source_record_id": str(source_record_id),
                        "operation": spec.operation,
                    },
                )
        return {
            **result,
            "provider": provider,
            "recalculation_run_id": saved["id"],
            "source_record_id": source_record_id,
        }

    async def verify(
        self, body: StatisticalVerificationRequest, actor: str
    ) -> dict[str, Any]:
        snapshot = await self.import_snapshot(
            body.provider, body.query, actor, body.legal_basis
        )
        calculation = await self.recalculate_stored(
            snapshot.source_record_id, body.calculation, actor
        )
        calculated = Decimal(calculation["result"])
        delta = calculated - body.asserted_value
        status = "VERIFIED" if abs(delta) <= body.tolerance else "REFUTED"
        async with connection() as conn:
            async with conn.transaction():
                saved = await (
                    await conn.execute(
                        """INSERT INTO claim_verification_runs(
                               source_record_id,recalculation_run_id,assertion_text,
                               asserted_value,calculated_value,tolerance,delta,status,created_by
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
                    "STATISTICAL_CLAIM_VERIFIED",
                    str(saved["id"]),
                    {
                        "provider": body.provider,
                        "status": status,
                        "source_record_id": str(snapshot.source_record_id),
                    },
                )
        return {
            "verification_run_id": saved["id"],
            "provider": body.provider,
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

    async def cross_verify(
        self, body: CrossSourceVerificationRequest, actor: str
    ) -> dict[str, Any]:
        provider_results: list[dict[str, Any]] = []
        successful: list[tuple[CrossSourceInput, ImportedStatisticalSnapshot, dict[str, Any]]] = []

        for item in body.sources:
            try:
                snapshot = await self.import_snapshot(
                    item.provider, item.query, actor, body.legal_basis
                )
                calculation = await self.recalculate_stored(
                    snapshot.source_record_id, item.calculation, actor
                )
                successful.append((item, snapshot, calculation))
                provider_results.append(
                    {
                        "provider": item.provider,
                        "status": "OK",
                        "mapping_note": item.mapping_note,
                        "source_record_id": str(snapshot.source_record_id),
                        "recalculation_run_id": str(calculation["recalculation_run_id"]),
                        "calculated_value": calculation["result"],
                        "observation_count": snapshot.observation_count,
                        "sha256": snapshot.sha256,
                    }
                )
            except (ConnectorError, ValueError) as exc:
                provider_results.append(
                    {
                        "provider": item.provider,
                        "status": "ERROR",
                        "mapping_note": item.mapping_note,
                        "error_code": type(exc).__name__,
                    }
                )

        failures = [result for result in provider_results if result["status"] != "OK"]
        values = [Decimal(calculation["result"]) for _, _, calculation in successful]
        consensus_value: Decimal | None = None
        spread: Decimal | None = None
        if failures or len(values) < 2:
            status = "INSUFFICIENT"
        else:
            spread = max(values) - min(values)
            if spread > body.source_spread_tolerance:
                status = "SOURCE_CONFLICT"
            else:
                consensus_value = sum(values, Decimal("0")) / Decimal(len(values))
                status = (
                    "CONSENSUS_VERIFIED"
                    if abs(consensus_value - body.asserted_value)
                    <= body.assertion_tolerance
                    else "CONSENSUS_REFUTED"
                )

        async with connection() as conn:
            async with conn.transaction():
                saved = await (
                    await conn.execute(
                        """INSERT INTO cross_source_verification_runs(
                               assertion_text,asserted_value,assertion_tolerance,
                               source_spread_tolerance,semantic_contract,provider_results,
                               consensus_value,spread,status,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,created_at""",
                        (
                            body.assertion_text,
                            body.asserted_value,
                            body.assertion_tolerance,
                            body.source_spread_tolerance,
                            Jsonb(body.semantic_contract.model_dump(mode="json")),
                            Jsonb(provider_results),
                            consensus_value,
                            spread,
                            status,
                            actor,
                        ),
                    )
                ).fetchone()
                for item, snapshot, calculation in successful:
                    await conn.execute(
                        """INSERT INTO cross_source_verification_members(
                               run_id,provider_code,source_record_id,recalculation_run_id,
                               calculated_value,mapping_note
                           ) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            saved["id"],
                            item.provider,
                            snapshot.source_record_id,
                            calculation["recalculation_run_id"],
                            Decimal(calculation["result"]),
                            item.mapping_note,
                        ),
                    )
                await audit.record(
                    conn,
                    actor,
                    "CROSS_SOURCE_STATISTICAL_VERIFICATION",
                    str(saved["id"]),
                    {
                        "status": status,
                        "providers": [item.provider for item in body.sources],
                        "successful_sources": len(successful),
                        "semantic_contract": body.semantic_contract.concept_id,
                    },
                )

        return {
            "cross_source_run_id": saved["id"],
            "status": status,
            "asserted_value": format(body.asserted_value, "f"),
            "consensus_value": (
                format(consensus_value, "f") if consensus_value is not None else None
            ),
            "spread": format(spread, "f") if spread is not None else None,
            "assertion_tolerance": format(body.assertion_tolerance, "f"),
            "source_spread_tolerance": format(body.source_spread_tolerance, "f"),
            "semantic_contract": body.semantic_contract.model_dump(mode="json"),
            "providers": provider_results,
            "is_legal_conclusion": False,
            "comparability_is_operator_declared": True,
        }
