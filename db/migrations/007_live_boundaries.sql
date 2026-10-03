ALTER TABLE entities ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE entities SET is_demo=TRUE WHERE id IN
    (SELECT entity_id FROM entity_identifiers WHERE scheme LIKE 'DEMO:%');
CREATE INDEX idx_entities_demo ON entities(is_demo);
CREATE FUNCTION reject_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'case history is append-only'; END $$;
CREATE TRIGGER case_events_immutable BEFORE UPDATE OR DELETE ON case_events
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER case_events_no_truncate BEFORE TRUNCATE ON case_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_history_mutation();
