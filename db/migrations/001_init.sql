
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_type TEXT NOT NULL,
    base_uri TEXT,
    jurisdiction TEXT,
    license TEXT,
    authority_level TEXT NOT NULL DEFAULT 'OFFICIAL',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','PARTIAL')),
    records_seen BIGINT NOT NULL DEFAULT 0,
    records_created BIGINT NOT NULL DEFAULT 0,
    records_changed BIGINT NOT NULL DEFAULT 0,
    content_hash TEXT,
    software_version TEXT,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    payload_uri TEXT,
    payload_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT,
    raw_payload JSONB,
    UNIQUE (source_id, external_id, payload_hash)
);

CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN (
      'PERSON','ORGANIZATION','PUBLIC_BODY','POLICY','LEGAL_ACT','PROGRAMME','CONTRACT',
      'TENDER','AWARD','GRANT','PAYMENT','FUND','ASSET','MEETING','LOBBY_ACTIVITY','ROLE',
      'DECLARATION','EVENT','DOCUMENT','SOURCE','JURISDICTION','SECTOR'
    )),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    jurisdiction_code TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    scheme TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    issuer TEXT,
    country_code TEXT,
    valid_from DATE,
    valid_to DATE,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    source_record_id UUID REFERENCES source_records(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_identifier
ON entity_identifiers(scheme, identifier_value, COALESCE(country_code,''));

CREATE TABLE IF NOT EXISTS entity_names (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    language TEXT,
    name_type TEXT NOT NULL CHECK (name_type IN ('LEGAL','FORMER','TRADING','ABBREVIATION','TRANSLITERATION','ALIAS')),
    valid_from DATE,
    valid_to DATE,
    source_record_id UUID REFERENCES source_records(id)
);

CREATE TABLE IF NOT EXISTS organizations (
    entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    legal_name TEXT,
    legal_form TEXT,
    registration_country TEXT,
    incorporation_date DATE,
    dissolution_date DATE,
    organization_type TEXT
);

CREATE TABLE IF NOT EXISTS persons (
    entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    public_role BOOLEAN NOT NULL DEFAULT FALSE,
    professional_description TEXT,
    birth_year SMALLINT
);

CREATE TABLE IF NOT EXISTS public_bodies (
    entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    body_type TEXT,
    country_code TEXT,
    parent_body_id UUID REFERENCES public_bodies(entity_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    external_document_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT,
    issuer_entity_id UUID REFERENCES entities(id),
    publication_date DATE,
    canonical_uri TEXT,
    UNIQUE (source_id, external_document_id)
);

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash TEXT NOT NULL,
    object_uri TEXT,
    mime_type TEXT,
    language TEXT,
    parser_version TEXT NOT NULL,
    UNIQUE (document_id, content_hash)
);

CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object_entity_id UUID REFERENCES entities(id),
    literal_value JSONB,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('FACT','DERIVED','HYPOTHESIS')),
    verification_status TEXT NOT NULL CHECK (verification_status IN (
      'VERIFIED_PRIMARY','VERIFIED_AUTHORITATIVE','CORROBORATED','UNVERIFIED','CONFLICTED','RETRACTED'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (object_entity_id IS NOT NULL OR literal_value IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    document_version_id UUID REFERENCES document_versions(id),
    source_record_id UUID REFERENCES source_records(id),
    locator JSONB,
    extraction_method TEXT NOT NULL,
    extractor_version TEXT,
    evidence_strength TEXT NOT NULL CHECK (evidence_strength IN ('E0','E1','E2','E3','E4','E5')),
    CHECK (document_version_id IS NOT NULL OR source_record_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_evidence_source
ON claim_evidence(claim_id, COALESCE(document_version_id, '00000000-0000-0000-0000-000000000000'::uuid),
                  COALESCE(source_record_id, '00000000-0000-0000-0000-000000000000'::uuid));

CREATE TABLE IF NOT EXISTS relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL REFERENCES entities(id),
    relationship_type TEXT NOT NULL,
    object_entity_id UUID NOT NULL REFERENCES entities(id),
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    relationship_status TEXT NOT NULL DEFAULT 'ACTIVE',
    derivation_method TEXT,
    claim_id UUID REFERENCES claims(id),
    CHECK (subject_entity_id <> object_entity_id)
);

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    event_start TIMESTAMPTZ,
    event_end TIMESTAMPTZ,
    jurisdiction TEXT,
    location_text TEXT,
    claim_id UUID REFERENCES claims(id)
);

CREATE TABLE IF NOT EXISTS event_participants (
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entities(id),
    participant_role TEXT,
    PRIMARY KEY (event_id, entity_id)
);

CREATE TABLE IF NOT EXISTS money_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_entity_id UUID NOT NULL REFERENCES entities(id),
    recipient_entity_id UUID NOT NULL REFERENCES entities(id),
    amount NUMERIC(24,6),
    currency CHAR(3),
    flow_type TEXT NOT NULL CHECK (flow_type IN ('GRANT','CONTRACT','PAYMENT','SUBSIDY','LOAN','GUARANTEE','INVESTMENT','TAX_BENEFIT','OTHER')),
    flow_state TEXT CHECK (flow_state IN ('ALLOCATED','COMMITTED','AWARDED','INVOICED','PAID')),
    commitment_date DATE,
    award_date DATE,
    payment_date DATE,
    contract_entity_id UUID REFERENCES entities(id),
    programme_entity_id UUID REFERENCES entities(id),
    source_claim_id UUID NOT NULL REFERENCES claims(id),
    CHECK (payer_entity_id <> recipient_entity_id)
);

CREATE TABLE IF NOT EXISTS ownership_interests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_entity_id UUID NOT NULL REFERENCES entities(id),
    owned_entity_id UUID NOT NULL REFERENCES entities(id),
    ownership_percent NUMERIC(7,4) CHECK (ownership_percent IS NULL OR (ownership_percent >= 0 AND ownership_percent <= 100)),
    control_percent NUMERIC(7,4) CHECK (control_percent IS NULL OR (control_percent >= 0 AND control_percent <= 100)),
    relationship_basis TEXT NOT NULL,
    valid_from DATE,
    valid_to DATE,
    source_claim_id UUID NOT NULL REFERENCES claims(id),
    CHECK (owner_entity_id <> owned_entity_id)
);

CREATE TABLE IF NOT EXISTS professional_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_entity_id UUID NOT NULL REFERENCES entities(id),
    organization_entity_id UUID NOT NULL REFERENCES entities(id),
    role_title TEXT,
    role_type TEXT,
    valid_from DATE,
    valid_to DATE,
    source_claim_id UUID NOT NULL REFERENCES claims(id)
);

CREATE TABLE IF NOT EXISTS contradictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_a UUID NOT NULL REFERENCES claims(id),
    claim_b UUID NOT NULL REFERENCES claims(id),
    contradiction_type TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'OPEN',
    resolution_note TEXT,
    CHECK (claim_a <> claim_b)
);

CREATE TABLE IF NOT EXISTS entity_merge_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id UUID NOT NULL REFERENCES entities(id),
    target_entity_id UUID NOT NULL REFERENCES entities(id),
    merge_reason TEXT NOT NULL,
    algorithm_version TEXT,
    reviewer_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reversed_at TIMESTAMPTZ,
    CHECK (source_entity_id <> target_entity_id)
);
