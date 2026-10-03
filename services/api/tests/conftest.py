from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def pure_graph_clock(monkeypatch):
    # Unit BFS tests replace the repository; PostgreSQL clock behavior is tested in integration.
    async def cutoff(known_at=None):
        return known_at or datetime(2026, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr("app.pathfinder.resolve_known_at", cutoff)
