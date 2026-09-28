\set ON_ERROR_STOP on

-- This fixture intentionally links the entity created by the real GLEIF ingestion
-- to a deterministic test contract node. It validates that an externally ingested
-- canonical entity can participate in the authoritative Path Finder.

INSERT INTO entities(
    id, entity_type, canonical_name, normalized_name, jurisdiction_code, status
) VALUES (
    '00000000-0000-0000-0000-00000000c001',
    'CONTRACT',
    'TRACE CI Smoke Contract',
    'trace ci smoke contract',
    'EU',
    'ACTIVE'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO claims(
    id,
    subject_entity_id,
    predicate,
    object_entity_id,
    literal_value,
    claim_type,
    verification_status
) VALUES (
    '00000000-0000-0000-0000-00000000c101',
    :'source_entity_id'::uuid,
    'RECEIVED_CONTRACT',
    '00000000-0000-0000-0000-00000000c001',
    '{"fixture":"docker-smoke","purpose":"integration-validation"}'::jsonb,
    'FACT',
    'VERIFIED_PRIMARY'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO claim_evidence(
    id,
    claim_id,
    source_record_id,
    extraction_method,
    extractor_version,
    evidence_strength
)
SELECT
    '00000000-0000-0000-0000-00000000c151',
    '00000000-0000-0000-0000-00000000c101',
    sr.id,
    'CI_SMOKE_FIXTURE',
    'trace-docker-smoke-v1',
    'E0'
FROM source_records sr
JOIN sources s ON s.id = sr.source_id
WHERE s.code = 'GLEIF'
  AND sr.external_id = :'test_lei'
ORDER BY sr.retrieved_at DESC
LIMIT 1
ON CONFLICT (id) DO NOTHING;

INSERT INTO relationships(
    id,
    subject_entity_id,
    relationship_type,
    object_entity_id,
    relationship_status,
    derivation_method,
    claim_id
) VALUES (
    '00000000-0000-0000-0000-00000000c201',
    :'source_entity_id'::uuid,
    'RECEIVED_CONTRACT',
    '00000000-0000-0000-0000-00000000c001',
    'ACTIVE',
    'CI_SMOKE_FIXTURE',
    '00000000-0000-0000-0000-00000000c101'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO relationship_observations(
    id,
    source_id,
    source_record_id,
    canonical_relationship_id,
    subject_entity_id,
    relationship_type,
    object_entity_id,
    semantic_key,
    details
)
SELECT
    '00000000-0000-0000-0000-00000000c301',
    s.id,
    sr.id,
    '00000000-0000-0000-0000-00000000c201',
    :'source_entity_id'::uuid,
    'RECEIVED_CONTRACT',
    '00000000-0000-0000-0000-00000000c001',
    'ci-smoke-' || :'source_entity_id',
    '{"fixture":"docker-smoke","source":"real-gleif-ingestion"}'::jsonb
FROM source_records sr
JOIN sources s ON s.id = sr.source_id
WHERE s.code = 'GLEIF'
  AND sr.external_id = :'test_lei'
ORDER BY sr.retrieved_at DESC
LIMIT 1
ON CONFLICT (id) DO NOTHING;
