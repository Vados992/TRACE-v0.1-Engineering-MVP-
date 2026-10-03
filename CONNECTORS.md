# Real connectors and import contracts

No connector silently substitutes synthetic data. Network failure returns an upstream error; mapped schema errors return 422; missing operator configuration returns 503. Fixture files exist exclusively for deterministic tests and explicit offline verification.

| Source | Executable path | Access / limits | Meaning and caveats |
|---|---|---|---|
| GLEIF | `POST /api/v1/relationship-intelligence/ownership/gleif/{lei}` | Public HTTPS JSON API; no key | LEI identity and accounting consolidation parents, not proof of natural-person beneficial ownership |
| TED | `POST /api/v1/relationship-intelligence/procurement/ted/search` | Public published-notice Search API, bounded request | Extracts explicit buyers/winners/amounts from supported fields; awarded amount is not payment |
| EUR-Lex / Cellar | `POST /api/v1/relationship-intelligence/policy/eurlex/{celex}` | Public RDF tree metadata, no key | Published legal-document relations; namespace mapping is explicit |
| Find a Tender OCDS | `POST /api/internal/connectors/fetch`, `source=ocds` | Actual public release-package endpoint; request limit 1–25 | OCDS 1.1 parties and active awards; suppliers must resolve; multiple-supplier total is not allocated as individual payments |
| Open Ownership UK | Same route, `source=openownership`, bounded `limit` | Actual publisher BODS 0.4 ZIP, bounded HTTPS byte-range retrieval | Republished UK PSC/overseas data, publisher release **2025-03-11**. Imports 20 complete NDJSON statements per limit unit from the first 1 MiB ZIP range (up to 500 statements); explicit partial-snapshot scope. Not the current Companies House API |
| Configured BODS | Same route, `source=bods` | Operator-set HTTPS `BODS_DATASET_URL`; optional Bearer credential | Explicit BODS 0.3 or 0.4 arrays; no mixed-version reinterpretation; only supported interest types |
| Configured PPDS-style export | Same route, `source=ppds` | Operator-set HTTPS `PPDS_DATASET_URL`; optional Bearer credential | Actual HTTP retrieval of `trace-procurement-export/1`; institution-specific native PPDS mappings/access must be supplied |
| EU Transparency | `POST /api/v1/relationship-intelligence/lobbying/import` | Authorized official export supplied by operator | File import contract; no automatic synchronization is claimed |
| Wealth declarations | `POST /api/internal/wealth/reconcile` | Authorized evidence and component locators supplied by operator | No access to tax/bank/private property registries is claimed |

The native TED connector is the available public procurement ingestion path when an institutional PPDS service is inaccessible. The PPDS-style mapped adapter is explicitly identified as an operator mapping contract, not a fabricated standard or an official government gateway. Private registries, bank/tax systems and non-public beneficial-ownership services require real credentials, lawful authorization, contractual/interface documentation and an approved mapping. There are no fake APIs representing those systems.

## Source configuration

Defaults are in `.env.example`. Configure only operator-approved endpoints, then restart the API. URLs require HTTPS, port 443 and public DNS addresses. Private/reserved IPs, embedded credentials and unsafe credentialed redirects are rejected. Responses are capped by `HTTP_MAX_RESPONSE_BYTES` (20 MiB; Cellar RDF has a separate bounded 64 MiB limit); each HTTP request has a timeout. No hidden automatic non-idempotent retries occur. Use an egress allowlist/firewall in deployment to address DNS rebinding and limit publisher access.

For an authenticated export:

```dotenv
BODS_DATASET_URL=https://your-approved-publisher/authorized/export.json
BODS_TOKEN_ENV=BODS_SOURCE_TOKEN
BODS_SOURCE_TOKEN=your-real-secret
PPDS_DATASET_URL=https://your-approved-publisher/mapped-procurement.json
PPDS_TOKEN_ENV=PPDS_SOURCE_TOKEN
PPDS_SOURCE_TOKEN=your-real-secret
```

These example hostnames are documentation placeholders, not live integrations. Production Compose injects the two standard secret variable names. For other environment names, configure deployment environment explicitly. Do not put tokens in URL query parameters. Raw response bodies stay in the private vault and are not echoed in errors.

## Fetch a real OCDS package

```sh
curl -X POST http://127.0.0.1:8000/api/internal/connectors/fetch \
  -H 'Authorization: Bearer trace-dev-analyst-only' -H 'Content-Type: application/json' \
  --data '{"source":"ocds","limit":3,"license":"Publisher license retained in source","legal_basis":"Authorized internal evaluation of public procurement data"}'
```

The request captures exact upstream response bytes as base64, SHA-256, retrieval time, request URL and status inside the protected evidence envelope, alongside normalized statements. Source-record metadata contains response hashes/URLs and snapshot identity; the public API does not expose it. A stable source payload reuses an import batch even if fetched again. An updated payload becomes a new observation; canonical edges can retain multiple observations. Imports never promote mapped assertions to independently verified facts.

## Authorized file import

Send `/api/internal/imports` a JSON envelope:

```json
{"format":"ocds","dataset_id":"publisher:export-id","payload":{"version":"1.1","releases":[]},"license":"actual publisher license","legal_basis":"actual authorized processing purpose","demo":false}
```

An empty package is shown only as envelope structure here; the adapter requires entities and meaningful resolvable references. Actual payloads come from the source. Maximum HTTP input is 5 MiB, 2,000 normalized entities and 5,000 relationships. Partition larger exports into stable publisher batches. `dataset_id` must be stable to retain replay and local-identifier scope. Registry identifiers can connect sources; names alone cannot establish identity.

OCDS local party IDs are scoped by OCID. Active awards become contract nodes, buyer/contract, supplier/contract and buyer/supplier edges. Pending/cancelled awards are skipped with warnings. BODS 0.4 resolves `recordId`, keeps publisher history in evidence, permits explicit GB-COH subject references as minimal registry nodes without inventing names, excludes closed/unresolved owner assertions and retains full interest ranges without inventing exact percentages. For 0.3, `statementID` references are supported. See the actual generated schema for validation and supported normalized relations.

For TED/PPDS mapped files, use `schema=trace-procurement-export/1`, `notices` with `id`, `status=AWARDED`, `decision_date`, buyer/supplier `{scheme,id,name}`, optional `amount/currency`, optional `title/publication_id`. This supported subset does not allocate multi-supplier awards or model institutional payment ledgers. Use native TED or a reviewed publisher mapping for those semantics.

## Publisher documentation

* [OCDS 1.1 reference](https://standard.open-contracting.org/latest/en/schema/reference/)
* [BODS 0.3](https://standard.openownership.org/en/0.3.0/schema/reference.html) and [BODS 0.4 schema browser](https://standard.openownership.org/en/0.4.0/standard/schema-browser.html)
* [TED published-notice Search API](https://docs.ted.europa.eu/api/latest/search.html)
* [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api)
* [Open Ownership UK snapshot and mapping caveats](https://bods-data.openownership.org/source/uk_version_0_4/)

Validate licenses, applicable privacy/access restrictions and publisher freshness for the specific installation; technical public access is not a blanket legal authorization.
