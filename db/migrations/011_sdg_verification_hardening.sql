-- TRACE v0.5: official UN SDG evidence, deterministic recalculation and operational hardening.
INSERT INTO sources(code,name,publisher,source_type,base_uri,jurisdiction,license,authority_level,is_demo)
VALUES (
    'UN_SDG',
    'Global SDG Indicators Database API',
    'United Nations Statistics Division',
    'OFFICIAL_STATISTICS',
    'https://unstats.un.org/SDGAPI',
    'GLOBAL',
    'UNSD source terms apply; preserve publisher metadata and attribution',
    'OFFICIAL',
    false
)
ON CONFLICT (code) DO UPDATE SET
    name=EXCLUDED.name,
    publisher=EXCLUDED.publisher,
    source_type=EXCLUDED.source_type,
    base_uri=EXCLUDED.base_uri,
    jurisdiction=EXCLUDED.jurisdiction,
    authority_level=EXCLUDED.authority_level,
    active=TRUE,
    is_demo=FALSE;

CREATE TABLE sdg_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id UUID NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    observation_hash TEXT NOT NULL,
    series_code TEXT NOT NULL,
    series_description TEXT,
    geo_area_code TEXT,
    geo_area_name TEXT,
    time_period_start NUMERIC,
    value_text TEXT,
    value_numeric NUMERIC,
    goals JSONB NOT NULL DEFAULT '[]'::jsonb,
    targets JSONB NOT NULL DEFAULT '[]'::jsonb,
    indicators JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_text TEXT,
    footnotes JSONB NOT NULL DEFAULT '[]'::jsonb,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_observation JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_record_id, observation_hash)
);

CREATE INDEX idx_sdg_series_period ON sdg_observations(series_code,time_period_start);
CREATE INDEX idx_sdg_series_geo_period ON sdg_observations(series_code,geo_area_code,time_period_start);
CREATE INDEX idx_sdg_source_record ON sdg_observations(source_record_id);
CREATE INDEX idx_sdg_dimensions_gin ON sdg_observations USING gin(dimensions);
CREATE INDEX idx_sdg_attributes_gin ON sdg_observations USING gin(attributes);

CREATE TABLE recalculation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id UUID NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    engine_version TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN (
        'count_observations','count_distinct_geographies','sum_values','mean_values','percent_change'
    )),
    input_spec JSONB NOT NULL,
    result JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_recalculation_source_created ON recalculation_runs(source_record_id,created_at DESC);

CREATE TABLE claim_verification_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id UUID NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    recalculation_run_id UUID NOT NULL REFERENCES recalculation_runs(id) ON DELETE RESTRICT,
    claim_id UUID REFERENCES claims(id) ON DELETE SET NULL,
    assertion_text TEXT NOT NULL,
    asserted_value NUMERIC NOT NULL,
    calculated_value NUMERIC NOT NULL,
    tolerance NUMERIC NOT NULL CHECK(tolerance >= 0),
    delta NUMERIC NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('VERIFIED','REFUTED','INDETERMINATE')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_claim_verification_source_created
    ON claim_verification_runs(source_record_id,created_at DESC);
CREATE INDEX idx_claim_verification_status_created
    ON claim_verification_runs(status,created_at DESC);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim_source
    ON claim_evidence(claim_id,source_record_id) WHERE source_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_relationships_active_subject_object
    ON relationships(subject_entity_id,relationship_type,object_entity_id)
    WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_source_records_source_retrieved
    ON source_records(source_id,retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_import_batches_status_started
    ON import_batches(status,started_at DESC);


-- Verification evidence and calculation receipts are append-only.
CREATE TRIGGER sdg_observations_immutable
    BEFORE UPDATE OR DELETE ON sdg_observations
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER sdg_observations_no_truncate
    BEFORE TRUNCATE ON sdg_observations
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER recalculation_runs_immutable
    BEFORE UPDATE OR DELETE ON recalculation_runs
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER recalculation_runs_no_truncate
    BEFORE TRUNCATE ON recalculation_runs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER claim_verification_runs_immutable
    BEFORE UPDATE OR DELETE ON claim_verification_runs
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER claim_verification_runs_no_truncate
    BEFORE TRUNCATE ON claim_verification_runs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
