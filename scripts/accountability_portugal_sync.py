"""Schedule-friendly Portugal BASE ingestion for operator-controlled TRACE database.

Usage: PYTHONPATH=services/api python scripts/accountability_portugal_sync.py [--catalog-only]
Requires configured DATABASE_URL and migrated database, no fallback to development DB.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/api'))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-only', action='store_true')
    parser.add_argument('--actor', default='scheduled-pt-official-source-ingestor')
    args = parser.parse_args()
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('DATABASE_URL must be explicitly provided; no development fallback permitted')
    from app.account_portugal import PortugalBaseClient, PortugalSourceError
    from app.account_portugal_store import persist_portugal_snapshot
    from app.db import pool
    await pool.open()
    try:
        client = PortugalBaseClient()
        snapshot, _, choices = await client.catalog()
        catalog = await persist_portugal_snapshot(snapshot, args.actor)
        result = {'catalog': catalog, 'records': None, 'skipped': None}
        if not args.catalog_only:
            selected = next((x for x in choices if x.media_format == 'json'), choices[0] if choices else None)
            if selected is None:
                result['skipped'] = 'No approved official JSON/CSV resource'
            else:
                try:
                    data, rows = await client.resource(selected)
                    result['records'] = await persist_portugal_snapshot(data, args.actor, rows)
                except PortugalSourceError as exc:
                    result['skipped'] = str(exc)
        print(json.dumps(result, indent=2))
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
