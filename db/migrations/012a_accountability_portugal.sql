-- TRACE-ACCOUNT: append-only snapshots of official Portuguese open-data responses.
-- No financial/legal conclusions are derived from raw import records.
CREATE TABLE IF NOT EXISTS accountability_portugal_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id UUID NOT NULL REFERENCES source_records(id),
    dataset_slug TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('catalog','contracts')),
    source_url TEXT NOT NULL,
    media_format TEXT NOT NULL CHECK(media_format IN ('json','csv')),
    content_sha256 CHAR(64) NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
    original_bytes BYTEA NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_by TEXT NOT NULL,
    UNIQUE(dataset_slug,kind,source_url,content_sha256)
);
CREATE TABLE IF NOT EXISTS accountability_portugal_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES accountability_portugal_snapshots(id),
    external_key TEXT NOT NULL,
    row_sha256 CHAR(64) NOT NULL CHECK(row_sha256 ~ '^[0-9a-f]{64}$'),
    row_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(snapshot_id,external_key,row_sha256)
);
CREATE INDEX IF NOT EXISTS idx_account_pt_external_key ON accountability_portugal_records(external_key);
CREATE OR REPLACE FUNCTION accountability_pt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Portugal official-source captures are append-only';
END $$;
CREATE TRIGGER accountability_pt_snapshots_immutable BEFORE UPDATE OR DELETE
    ON accountability_portugal_snapshots FOR EACH ROW EXECUTE FUNCTION accountability_pt_immutable();
CREATE TRIGGER accountability_pt_records_immutable BEFORE UPDATE OR DELETE
    ON accountability_portugal_records FOR EACH ROW EXECUTE FUNCTION accountability_pt_immutable();
