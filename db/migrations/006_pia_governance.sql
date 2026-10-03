-- Additive migration: preserve 001-005 and their checksums.
CREATE TABLE audit_events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);
CREATE FUNCTION audit_chain_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(7450206);
    NEW.id := nextval('audit_events_id_seq');
    SELECT event_hash INTO NEW.previous_hash FROM audit_events ORDER BY id DESC LIMIT 1;
    NEW.previous_hash := COALESCE(NEW.previous_hash, repeat('0',64));
    NEW.event_hash := encode(digest(NEW.previous_hash || jsonb_build_array(
        NEW.id, NEW.occurred_at AT TIME ZONE 'UTC', NEW.actor, NEW.action, NEW.resource, NEW.details)::text,
        'sha256'), 'hex');
    RETURN NEW;
END $$;
CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only';
END $$;
CREATE TRIGGER audit_insert BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_chain_insert();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE INDEX idx_audit_time ON audit_events(occurred_at);

ALTER TABLE claims ADD COLUMN created_by TEXT;
ALTER TABLE claims ADD COLUMN reviewed_by TEXT;
ALTER TABLE claims ADD COLUMN reviewed_at TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE source_records ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE raw_artifacts ADD COLUMN access_class TEXT NOT NULL DEFAULT 'INTERNAL'
    CHECK(access_class IN ('INTERNAL','RESTRICTED'));
ALTER TABLE relationships ADD CONSTRAINT relationship_valid_interval
    CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from);
ALTER TABLE claims ADD CONSTRAINT claim_valid_interval
    CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from);

CREATE TABLE import_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    dataset_id TEXT NOT NULL,
    format TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    source_record_id UUID REFERENCES source_records(id),
    status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED')),
    result JSONB,
    error_code TEXT,
    created_by TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE(source_id,dataset_id,payload_hash)
);
CREATE TABLE wealth_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL CHECK(period_end > period_start),
    currency CHAR(3) NOT NULL,
    inputs JSONB NOT NULL,
    result JSONB NOT NULL,
    engine_version TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_wealth_entity ON wealth_submissions(entity_id,period_end);
CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id),
    title TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','REVIEWED','PUBLISHED','WITHDRAWN')),
    created_by TEXT NOT NULL,
    reviewed_by TEXT,
    review_note TEXT,
    publication_title TEXT,
    publication_summary TEXT,
    published_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK(reviewed_by IS NULL OR reviewed_by <> created_by),
    CHECK(published_by IS NULL OR (published_by <> created_by AND published_by <> reviewed_by))
);
CREATE TABLE case_evidence (
    case_id UUID NOT NULL REFERENCES cases(id),
    claim_id UUID NOT NULL REFERENCES claims(id),
    PRIMARY KEY(case_id,claim_id)
);
CREATE TABLE case_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE conflict_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id),
    rule_version TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    signal_type TEXT NOT NULL,
    evidence JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DISMISSED','ESCALATED')),
    reviewed_by TEXT,
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ
);
CREATE TABLE public_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    publication_note TEXT NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    withdrawn_at TIMESTAMPTZ
);
CREATE INDEX idx_public_active ON public_releases(published_at) WHERE withdrawn_at IS NULL;

INSERT INTO sources(code,name,publisher,source_type,authority_level,is_demo) VALUES
('OCDS_IMPORT','OCDS user supplied export','Configured operator','PROCUREMENT','USER_SUPPLIED',false),
('BODS_IMPORT','BODS 0.3 user supplied statements','Configured operator','OWNERSHIP','USER_SUPPLIED',false),
('TED_IMPORT','TED normalized export','Configured operator','PROCUREMENT','USER_SUPPLIED',false),
('PPDS_IMPORT','PPDS style normalized export','Configured operator','PROCUREMENT','USER_SUPPLIED',false),
('TRACE_IMPORT','TRACE normalized evidence','Configured operator','EVIDENCE','USER_SUPPLIED',false),
('DECLARATIONS','Operator supplied wealth declarations','Configured operator','DECLARATION','USER_SUPPLIED',false),
('DEMO','Synthetic demo fixtures','TRACE-PIA developers','DEMO','SYNTHETIC',true);
