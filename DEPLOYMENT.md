# Deployment

## Development

Copy `.env.example` to `.env`, then `docker compose up --build -d --wait`. Required services are postgres, one-shot migrate and API. Named volumes persist DB/evidence across container recreation. `docker compose down` stops containers without deleting data. **`down -v` deletes volumes** and is reserved for disposable CI/test installations.

For optional Neo4j use `docker compose --profile graph up -d`; the authoritative Path Finder still works without it. Redis is opt-in `--profile cache`. LocalStack is a real local S3 implementation/emulator for testing the optional S3 backend: `--profile s3`, `EVIDENCE_BACKEND=s3`, `MINIO_ENDPOINT=objectstore:4566`, access/secret `test`, bucket `trace-evidence`, TLS false on the isolated dev network. Restart API after changing environment. LocalStack is not a production object-store recommendation or a simulated government data source.

The inherited `compose.desktop.yml`/Windows launcher belongs to the older, larger desktop stack. The current supported minimal stack is `docker-compose.yml`; follow the new README rather than assuming all optional legacy services are needed. The installer remains under regression checks for compatibility.

## Production-like reference

```sh
python scripts/bootstrap_production.py
docker compose --env-file .env.production -f compose.production.yml up --build -d --wait
python scripts/production_smoke.py
```

Owner/runtime passwords and role keys are generated locally. Give credentials from the ignored `.production-keys.json` to distinct operators via an approved secret channel. The bootstrap refuses to overwrite an existing configuration. Change ALLOWED_HOSTS if exposing an internal hostname. If ports are occupied, change TRACE_PORT/PUBLIC_PORT; adapt smoke-script base URLs when using non-default ports.

Production Compose applies migrations, provisions runtime grants, then starts a non-root, read-only API with a writable persistent evidence volume. It starts a public-only nginx gateway on loopback 8080. PostgreSQL is not exposed to the host network. Image tags/runtime dependencies are explicit; release deployment should additionally resolve approved image digests and verify supply-chain/security scans under institutional policy.

Terminate TLS at an operator-managed edge proxy to loopback 8080. Route `/public/*`, `/ui/style.css` and `/api/public/*` only. Do not route `/ui/`, `/api/internal/`, `/api/v1/`, `/docs` or database/storage interfaces publicly. Keep the analyst API on a VPN/internal network; set Host correctly and maintain an explicit host allowlist. If terminating internal TLS, either preserve same-origin semantics with a verified proxy configuration or expose the internal UI through the same HTTPS origin. Do not solve origin failures by disabling the guard.

For institutional identity set `AUTH_MODE=oidc` and configure `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` and `OIDC_ROLE_MAP_JSON`. Keep the IdP behind its normal MFA and lifecycle controls; TRACE verifies tokens but does not become the account authority.

For managed PostgreSQL or object storage, use the variables in [DATABASES.md](DATABASES.md) and provider-approved credentials. Run migrations/provisioning as a distinct deployment job, not the runtime role. Inject BODS/PPDS tokens only when legally authorized and required. No institutional integration becomes official merely by configuring a URL.

## Backup and restore drill

The operational compose extension creates a PostgreSQL custom-format dump and a hash-verified Evidence Vault archive, then restores them into a disposable PostgreSQL 17 instance.

```sh
mkdir -p .artifacts/backups
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops run --rm backup
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops up -d restore-postgres
docker compose --env-file .env.production -f compose.production.yml -f compose.ops.yml --profile ops run --rm restore-drill
```

The restore drill checks migration count, every DB-referenced evidence object and the complete audit hash chain. CI runs this drill against the production-like stack. Copy backup sets to institution-approved encrypted/off-site storage and apply retention/object-lock policy there; the repository does not embed a cloud vendor credential.

## Release procedure

Back up both DB and vault; record image/commit and migration checksums; run CI, staging integration/smoke tests and a real-source health/import check where authorized. Apply migrations with the owner job; re-provision grants; deploy the runtime; verify `/ready`, role separation and the public gateway. Inspect failed imports and audit continuity. An application rollback does not undo schema migration: keep forward-compatible migrations or restore the tested backup to an isolated recovery environment. Verify a restore before replacing the live database.

The local workstation used for repository development did not provide Docker/WSL. Native PostgreSQL/API execution and integration tests are separate evidence from GitHub container validation; check [VALIDATION_REPORT.md](VALIDATION_REPORT.md) for actual results. None of these checks substitutes for institutional security/privacy approval.
