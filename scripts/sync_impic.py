"""Operator-scheduled official Portuguese contract open-data sync.
Run in the existing TRACE environment with PYTHONPATH=services/api.
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.account_impic import fetch_snapshot, persist_snapshot
from app.db import pool


async def sync(year: int, artifacts: Path) -> dict:
    snapshot = await fetch_snapshot(year)
    await pool.open()
    try:
        await pool.wait(timeout=15)
        async with pool.connection() as conn:
            return await persist_snapshot(conn, snapshot, artifacts)
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description="Import official IMPIC BASE contracts (JSON)")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path(".artifacts/impic"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(sync(args.year, args.artifacts)), sort_keys=True))


if __name__ == "__main__":
    main()
