-- Preserve evidence/history; retire the old parser that mixed RDF subjects and guessed predicates.
UPDATE claims SET verification_status='RETRACTED'
WHERE id IN (SELECT claim_id FROM relationships WHERE derivation_method='CELLAR_RDF_TREE');
UPDATE relationship_observations SET observation_status='SUPERSEDED'
WHERE canonical_relationship_id IN (SELECT id FROM relationships WHERE derivation_method='CELLAR_RDF_TREE');
WITH retired AS (
    UPDATE relationships SET superseded_at=now(),relationship_status='SUPERSEDED'
    WHERE derivation_method='CELLAR_RDF_TREE' AND superseded_at IS NULL RETURNING id
)
INSERT INTO audit_events(actor,action,resource,details)
SELECT 'migration-owner','PARSER_SCOPE_CORRECTION','CELLAR_RDF_TREE',
       jsonb_build_object('retired_relationships',count(*),'replacement','cellar-scope/2',
                          'reason','Require matching RDF subject, explicit CDM predicate and correct edge direction')
FROM retired;
