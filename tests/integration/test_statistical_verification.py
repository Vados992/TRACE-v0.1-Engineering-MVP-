"""Integration coverage for canonical statistical storage and cross-source receipts."""

import os
from uuid import uuid4

import psycopg
import pytest
from app.statistical_verification import ImportedStatisticalSnapshot, StatisticalVerificationService
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("TRACE_INTEGRATION") != "1",
        reason="Set TRACE_INTEGRATION=1 and use a disposable migrated PostgreSQL database",
    ),
]


def auth(role):
    return {"Authorization": f"Bearer trace-dev-{role}-only"}


@pytest.fixture(scope="module")
def client():
    from app.loop import selector_loop
    from app.main import app

    with TestClient(
        app, raise_server_exceptions=True, backend_options={"loop_factory": selector_loop}
    ) as client:
        yield client


def seed_snapshot(provider: str, values: list[tuple[str, str]], dataset: str):
    from app.settings import settings

    external = f"integration-{provider.lower()}-{uuid4()}"
    with psycopg.connect(settings.database_url) as conn:
        source_id = conn.execute(
            "SELECT id FROM sources WHERE code=%s", (provider,)
        ).fetchone()[0]
        source_record_id = conn.execute(
            """INSERT INTO source_records(
                   source_id,external_id,payload_uri,payload_hash,parser_version,schema_version
               ) VALUES (%s,%s,%s,%s,'integration-test','TRACE_CANONICAL_STATISTICAL_OBSERVATION_V1')
               RETURNING id""",
            (
                source_id,
                external,
                "fixture://statistical/" + external,
                "hash-" + str(uuid4()),
            ),
        ).fetchone()[0]
        for period, value in values:
            conn.execute(
                """INSERT INTO statistical_observations(
                       source_record_id,observation_hash,provider_code,dataset_code,series_code,
                       geo_code,time_period,value_text,value_numeric,unit,frequency,measure,
                       dimensions,attributes,raw_observation
                   ) VALUES (%s,%s,%s,%s,%s,'PRT',%s,%s,%s,'percent','A','test',
                             %s,%s,%s)""",
                (
                    source_record_id,
                    str(uuid4()),
                    provider,
                    dataset,
                    dataset,
                    period,
                    value,
                    value,
                    Jsonb({"geo": "PRT"}),
                    Jsonb({}),
                    Jsonb({"period": period, "value": value}),
                ),
            )
        return source_record_id


def test_statistical_recalculation_endpoint_and_immutability(client):
    from app.settings import settings

    record = seed_snapshot(
        "WORLD_BANK",
        [("2023", "100"), ("2024", "110")],
        "SP.TEST",
    )
    response = client.post(
        "/api/internal/statistics/recalculate",
        headers=auth("analyst"),
        json={
            "source_record_id": str(record),
            "calculation": {
                "operation": "percent_change",
                "baseline_period": "2023",
                "comparison_period": "2024",
                "aggregation": "sum",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "10"
    assert response.json()["provider"] == "WORLD_BANK"

    with psycopg.connect(settings.database_url) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute(
                "DELETE FROM statistical_observations WHERE source_record_id=%s",
                (record,),
            )


def test_cross_source_consensus_receipt_is_persisted(client, monkeypatch):
    world_bank = seed_snapshot("WORLD_BANK", [("2024", "100.0")], "WB.TEST")
    eurostat = seed_snapshot("EUROSTAT", [("2024", "100.2")], "ESTAT_TEST")
    snapshots = {
        "WORLD_BANK": ImportedStatisticalSnapshot(
            provider="WORLD_BANK",
            dataset_code="WB.TEST",
            source_record_id=world_bank,
            artifact_id=uuid4(),
            observation_count=1,
            sha256="a" * 64,
            external_id="fixture-world-bank",
        ),
        "EUROSTAT": ImportedStatisticalSnapshot(
            provider="EUROSTAT",
            dataset_code="ESTAT_TEST",
            source_record_id=eurostat,
            artifact_id=uuid4(),
            observation_count=1,
            sha256="b" * 64,
            external_id="fixture-eurostat",
        ),
    }

    async def no_network_import(self, provider, query, actor, legal_basis):
        return snapshots[provider]

    monkeypatch.setattr(
        StatisticalVerificationService,
        "import_snapshot",
        no_network_import,
    )
    response = client.post(
        "/api/internal/statistics/cross-verify",
        headers=auth("analyst"),
        json={
            "sources": [
                {
                    "provider": "WORLD_BANK",
                    "query": {},
                    "calculation": {"operation": "mean_values"},
                    "mapping_note": "Mapped to the declared synthetic annual concept.",
                },
                {
                    "provider": "EUROSTAT",
                    "query": {},
                    "calculation": {"operation": "mean_values"},
                    "mapping_note": "Mapped to the declared synthetic annual concept.",
                },
            ],
            "semantic_contract": {
                "concept_id": "integration.synthetic",
                "label": "Integration synthetic comparable measure",
                "unit": "percent",
                "frequency": "A",
                "geography_scope": "Portugal",
                "period_start": "2024",
                "period_end": "2024",
                "transformation": "level",
                "comparability_note": (
                    "This disposable integration fixture explicitly declares both values "
                    "semantically equivalent only to exercise the cross-source control path."
                ),
            },
            "asserted_value": "100.1",
            "assertion_tolerance": "0.01",
            "source_spread_tolerance": "0.3",
            "assertion_text": "Synthetic integration assertion equals the source consensus.",
            "legal_basis": "Disposable technical validation using synthetic integration records",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "CONSENSUS_VERIFIED"
    assert body["consensus_value"] == "100.1"
    assert body["comparability_is_operator_declared"] is True

    from app.settings import settings

    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute(
            "SELECT status FROM cross_source_verification_runs WHERE id=%s",
            (body["cross_source_run_id"],),
        ).fetchone()
        members = conn.execute(
            "SELECT count(*) FROM cross_source_verification_members WHERE run_id=%s",
            (body["cross_source_run_id"],),
        ).fetchone()[0]
    assert row[0] == "CONSENSUS_VERIFIED"
    assert members == 2
