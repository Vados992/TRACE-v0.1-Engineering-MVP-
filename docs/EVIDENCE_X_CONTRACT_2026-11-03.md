# TRACE → TRACE-ACCOUNT → EVIDENCE-X contract repair

Base TRACE PR #6: `7b58da7500bdec1fd25166feaab64756c5a19984`.
Companion EVIDENCE-X PR #19 base: `8d16bb94661896cd0d0847c39920fa591c8c653c`.
Both heads were rechecked before publication on 2026-11-03.

The connector now sends the requested `limit` and bounds decoded response bytes
while streaming, rather than loading the entire response before checking size.
Malformed list rows and malformed service URLs fail as unavailable. Redirects
remain disabled and scoped credentials remain confined to the configured origin.
The existing PostgreSQL fixture now checks the limit query parameter.

EVIDENCE-X's companion repair adds bounded metadata-only SQL projection, restores
the dropped v0.5–v0.14 route registration and `/eie`, and registers the existing
v0.15 cycle API alongside v0.16. Metadata listing does not load/decrypt raw evidence.

Local checks: 84 TRACE unit tests passed (16 integration cases deselected), plus
one two-repository contract test passed. Ruff and compilation passed. The contract
uses the real EVIDENCE-X ASGI application with a disposable SQLite database, the
TRACE boundary middleware and accountability router, and a viewer-only EVIDENCE-X
key. It checks 401/403 boundaries, a bounded successful response, unverified status,
503 on an invalid upstream key, rejection of writes using the viewer key, and no
source-row creation during the bridge read.

This is an in-process HTTP contract over ASGI, not a TLS/network deployment test,
not PostgreSQL end-to-end persistence, and not a live official-source ingest.
It does not validate the submit/review database transactions. No evidence is
automatically promoted to independently verified status.

## Reproduce across checkouts

Check out the companion repaired EVIDENCE-X branch at `../EVIDENCE` and install its
requirements into an environment that also satisfies TRACE's lock file:

```sh
python -m pip install -r requirements-dev.lock -r ../EVIDENCE/requirements.txt
pytest -q -m 'not integration'
TRACE_EVIDENCE_X_CHECKOUT=../EVIDENCE pytest -q tests/contracts/test_evidence_x_contract.py
```

The cross-repository test is explicit and skips without its checkout variable.
No cross-repository workflow token or private checkout credentials were introduced.
PostgreSQL migrations, durable assessment/review tests and hosted Actions remain
deferred until the requested environment and Actions availability are restored.
