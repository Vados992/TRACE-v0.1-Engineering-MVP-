
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name_trgm ON entities USING gin(normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entity_names_name_trgm ON entity_names USING gin(normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entity_identifiers_entity ON entity_identifiers(entity_id);
CREATE INDEX IF NOT EXISTS idx_source_records_external ON source_records(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_claims_subject_predicate ON claims(subject_entity_id, predicate);
CREATE INDEX IF NOT EXISTS idx_claims_object ON claims(object_entity_id) WHERE object_entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_relationships_subject ON relationships(subject_entity_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_relationships_object ON relationships(object_entity_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_relationships_time ON relationships(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_money_payer ON money_flows(payer_entity_id);
CREATE INDEX IF NOT EXISTS idx_money_recipient ON money_flows(recipient_entity_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owner ON ownership_interests(owner_entity_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owned ON ownership_interests(owned_entity_id);

CREATE OR REPLACE VIEW verified_relationships AS
SELECT r.*, c.verification_status, c.claim_type
FROM relationships r
JOIN claims c ON c.id = r.claim_id
WHERE c.claim_type <> 'HYPOTHESIS'
  AND c.verification_status IN ('VERIFIED_PRIMARY','VERIFIED_AUTHORITATIVE','CORROBORATED')
  AND r.superseded_at IS NULL;

CREATE OR REPLACE VIEW public_entity_summary AS
SELECT e.id, e.entity_type, e.canonical_name, e.jurisdiction_code, e.status,
       COUNT(DISTINCT i.id) AS identifier_count,
       COUNT(DISTINCT r.id) AS relationship_count
FROM entities e
LEFT JOIN entity_identifiers i ON i.entity_id = e.id
LEFT JOIN relationships r ON r.subject_entity_id = e.id OR r.object_entity_id = e.id
GROUP BY e.id;
