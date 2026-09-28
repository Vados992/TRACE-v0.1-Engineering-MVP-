INSERT INTO sources(code,name,publisher,source_type,base_uri,jurisdiction,license,authority_level)
VALUES
('EU_TR','EU Transparency Register','European Parliament, Council of the EU and European Commission','LOBBYING','https://transparency-register.europa.eu','EU',NULL,'OFFICIAL')
ON CONFLICT (code) DO UPDATE SET
  name=EXCLUDED.name,
  publisher=EXCLUDED.publisher,
  source_type=EXCLUDED.source_type,
  base_uri=EXCLUDED.base_uri,
  active=TRUE;

CREATE TABLE IF NOT EXISTS source_entity_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    external_entity_key TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES entities(id),
    mapping_method TEXT NOT NULL,
    confidence NUMERIC(8,6) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source_record_id UUID REFERENCES source_records(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_id, external_entity_key)
);

CREATE TABLE IF NOT EXISTS relationship_build_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id),
    build_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','PARTIAL')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    observations_seen BIGINT NOT NULL DEFAULT 0,
    relationships_created BIGINT NOT NULL DEFAULT 0,
    relationships_reused BIGINT NOT NULL DEFAULT 0,
    conflicts_detected BIGINT NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS relationship_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    canonical_relationship_id UUID REFERENCES relationships(id),
    subject_entity_id UUID NOT NULL REFERENCES entities(id),
    relationship_type TEXT NOT NULL,
    object_entity_id UUID NOT NULL REFERENCES entities(id),
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    amount NUMERIC(24,6),
    currency CHAR(3),
    source_priority INTEGER NOT NULL DEFAULT 100,
    observation_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (
        observation_status IN ('ACTIVE','CONFLICTING','SUPERSEDED','RETRACTED')
    ),
    semantic_key TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (subject_entity_id <> object_entity_id),
    UNIQUE(source_record_id, semantic_key)
);

CREATE INDEX IF NOT EXISTS idx_relationship_observations_canonical
    ON relationship_observations(canonical_relationship_id);
CREATE INDEX IF NOT EXISTS idx_relationship_observations_semantic
    ON relationship_observations(semantic_key);
CREATE INDEX IF NOT EXISTS idx_relationship_observations_pair
    ON relationship_observations(subject_entity_id, relationship_type, object_entity_id);

CREATE TABLE IF NOT EXISTS reconciliation_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conflict_type TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    observation_a UUID NOT NULL REFERENCES relationship_observations(id),
    observation_b UUID NOT NULL REFERENCES relationship_observations(id),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED','IGNORED')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CHECK (observation_a <> observation_b),
    UNIQUE(observation_a, observation_b)
);

CREATE TABLE IF NOT EXISTS procurement_awards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notice_entity_id UUID NOT NULL REFERENCES entities(id),
    buyer_entity_id UUID REFERENCES entities(id),
    winner_entity_id UUID REFERENCES entities(id),
    procedure_identifier TEXT,
    publication_number TEXT NOT NULL,
    decision_date DATE,
    awarded_amount NUMERIC(24,6),
    currency CHAR(3),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    buyer_notice_relationship_id UUID REFERENCES relationships(id),
    notice_winner_relationship_id UUID REFERENCES relationships(id),
    buyer_winner_relationship_id UUID REFERENCES relationships(id),
    money_flow_id UUID REFERENCES money_flows(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_record_id, publication_number, buyer_entity_id, winner_entity_id)
);

CREATE TABLE IF NOT EXISTS lobbying_disclosures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registrant_entity_id UUID NOT NULL REFERENCES entities(id),
    transparency_id TEXT,
    institution_entity_id UUID REFERENCES entities(id),
    policy_entity_id UUID REFERENCES entities(id),
    meeting_date DATE,
    subject TEXT,
    declared_budget_min NUMERIC(24,6),
    declared_budget_max NUMERIC(24,6),
    currency CHAR(3),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    relationship_id UUID REFERENCES relationships(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS policy_lifecycle_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL REFERENCES entities(id),
    lifecycle_relation TEXT NOT NULL,
    object_entity_id UUID NOT NULL REFERENCES entities(id),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    canonical_relationship_id UUID REFERENCES relationships(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (subject_entity_id <> object_entity_id),
    UNIQUE(subject_entity_id, lifecycle_relation, object_entity_id, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_source_entity_mapping_entity ON source_entity_mappings(entity_id);
CREATE INDEX IF NOT EXISTS idx_procurement_awards_buyer ON procurement_awards(buyer_entity_id);
CREATE INDEX IF NOT EXISTS idx_procurement_awards_winner ON procurement_awards(winner_entity_id);
CREATE INDEX IF NOT EXISTS idx_lobbying_registrant ON lobbying_disclosures(registrant_entity_id);
CREATE INDEX IF NOT EXISTS idx_policy_lifecycle_subject ON policy_lifecycle_edges(subject_entity_id);
