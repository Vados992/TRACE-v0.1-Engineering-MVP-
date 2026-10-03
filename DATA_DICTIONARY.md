# Data dictionary

Exact columns, constraints and indexes are defined by `db/migrations/*.sql`; executable field schemas by OpenAPI. UUIDs identify internal objects; publisher IDs retain their explicit namespace.

| Table/group | Grain / key | Meaning |
|---|---|---|
| sources | One publisher/adapter code | Authority, license/URI metadata and `is_demo`; registration is not proof of successful live access |
| source_records | Source + external ID + content hash | Versioned acquired record, retrieval time, parser/schema version, vault URI, metadata |
| raw_artifacts | Source + external ID + SHA-256 | Byte hash, object key, MIME/length and INTERNAL/RESTRICTED access class |
| entities | UUID | Canonical object/type/name/jurisdiction; `is_demo` separates synthetic identity |
| entity_identifiers / names | Namespaced identifier / sourced name | Supplied registry identity and aliases; demo schemes cannot merge into live identifiers |
| persons / organizations / public_bodies | Entity UUID | Domain attributes; absence is unknown, not a negative fact |
| claims | UUID | Subject-predicate-object/literal assertion with FACT/DERIVED/HYPOTHESIS, validity, verification and reviewer |
| claim_evidence | Claim + source/document reference | Locator, extraction method/version, strength and provenance |
| relationships | UUID / canonical semantic interval | Directed asserted edge, valid time, observed time, superseded time and canonical claim |
| relationship_observations | Source record + semantic key | Publisher-specific evidence for a canonical edge; retains reported amount/currency/details |
| reconciliation_conflicts | Paired observations | Numeric inconsistencies across observations, status and source details |
| ownership_interests | Source-backed ownership observation | Optional exact ownership percentage, dates, basis; BODS ranges remain in claim details, not midpoint estimates |
| procurement_awards | Notice + buyer + winner + source | Decision date, explicitly awarded amount/currency, relationship and optional money flow |
| money_flows | Sourced payer/recipient/state | ALLOCATED/COMMITTED/AWARDED/INVOICED/PAID explicitly distinguished; no default conversion to PAID |
| professional_roles | Person + organization + claim | Sourced professional role and period; direct-role scan also reads graph HOLDS_ROLE_IN assertions |
| import_batches | Source + dataset ID + stable payload hash | RUNNING/SUCCEEDED/FAILED, actor, result and sanitized error code; canonical retry reuses successful result |
| wealth_submissions | Person + versioned submission UUID | Period, currency, exact input components/locators, engine result/version, source and actor |
| conflict_signals | Evidence fingerprint + rule version | OPEN/DISMISSED/ESCALATED review context; never a corruption verdict |
| cases / case_evidence / case_events | Case UUID / linked claims / immutable event | OPEN/REVIEWED/PUBLISHED/WITHDRAWN, separate creator/reviewer/publisher, reviewed public text and appeal history |
| public_releases | Approved release UUID | Only redacted title/summary/publication time; withdrawn records excluded from public endpoint |
| audit_events | Serialized BIGSERIAL ID | Actor/action/resource/details, UTC timestamp, previous/event SHA-256; gaps permitted after rollback |
| schema_migrations | Filename + checksum | Applied schema history; owner writes, runtime reads |

## Semantics

* `valid_from/valid_to`: publisher-supported world-time interval. Null means unknown; it is not a fabricated continuous ownership period. `retrieved_at/observed_at` records ingestion time, not the date the relationship began.
* `VERIFIED_PRIMARY/AUTHORITATIVE/CORROBORATED` refers to source/evidence classification. Legacy adapters can classify primary publisher assertions automatically. Independent human review has separate reviewer/time/audit records. `UNVERIFIED`, `CONFLICTED`, `RETRACTED` are retained rather than deleted.
* `E0`–`E5` are inherited evidence-strength codes. The application does not present these as calibrated probabilities or a legal proof standard.
* Monetary fields use PostgreSQL NUMERIC and Python Decimal. Values in different currencies are not summed without a separately sourced valuation policy.
* Ownership ranges are not exact percentages. Identity matching by a supplied registry scheme/ID differs from uncertain name similarity; uncertain resolution requires human action.
* `demo=true`, source DEMO and `DEMO:` identifier namespaces are explicit test labels. Startup does not seed demo people. Test fixtures do not demonstrate real connector access.

## Temporal versions

`temporal_versions`: immutable full row snapshots, table/UUID identity, operation and PostgreSQL xid8. `temporal_commits`: immutable actual transaction commit time, retained independently of PostgreSQL tracker pruning. `temporal_pending`: operational receipt finalization queue. `temporal_control`: immutable activation transaction defining the earliest exact knowledge snapshot. `known_at`: requested system cutoff; `known_from`: actual commit of the selected relationship version. `valid_from/valid_to`: independent fact validity. Baseline rows are never backdated.
