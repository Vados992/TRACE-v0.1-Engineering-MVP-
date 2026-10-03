# Troubleshooting

| Symptom | Check / remedy |
|---|---|
| `/ready` gives 503 | Check required postgres/evidence components, migration logs and writable persistent vault directory. Optional services may be absent |
| Port 8000/5432 occupied | Set TRACE_PORT/POSTGRES_PORT in `.env`; update host DSN and script base URL. Container DB host stays `postgres` |
| 401 | Enter the correct scoped key; the browser intentionally forgets it on reload. Production rejects public dev keys |
| 403 | Check operation role, explicit Host and same-origin write. Do not disable the guard to fix proxy configuration |
| Source 502 / timeout / 400 upstream | Inspect publisher availability and connector code/error, use its documented canonical endpoint, retry later. No fixture fallback is used |
| Open Ownership company filter timeout | Publisher SQL time limit/unindexed filter. The supported connector reads the actual publisher archive via bounded byte range. For arbitrary searches use an authorized indexed local/native BODS dataset; the prefix is not a full-company search |
| Import 422 | Check OCDS/BODS version and references, timezone-aware dates, supported mapping, numeric/currency bounds and entity-type conflict |
| Graph empty | Check actual stored edges, verified-only status and shared time interval. New file/BODS/OCDS imports remain UNVERIFIED. A missing graph path is not proof of no real-world relationship |
| Graph 422 budget | Narrow dates/entity scope/depth; partition large investigations rather than claiming complete enumeration |
| Wealth INCOMPLETE | Supply actual missing component evidence; never fill unknown fields with zero just to produce a residual |
| Evidence 409 | Object missing/hash changed; quarantine and investigate using trusted backup. Do not overwrite a hash-addressed object |
| Production refuses DB user | Runtime must not be superuser. Run migrations/provisioning with owner, connect API as `trace_runtime` |
| Production permission error after upgrade | Re-run runtime provisioning after migration, then restart API and test audit writes |
| Migration checksum mismatch | Restore the original applied file and add a new migration; only LF/CRLF normalization is accepted |
| Windows psycopg Proactor error | Launch with `python scripts/serve.py`; it selects compatible asyncio loop. Linux container uvicorn works normally |
| API docs blank with CSP | Current `/docs` serves local scripts only. Historical Swagger/CDN URLs are not the current UI |
| Docker unavailable on workstation | Use native PostgreSQL + filesystem vault + `scripts/serve.py`; container launch still requires a real Docker host |

Collect commit/version, source code, migration state, sanitized status/error and source retrieval time when reporting errors. Do not include API keys, credentials or real personal-data responses in public issues. Preserve original evidence hashes and private logs for authorized investigation.
