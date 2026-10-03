# Threat model

Assets: private source evidence and personal data, source/identity integrity, case/review decisions, operator credentials, audit history and public-release accuracy. Trust boundaries: external publisher → connector, browser → protected API, API → PostgreSQL/vault, reviewer → publisher and private runtime → public gateway.

| Threat | Implemented mitigation | Remaining deployment control |
|---|---|---|
| Anonymous/overprivileged access | Bearer role checks on old and new API routes, explicit public projection, restricted artifact role | OIDC/MFA, identity lifecycle, record/jurisdiction scope and internal network access |
| Accidental public disclosure | Separate public API, gateway allowlist, three-person case process, reviewed text only | Human redaction/relevance/legal review; private backup/log handling |
| Credential theft | Hash-only configuration, token in browser memory, no token error echoes, random production generation | TLS, secrets service, OS ACLs, short-lived credentials/rotation and endpoint protection |
| Request/source payload exhaustion | 5 MiB request cap, 20 MiB; Cellar RDF has a separate bounded 64 MiB limit response cap, normalized item bounds, timeouts, bounded graph queries | Proxy rate/concurrency limits, capacity planning and provider quotas |
| SSRF / malicious endpoint | Operator-only URL config, HTTPS/public-address validation, bounded redirects, no credentialed redirects | Fixed egress allowlist and DNS-rebinding-resistant network policy |
| Wrong identity / provenance fabrication | Explicit identifier namespaces, source hashes/locators, unknown references skipped/warned, synthetic isolation | Validate actual publisher authenticity/semantics and contested identities independently |
| Evidence tampering | Content-addressed atomic writes and verified reads; mismatch gives 409 | OS/object-store retention, independent copies, encryption and custody |
| Time/amount misinterpretation | Common temporal interval, uncertainty, Decimal arithmetic, no missing-value imputation, AWARDED vs PAID | Valuation/FX policy and source date/amount review |
| Collusion / state capture | Distinct creator/reviewer/publisher, reasoned immutable history, linked audit hashes, appeal/withdrawal | External oversight, signed off-host checkpoints, independent reviewer identity/custody |
| DBA/root compromise | Runtime has no superuser/schema-owner/audit deletion rights | DBA can bypass triggers; secure owner access, independent off-host evidence and recovery |
| Source outage/schema drift | Visible 502/422 errors; parser versions and raw bytes retained | Alerts, manual quarantine, replay/reprocess only after approved mapping |
| Supply-chain compromise | Pinned Python dependencies, CI, non-root/read-only runtime container | Approved image digests, dependency review/scans, signed releases and patch policy |

Out of scope for automatic proof: factual truth of a declared register entry, guilt, comprehensive personal wealth, independence of people sharing an institution, and legal authorization merely from a public URL. These must not be inferred from a green health check. The current implementation is a bounded MVP/reference architecture; it has not passed a formal penetration test or certification.
