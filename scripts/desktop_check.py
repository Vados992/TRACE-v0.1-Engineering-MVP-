"""Non-destructive stack check. With --live, ingest public records; never seed fixtures."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import httpx
import psycopg
from psycopg.rows import dict_row

from app.object_store import EvidenceStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--strict-sources', action='store_true')
    args = parser.parse_args()
    report = {'time': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'sources': {}}
    failed = False
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=180) as client:
        for path in ['/health', '/ready', '/ui/', '/openapi.json']:
            r = client.get(path)
            r.raise_for_status()
            report['checks'][path] = 'ok'
        status = client.get('/api/v1/system/status').json()
        report['components'] = status['components']
        if any(c['status'] != 'ok' for c in status['components'].values()):
            failed = True
        if args.live:
            for code, path, body in [
                ('GLEIF', '/api/v1/relationship-intelligence/ownership/gleif/529900T8BM49AURSDO55', None),
                ('TED', '/api/v1/relationship-intelligence/procurement/ted/search',
                 {'query': 'publication-date >= '+(datetime.now(timezone.utc)-timedelta(days=30)).strftime('%Y%m%d'), 'limit': 3}),
                ('EURLEX', '/api/v1/relationship-intelligence/policy/eurlex/32016R0679', None),
            ]:
                try:
                    r = client.post(path, json=body) if body else client.post(path)
                    r.raise_for_status()
                    data = r.json()
                    assert data['status'] in ['SUCCEEDED', 'PARTIAL'], data
                    assert data['source_record_ids'], data
                    report['sources'][code] = data
                except Exception as exc:
                    report['sources'][code] = {'status': 'FAILED', 'error': str(exc)[:400]}
                    if args.strict_sources:
                        failed = True
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as conn:
            rows = conn.execute('SELECT object_key, content_hash FROM raw_artifacts').fetchall()
            if args.live and not rows:
                raise RuntimeError('No evidence stored')
            store = EvidenceStore()
            for row in rows:
                store.get_bytes(row['object_key'], row['content_hash'])
            report['checks']['evidence_objects_verified'] = len(rows)
            # Exercise a real canonical relationship if the sources supplied one.
            edge = conn.execute('SELECT id, subject_entity_id, object_entity_id FROM relationships WHERE superseded_at IS NULL LIMIT 1').fetchone()
            if edge:
                r = client.post('/api/v1/graph/path', json={'source_entity_id': str(edge['subject_entity_id']), 'target_entity_id': str(edge['object_entity_id']), 'max_depth': 2, 'verified_only': True})
                r.raise_for_status()
                paths = r.json()['paths']
                assert any(str(edge['id']) in [e['id'] for e in p['edges']] for p in paths), paths
                why = client.get('/api/v1/relationships/'+str(edge['id'])+'/why')
                why.raise_for_status()
                assert why.json()['source_observations']
                report['checks']['real_relationship_path_and_provenance'] = 'ok'
            else:
                report['checks']['real_relationship_path_and_provenance'] = 'not available: no source relationship'
                if args.strict_sources: failed = True
            # Stable digest lets CI compare the same evidence set after container recreation.
            report['evidence_set_sha256'] = hashlib.sha256(json.dumps(sorted((r['object_key'],r['content_hash']) for r in rows)).encode()).hexdigest()
    report['passed'] = not failed
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
