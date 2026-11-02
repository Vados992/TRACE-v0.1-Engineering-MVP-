"""Real PostgreSQL persistence test. CI needs migrated disposable PostgreSQL."""
import httpx
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.account_impic import DATASET_URL, fetch_snapshot, persist_snapshot
from app.settings import settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_impic_transaction_replay(tmp_path):
    source = "https://dados.gov.pt/fixtures/contratos2026.json"
    metadata = {"organization": {"name": "IMPIC"},
                "resources": [{"title": "contratos2026.json", "format": "json", "url": source}]}
    contracts = [{"idContrato": "TRACE-ACCOUNT-TEST-001",
                  "objectoContrato": "Synthetic integration record - never publish",
                  "precoContratual": "3000,00"}]

    def handler(request):
        if str(request.url) == DATASET_URL:
            return httpx.Response(200, json=metadata)
        if str(request.url) == source:
            return httpx.Response(200, json=contracts)
        raise AssertionError(str(request.url))

    snapshot = await fetch_snapshot(2026, transport=httpx.MockTransport(handler))
    # Isolate the test connection pool from the TRACE application lifespan.
    async with AsyncConnectionPool(
        conninfo=settings.database_url, min_size=1, max_size=2,
        kwargs={"row_factory": dict_row},
    ) as test_pool:
        async with test_pool.connection() as conn:
            first = await persist_snapshot(conn, snapshot, tmp_path)
            second = await persist_snapshot(conn, snapshot, tmp_path)
            assert first["snapshot_id"] == second["snapshot_id"]
            assert second["reused"] is True
            result = await (await conn.execute(
                """SELECT COUNT(*) AS n, MAX(contract_price_eur) AS price
                   FROM account_impic_contracts WHERE snapshot_id=%s""",
                (first["snapshot_id"],),
            )).fetchone()
            assert result["n"] == 1
            assert str(result["price"]) == "3000.00"

