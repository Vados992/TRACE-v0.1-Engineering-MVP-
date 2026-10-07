-- TRACE v0.6: multi-source official statistical verification.
INSERT INTO sources(
    code,name,publisher,source_type,base_uri,jurisdiction,license,authority_level,is_demo
) VALUES
(
    'EUROSTAT','Eurostat dissemination statistics API','Eurostat',
    'OFFICIAL_STATISTICS','https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0',
    'EU','Eurostat reuse policy applies','OFFICIAL',false
),
(
    'WORLD_BANK','World Bank Indicators API','World Bank',
    'OFFICIAL_STATISTICS','https://api.worldbank.org/v2',
    'GLOBAL','World Bank data terms apply','OFFICIAL',false
),
(
    'OECD','OECD Data Explorer SDMX API','Organisation for Economic Co-operation and Development',
    'OFFICIAL_STATISTICS','https://sdmx.oecd.org/public/rest',
    'GLOBAL','OECD terms and conditions apply','OFFICIAL',false
),
(
    'IMF','IMF DataMapper API','International Monetary Fund',
    'OFFICIAL_STATISTICS','https://www.imf.org/external/datamapper/api/v2',
    'GLOBAL','IMF data terms apply','OFFICIAL',false
),
(
    'INE_ES','INEbase JSON API','Instituto Nacional de Estadística (Spain)',
    'NATIONAL_OFFICIAL_STATISTICS','https://servicios.ine.es/wstempus/js/EN',
    'ES','INE Spain open-data terms apply','OFFICIAL',false
),
(
    'ONS_UK','Office for National Statistics API','Office for National Statistics (United Kingdom)',
    'NATIONAL_OFFICIAL_STATISTICS','https://api.beta.ons.gov.uk/v1',
    'GB','Open Government Licence terms apply','OFFICIAL',false
)
ON CONFLICT (code) DO UPDATE SET
    name=EXCLUDED.name,
    publisher=EXCLUDED.publisher,
    source_type=EXCLUDED.source_type,
    base_uri=EXCLUDED.base_uri,
    jurisdiction=EXCLUDED.jurisdiction,
    license=EXCLUDED.license,
    authority_level=EXCLUDED.authority_level,
    active=TRUE,
    is_demo=FALSE;

CREATE TABLE statistical_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id UUID NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    observation_hash TEXT NOT NULL,
    provider_code TEXT NOT NULL,
    dataset_code TEXT NOT NULL,
    series_code TEXT NOT NULL,
    geo_code TEXT,
    geo_name TEXT,
    time_period TEXT NOT NULL,
    value_text TEXT,
    value_numeric NUMERIC,
    unit TEXT,
    frequency TEXT,
    measure TEXT,
    observation_status TEXT,
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_observation JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_record_id,observation_hash)
);

CREATE INDEX idx_stat_obs_provider_dataset_period
    ON statistical_observations(provider_code,dataset_code,time_period);
CREATE INDEX idx_stat_obs_provider_series_geo_period
    ON statistical_observations(provider_code,series_code,geo_code,time_period);
CREATE INDEX idx_stat_obs_source_record
    ON statistical_observations(source_record_id);
CREATE INDEX idx_stat_obs_dimensions_gin
    ON statistical_observations USING gin(dimensions);
CREATE INDEX idx_stat_obs_attributes_gin
    ON statistical_observations USING gin(attributes);

-- Make existing UN SDG captures visible to the canonical statistical layer without
-- changing the backwards-compatible sdg_observations table.
INSERT INTO statistical_observations(
    source_record_id,observation_hash,provider_code,dataset_code,series_code,
    geo_code,geo_name,time_period,value_text,value_numeric,unit,frequency,measure,
    observation_status,dimensions,attributes,raw_observation
)
SELECT
    source_record_id,
    observation_hash,
    'UN_SDG',
    series_code,
    series_code,
    geo_area_code,
    geo_area_name,
    time_period_start::text,
    value_text,
    value_numeric,
    NULL,
    NULL,
    NULL,
    NULL,
    dimensions,
    attributes,
    raw_observation
FROM sdg_observations
ON CONFLICT(source_record_id,observation_hash) DO NOTHING;

CREATE TABLE cross_source_verification_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assertion_text TEXT NOT NULL,
    asserted_value NUMERIC NOT NULL,
    assertion_tolerance NUMERIC NOT NULL CHECK(assertion_tolerance >= 0),
    source_spread_tolerance NUMERIC NOT NULL CHECK(source_spread_tolerance >= 0),
    semantic_contract JSONB NOT NULL,
    provider_results JSONB NOT NULL,
    consensus_value NUMERIC,
    spread NUMERIC,
    status TEXT NOT NULL CHECK(status IN (
        'CONSENSUS_VERIFIED',
        'CONSENSUS_REFUTED',
        'SOURCE_CONFLICT',
        'INSUFFICIENT'
    )),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cross_source_verification_members (
    run_id UUID NOT NULL REFERENCES cross_source_verification_runs(id) ON DELETE RESTRICT,
    provider_code TEXT NOT NULL,
    source_record_id UUID NOT NULL REFERENCES source_records(id) ON DELETE RESTRICT,
    recalculation_run_id UUID NOT NULL REFERENCES recalculation_runs(id) ON DELETE RESTRICT,
    calculated_value NUMERIC NOT NULL,
    mapping_note TEXT NOT NULL,
    PRIMARY KEY(run_id,provider_code)
);

CREATE INDEX idx_cross_source_status_created
    ON cross_source_verification_runs(status,created_at DESC);
CREATE INDEX idx_cross_source_member_source
    ON cross_source_verification_members(source_record_id);
CREATE INDEX idx_cross_source_member_recalc
    ON cross_source_verification_members(recalculation_run_id);

CREATE TRIGGER statistical_observations_immutable
    BEFORE UPDATE OR DELETE ON statistical_observations
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER statistical_observations_no_truncate
    BEFORE TRUNCATE ON statistical_observations
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER cross_source_runs_immutable
    BEFORE UPDATE OR DELETE ON cross_source_verification_runs
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER cross_source_runs_no_truncate
    BEFORE TRUNCATE ON cross_source_verification_runs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER cross_source_members_immutable
    BEFORE UPDATE OR DELETE ON cross_source_verification_members
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER cross_source_members_no_truncate
    BEFORE TRUNCATE ON cross_source_verification_members
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
