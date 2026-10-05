# Security

TRACE supports two real authentication adapters: scoped API keys for local/controlled deployments and institutional OIDC for production identity integration. API keys are SHA-256 matched against `AUTH_KEYS_JSON`; plaintext keys are not stored in PostgreSQL or audit details. OIDC accepts signed RS256 JWTs, obtains public keys from a bounded HTTPS JWKS endpoint, validates signature, issuer, audience, expiry, issued-at/not-before time and subject, then maps external groups to exactly one TRACE role through an explicit allowlist. Raw external role names never grant TRACE privileges. Browser credentials remain in memory and disappear on reload.

Production startup rejects known development keys, empty/wildcard host policies, invalid role maps, unsafe DB pool bounds and PostgreSQL superuser runtime connections.

| Role | Mutations |
|---|---|
| analyst | Ingest evidence, reconcile wealth, scan context, create/appeal cases |
| reviewer | Independently review claims and signals, review/redact cases, appeal/withdraw |
| publisher | Publish reviewed text, withdraw releases |
| admin | Ingest/operate, access restricted artifacts, read audit; cannot substitute for reviewer/publisher |

Both `/api/v1/*` and `/api/internal/*` require authentication. Existing graph/compare/investigation POSTs allow analyst/reviewer/admin; legacy source writes allow analyst/admin. Evidence downloads require analyst/reviewer/admin and hash verification, with RESTRICTED evidence limited to admin. Public endpoints expose only explicit release projections. Independent subject identities are checked for case creator, reviewer and publisher; the operator must ensure they correspond to distinct accountable people.

## Deployment controls

1. Use `scripts/bootstrap_production.py` once. Protect the generated files with OS permissions/secret management. On Windows, enforce appropriate NTFS ACLs; POSIX file mode 0600 alone is not an NTFS access policy.
2. Put public access behind TLS and the shipped allowlist gateway. Port 8000 and PostgreSQL belong to an internal/VPN network. An API key should not cross plaintext public networks.
3. Use a non-superuser runtime DB role separate from the migration owner; no schema-owner credentials in the API container. Do not grant audit/history deletion rights.
4. Enforce rate limits at the internal proxy too. Public gateway rate-limits public APIs; the app itself is not a distributed rate limiter.
5. Configure source egress allowlists and private encrypted evidence storage. Protect raw evidence, backups and operational logs as personal-data-bearing artifacts.
6. For institutional deployment set `AUTH_MODE=oidc`, configure the institution-approved issuer/audience/JWKS endpoint and an explicit `OIDC_ROLE_MAP_JSON`, and enforce MFA at the IdP. `hybrid` is intended only for a controlled migration window; remove API-key access after migration.
7. Rotate role keys and DB credentials deliberately; remove old hashes and restart. Key identity changes are operationally accountable and must be recorded by the operator. Do not reuse a reviewer/publisher identity across people.

Bearer headers and request bodies are bounded, write origins must match, hosts are allowlisted and UI output uses text nodes. Security headers restrict scripts/styles to local content, block framing and disable MIME sniffing. Evidence is downloaded as octet-stream, not rendered HTML. There is no wildcard CORS policy.

The audit/history protections detect ordinary runtime modification but do not protect against a database owner, filesystem administrator or colluding institutional operators. Export and independently sign/checkpoint the audit tail off-host. WORM/object-lock custody, external signature service, SIEM, formal penetration testing and jurisdiction-specific record/tenant access controls are necessary deployment extensions, not certified features of this MVP. See [THREAT_MODEL.md](THREAT_MODEL.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Reporting a vulnerability

Do not post keys, personal evidence or exploit data in a public issue. Contact the repository maintainer privately through an approved channel or GitHub private vulnerability reporting if enabled. The repository does not advertise a verified incident-response mailbox.

## Historical reads

Immutable temporal versions and PostgreSQL commit receipts are protected from application writes; capture/finalization use fixed-search-path database trigger/functions. Runtime has SELECT only on temporal internals. Current authorization still controls old snapshots: a historical artifact classification cannot bypass a later restriction. Public APIs do not provide historical withdrawn releases. A privileged DBA can still disable triggers or alter clocks; maintain independent checkpoints and time controls.

Commit receipt identities include the originating PostgreSQL cluster, preventing reused transaction IDs after logical restore from backdating new assertions. Unresolved foreign receipts and unsafe transaction-ID ages stop historical reads. The cluster identity wrapper returns only the system identifier, using a fixed `pg_catalog` search path; its owner needs explicit provider permission for `pg_control_system()` where restricted.
