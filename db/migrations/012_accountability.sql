-- TRACE-ACCOUNT v0.1, additive to 001-011. No destructive changes.
-- All assessments and reviews are immutable; TRACE audit_events stores chained activity.
CREATE TABLE IF NOT EXISTS accountability_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key TEXT NOT NULL UNIQUE CHECK (length(project_key) BETWEEN 2 AND 160),
    title TEXT NOT NULL,
    jurisdiction CHAR(2) NOT NULL,
    source_system TEXT NOT NULL CHECK (source_system IN ('manual','oc4ids','trace','evidence_x')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS accountability_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES accountability_projects(id),
    input_sha256 CHAR(64) NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    input_json JSONB NOT NULL,
    result_json JSONB NOT NULL,
    submitted_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id,input_sha256)
);
CREATE INDEX IF NOT EXISTS idx_account_project_created
    ON accountability_assessments(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS accountability_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES accountability_assessments(id),
    reviewer TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN (
        'NEEDS_INFORMATION','DISPUTED','READY_FOR_EXTERNAL_AUDIT')),
    note TEXT NOT NULL CHECK (length(note) BETWEEN 20 AND 3000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(assessment_id,reviewer)
);
-- Prevent changes to already submitted source evidence and independent reviews.
CREATE OR REPLACE FUNCTION accountability_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Accountability assessments and reviews are append-only';
END $$;
DROP TRIGGER IF EXISTS accountability_assessment_immutable ON accountability_assessments;
CREATE TRIGGER accountability_assessment_immutable
    BEFORE UPDATE OR DELETE ON accountability_assessments
    FOR EACH ROW EXECUTE FUNCTION accountability_immutable();
DROP TRIGGER IF EXISTS accountability_review_immutable ON accountability_reviews;
CREATE TRIGGER accountability_review_immutable
    BEFORE UPDATE OR DELETE ON accountability_reviews
    FOR EACH ROW EXECUTE FUNCTION accountability_immutable();
