-- TRACE-ACCOUNT official IMPIC open-data import; additive and idempotent.
-- Migration 014 intentionally avoids reserved 013 of the separate TRACE v0.7 branch.
CREATE TABLE IF NOT EXISTS account_impic_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_url TEXT NOT NULL,
    resource_url TEXT NOT NULL,
    year INTEGER NOT NULL CHECK (year BETWEEN 2012 AND 2026),
    raw_sha256 CHAR(64) NOT NULL UNIQUE CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    artifact_path TEXT NOT NULL,
    rows_total INTEGER NOT NULL CHECK (rows_total > 0),
    imported_count INTEGER NOT NULL CHECK (imported_count > 0 AND imported_count <= rows_total),
    invalid_count INTEGER NOT NULL CHECK (invalid_count >= 0 AND invalid_count <= rows_total),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_impic_contracts (
    snapshot_id UUID NOT NULL REFERENCES account_impic_snapshots(id),
    contract_id TEXT NOT NULL CHECK (length(contract_id) BETWEEN 1 AND 150),
    title TEXT NOT NULL,
    contract_price_eur NUMERIC(24,2) CHECK (contract_price_eur >= 0),
    record_sha256 CHAR(64) NOT NULL CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY(snapshot_id, contract_id)
);
CREATE INDEX IF NOT EXISTS account_impic_lookup ON account_impic_contracts(contract_id);
-- Public amounts here are contract *prices*, never proof of cash paid or loss.
CREATE OR REPLACE VIEW account_impic_latest AS
SELECT DISTINCT ON (c.contract_id) c.contract_id,c.title,c.contract_price_eur,
       c.record_sha256,s.resource_url,s.retrieved_at,s.id AS snapshot_id
FROM account_impic_contracts c
JOIN account_impic_snapshots s ON s.id=c.snapshot_id
ORDER BY c.contract_id,s.retrieved_at DESC,s.id DESC;
