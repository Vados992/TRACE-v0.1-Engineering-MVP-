import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import app.pathfinder as pathfinder
import pytest
from app.adapters import parse_import
from app.security import authenticate, validate_configuration
from app.settings import settings
from app.wealth import WealthInput, reconcile
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["ocds", "bods", "roles", "ppds"])
def test_offline_adapters(name):
    data = json.loads((ROOT / "fixtures" / "demo" / f"{name}.json").read_text())
    normalized = parse_import(data["format"], data["payload"])
    assert normalized.entities and normalized.relationships


def test_consortium_amount_not_double_counted():
    package = json.loads((ROOT / "fixtures/demo/ocds.json").read_text())["payload"]
    release = package["releases"][0]
    release["parties"].append({"id": "supplier2", "name": "Another supplier"})
    release["awards"][0]["suppliers"].append({"id": "supplier2"})
    result = parse_import("ocds", package)
    assert all(edge.amount is None for edge in result.relationships)
    assert result.warnings


def test_unsupported_bods_and_unknown_owner():
    data = json.loads((ROOT / "fixtures/demo/bods.json").read_text())["payload"]
    data[0]["publicationDetails"]["bodsVersion"] = "0.5"
    with pytest.raises(ValueError):
        parse_import("bods", data)
    data[0]["publicationDetails"]["bodsVersion"] = "0.3"
    data[0]["personType"] = "unknownPerson"
    result = parse_import("bods", data)
    assert not result.relationships and result.warnings


def test_decimal_bridge_and_completeness():
    data = json.loads((ROOT / "fixtures/demo/wealth.json").read_text())
    result = reconcile(WealthInput(**data))
    assert result["residual"] == "50000.00"
    data["closing_net_worth"] = "130000.00"
    assert reconcile(WealthInput(**data))["status"] == "RECONCILED"
    data["income"] = None
    result = reconcile(WealthInput(**data))
    assert result["status"] == "INCOMPLETE" and result["residual"] is None
    data["period_end"] = data["period_start"]
    with pytest.raises(ValidationError):
        WealthInput(**data)


def test_prod_rejects_demo_keys(monkeypatch):
    assert authenticate("Bearer trace-dev-reviewer-only").role == "reviewer"
    assert authenticate("Bearer invalid") is None
    monkeypatch.setattr(settings, "trace_env", "production")
    with pytest.raises(ValueError, match="Demo"):
        validate_configuration()


@pytest.mark.asyncio
async def test_path_rejects_noncontemporaneous_edges(monkeypatch):
    a, b, c = [UUID(int=i) for i in [1, 2, 3]]

    def edge(i, subject, obj, year):
        return {
            "id": UUID(int=i),
            "subject_entity_id": subject,
            "object_entity_id": obj,
            "relationship_type": "OWNS",
            "valid_from": datetime(year, 1, 1, tzinfo=timezone.utc),
            "valid_to": datetime(year, 12, 31, tzinfo=timezone.utc),
            "verification_status": "VERIFIED_PRIMARY",
            "claim_type": "FACT",
        }

    ab, bc = edge(10, a, b, 2020), edge(11, b, c, 2025)

    async def frontier(ids, **kwargs):
        return [ab] if ids[0] == a else [ab, bc]

    monkeypatch.setattr(pathfinder, "fetch_relationship_frontier", frontier)
    assert await pathfinder.find_paths(a, c) == []


@pytest.mark.asyncio
async def test_graph_budget_is_explicit(monkeypatch):
    monkeypatch.setattr(settings, "graph_max_expansions", 0)
    with pytest.raises(pathfinder.GraphBudgetExceeded):
        await pathfinder.find_paths(UUID(int=1), UUID(int=2))
