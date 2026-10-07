# Multi-source statistical verification

## Scope

TRACE 0.6 extends the UN/SDG verification protocol to multiple independent official statistical publishers without changing the evidence/provenance guarantees established in 0.5.

Supported provider codes:

| Provider | Official interface | TRACE code |
|---|---|---|
| United Nations Statistics Division | SDG API | UN_SDG |
| Eurostat | Dissemination Statistics API / JSON-stat | EUROSTAT |
| World Bank | Indicators API v2 | WORLD_BANK |
| OECD | Data Explorer SDMX REST | OECD |
| International Monetary Fund | DataMapper API v2 | IMF |
| Instituto Nacional de Estadística, Spain | INEbase JSON API | INE_ES |
| Office for National Statistics, UK | ONS API v1 | ONS_UK |

The national-statistics layer is intentionally implemented with concrete official offices rather than a fictional generic government API. Additional national offices can implement the same canonical connector contract.

## Verification pipeline

~~~
official provider
  -> provider-specific bounded query
  -> exact upstream response capture
  -> Evidence Vault + SHA-256
  -> source_record
  -> canonical statistical_observations
  -> deterministic Decimal recalculation
  -> one-provider verification
  -> optional cross-source semantic contract
  -> consensus / conflict / insufficient result
  -> immutable receipt + audit chain
~~~

There is no synthetic fallback. An unavailable or malformed publisher does not become a successful verification.

## Canonical observation contract

Provider responses are normalized to:

~~~
provider_code
dataset_code
series_code
geo_code
geo_name
time_period
value_text
value_numeric
unit
frequency
measure
observation_status
dimensions
attributes
raw_observation
~~~

value_text always preserves the publisher representation. value_numeric is populated only when the source representation is a plain decimal. Qualified values such as <0.1, .., flags, suppressed values or textual estimates are not silently converted.

The exact normalized observation is hashed and linked to its immutable source record. The evidence artifact also retains the upstream response envelope and response hashes.

## One-provider verification

POST /api/internal/statistics/verify

The provider result determines VERIFIED or REFUTED. Example requests in this repository intentionally avoid presenting a placeholder numeric assertion as a real-world fact.

## Cross-source verification

POST /api/internal/statistics/cross-verify

Cross-source comparison requires at least two distinct providers. It never assumes that indicators with similar names are equivalent.

The caller must declare a semantic contract containing concept identifier and label, unit, frequency, geography scope, period, transformation and a detailed comparability note. Each provider must also include a mapping_note explaining why its native series/query is treated as an implementation of that contract.

## Cross-source statuses

### CONSENSUS_VERIFIED

All requested providers completed successfully, at least two results are available, provider values are within source_spread_tolerance, and their arithmetic mean is within assertion_tolerance of the asserted value.

### CONSENSUS_REFUTED

Providers agree within the source-spread tolerance, but their consensus is outside the assertion tolerance.

### SOURCE_CONFLICT

All providers completed, but the calculated values differ by more than the permitted source-spread tolerance.

This is not automatically evidence that a publisher is wrong. It can indicate different definitions, vintages, seasonal adjustments, geographic concepts, revisions, units or transformations.

### INSUFFICIENT

At least one requested provider failed, or fewer than two usable provider calculations remain. TRACE does not silently discard an unavailable requested source and then report consensus.

## Provider-specific boundaries

### Eurostat

TRACE uses the official dissemination Statistics API and parses JSON-stat datasets. Dimension positions are decoded explicitly. A response exceeding the configured observation bound is rejected.

### World Bank

TRACE uses Indicators API v2. Pagination metadata is checked across every requested page. If page counts or total element counts change during retrieval, or if the final count is incomplete, the snapshot is rejected.

### OECD

TRACE uses the Data Explorer SDMX REST endpoint and requests SDMX-CSV. The dataflow, agency, version and SDMX key remain explicit query inputs. Dataset semantics are never inferred from a label.

### IMF

TRACE uses the official IMF DataMapper v2 API for the time series available through DataMapper. This is an official IMF source but does not represent every dataset exposed by the separate IMF Data Portal SDMX interfaces. A future connector can add the broader Data Portal SDMX surface without changing the canonical verification model.

### Spain INE

TRACE uses servicios.ine.es INEbase JSON table data. Table identifiers and returned series metadata are preserved. The connector does not invent geographic mappings from series names.

### UK ONS

TRACE uses the official ONS v1 API. For deterministic evidence, wildcard observation requests are rejected: each requested dimension set must resolve to exactly one observation. Multiple explicit points can be requested in one TRACE import.

## Reproducibility

Once captured, a snapshot can be recalculated without network access using POST /api/internal/statistics/recalculate.

The recalculation receipt stores source record, engine version, operation, filters, periods, aggregation, result, actor and timestamp. Cross-source receipts additionally store the semantic contract, each provider result, spread, consensus value and mapping notes.

## Security and custody

Provider base URLs are pinned to their official HTTPS hosts in code. Arbitrary caller-supplied upstream URLs are not accepted.

All statistical observation rows and cross-source verification receipts are append-only under both database triggers and runtime-role grants. The normal backup/restore drill includes the new migration and continues to verify evidence-object completeness and the full audit chain.

## Limitations

Cross-source agreement is not equivalent to scientific truth. Multiple organizations can derive data from the same national source, use the same methodology, or publish different vintages. TRACE therefore records source identity and an explicit semantic contract rather than presenting provider count as an independence score.

Institutional use should add reviewed indicator mappings, methodology/version metadata, publisher release calendars and domain-specific validation rules for the statistics being compared.
