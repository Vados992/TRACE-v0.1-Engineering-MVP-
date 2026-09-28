CREATE TABLE IF NOT EXISTS raw_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    object_key TEXT NOT NULL,
    media_type TEXT,
    byte_length BIGINT NOT NULL CHECK (byte_length >= 0),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, external_id, content_hash)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    job_type TEXT NOT NULL,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','PARTIAL')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    source_record_id UUID REFERENCES source_records(id),
    raw_artifact_id UUID REFERENCES raw_artifacts(id),
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS entity_resolution_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    left_entity_id UUID NOT NULL REFERENCES entities(id),
    right_entity_id UUID NOT NULL REFERENCES entities(id),
    score NUMERIC(8,6) NOT NULL CHECK (score >= 0 AND score <= 1),
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','MERGED','REJECTED','DEFERRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CHECK (left_entity_id <> right_entity_id)
);

CREATE TABLE IF NOT EXISTS investigations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT,
    source_entity_id UUID REFERENCES entities(id),
    target_entity_id UUID REFERENCES entities(id),
    from_time TIMESTAMPTZ,
    to_time TIMESTAMPTZ,
    max_depth INTEGER NOT NULL DEFAULT 6 CHECK (max_depth BETWEEN 1 AND 8),
    verified_only BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    result JSONB,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_artifacts_source_external
    ON raw_artifacts(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status_started
    ON ingest_jobs(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_resolution_queue_status_score
    ON entity_resolution_queue(status, score DESC);
CREATE INDEX IF NOT EXISTS idx_investigations_created
    ON investigations(created_at DESC);
