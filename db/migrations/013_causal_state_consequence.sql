-- TRACE v0.7: Causal State & Consequence Layer.
-- The hard boundary between OBSERVED, DERIVED and SIMULATED material is enforced
-- in storage as well as in the application service.

CREATE TABLE causal_branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    branch_type TEXT NOT NULL CHECK(branch_type IN ('REALITY','COUNTERFACTUAL','SCENARIO')),
    parent_branch_id UUID REFERENCES causal_branches(id) ON DELETE RESTRICT,
    fork_event_id UUID,
    assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (branch_type='REALITY' AND parent_branch_id IS NULL)
        OR (branch_type<>'REALITY' AND parent_branch_id IS NOT NULL)
    )
);

INSERT INTO causal_branches(id,name,branch_type,parent_branch_id,assumptions,created_by)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Canonical observed reality',
    'REALITY',
    NULL,
    '{}'::jsonb,
    'system'
)
ON CONFLICT(id) DO NOTHING;

CREATE UNIQUE INDEX uq_single_reality_branch
    ON causal_branches(branch_type) WHERE branch_type='REALITY';

CREATE TABLE causal_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_key TEXT NOT NULL UNIQUE,
    event_hash TEXT NOT NULL UNIQUE,
    branch_id UUID NOT NULL REFERENCES causal_branches(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    epistemic_class TEXT NOT NULL CHECK(epistemic_class IN ('OBSERVED','DERIVED','SIMULATED')),
    subject_entity_id UUID REFERENCES entities(id) ON DELETE RESTRICT,
    object_entity_id UUID REFERENCES entities(id) ON DELETE RESTRICT,
    source_record_id UUID REFERENCES source_records(id) ON DELETE RESTRICT,
    occurred_at TIMESTAMPTZ NOT NULL,
    correlation_id UUID,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(6,5) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    model_ref TEXT,
    assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (epistemic_class='OBSERVED' AND source_record_id IS NOT NULL)
        OR (epistemic_class<>'OBSERVED' AND model_ref IS NOT NULL)
    )
);

ALTER TABLE causal_branches
    ADD CONSTRAINT fk_causal_branch_fork_event
    FOREIGN KEY(fork_event_id) REFERENCES causal_events(id) ON DELETE RESTRICT;

CREATE INDEX idx_causal_events_branch_time
    ON causal_events(branch_id,occurred_at,id);
CREATE INDEX idx_causal_events_subject_time
    ON causal_events(subject_entity_id,occurred_at) WHERE subject_entity_id IS NOT NULL;
CREATE INDEX idx_causal_events_correlation
    ON causal_events(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE TABLE causal_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cause_event_id UUID NOT NULL REFERENCES causal_events(id) ON DELETE RESTRICT,
    effect_event_id UUID NOT NULL REFERENCES causal_events(id) ON DELETE RESTRICT,
    edge_type TEXT NOT NULL CHECK(edge_type IN (
        'CAUSES','ENABLES','CONTRIBUTES','CORRELATES','COUNTERFACTUAL'
    )),
    epistemic_class TEXT NOT NULL CHECK(epistemic_class IN ('OBSERVED','DERIVED','SIMULATED')),
    evidence_source_record_id UUID REFERENCES source_records(id) ON DELETE RESTRICT,
    confidence NUMERIC(6,5) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    rationale TEXT NOT NULL,
    model_ref TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK(cause_event_id <> effect_event_id),
    CHECK (
        (epistemic_class='OBSERVED' AND evidence_source_record_id IS NOT NULL)
        OR (epistemic_class<>'OBSERVED' AND model_ref IS NOT NULL)
    ),
    UNIQUE(cause_event_id,effect_event_id,edge_type)
);

CREATE INDEX idx_causal_edges_cause ON causal_edges(cause_event_id);
CREATE INDEX idx_causal_edges_effect ON causal_edges(effect_event_id);

CREATE TABLE entity_state_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    branch_id UUID NOT NULL REFERENCES causal_branches(id) ON DELETE RESTRICT,
    snapshot_kind TEXT NOT NULL CHECK(snapshot_kind IN ('BASE','TRANSITION')),
    as_of TIMESTAMPTZ NOT NULL,
    epistemic_class TEXT NOT NULL CHECK(epistemic_class IN ('OBSERVED','DERIVED','SIMULATED')),
    state JSONB NOT NULL,
    state_hash TEXT NOT NULL,
    source_event_id UUID REFERENCES causal_events(id) ON DELETE RESTRICT,
    confidence NUMERIC(6,5) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    model_ref TEXT,
    assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(entity_id,branch_id,as_of,state_hash),
    CHECK (
        (epistemic_class='OBSERVED' AND source_event_id IS NOT NULL)
        OR (epistemic_class<>'OBSERVED' AND model_ref IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_state_base_per_entity_branch
    ON entity_state_snapshots(entity_id,branch_id) WHERE snapshot_kind='BASE';
CREATE INDEX idx_state_snapshot_entity_branch_time
    ON entity_state_snapshots(entity_id,branch_id,as_of,id);

CREATE TABLE state_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    branch_id UUID NOT NULL REFERENCES causal_branches(id) ON DELETE RESTRICT,
    event_id UUID NOT NULL REFERENCES causal_events(id) ON DELETE RESTRICT,
    from_snapshot_id UUID NOT NULL REFERENCES entity_state_snapshots(id) ON DELETE RESTRICT,
    to_snapshot_id UUID NOT NULL REFERENCES entity_state_snapshots(id) ON DELETE RESTRICT,
    transition_class TEXT NOT NULL CHECK(transition_class IN (
        'OBSERVED_APPLY','DERIVED_APPLY','SIMULATED_APPLY'
    )),
    patch JSONB NOT NULL,
    changed_keys JSONB NOT NULL,
    before_hash TEXT NOT NULL,
    after_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(entity_id,branch_id,event_id),
    CHECK(from_snapshot_id <> to_snapshot_id)
);

CREATE INDEX idx_state_transition_replay
    ON state_transitions(entity_id,branch_id,created_at,id);

CREATE FUNCTION trace_validate_causal_event_branch()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE kind TEXT;
BEGIN
    SELECT branch_type INTO kind FROM causal_branches WHERE id=NEW.branch_id;
    IF NEW.epistemic_class='OBSERVED' AND kind <> 'REALITY' THEN
        RAISE EXCEPTION 'OBSERVED events may exist only on the REALITY branch';
    END IF;
    IF NEW.epistemic_class='SIMULATED' AND kind = 'REALITY' THEN
        RAISE EXCEPTION 'SIMULATED events may not be written to the REALITY branch';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER causal_event_branch_guard
    BEFORE INSERT ON causal_events
    FOR EACH ROW EXECUTE FUNCTION trace_validate_causal_event_branch();

CREATE FUNCTION trace_validate_causal_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE cause_branch UUID;
DECLARE effect_branch UUID;
DECLARE cause_time TIMESTAMPTZ;
DECLARE effect_time TIMESTAMPTZ;
BEGIN
    SELECT branch_id,occurred_at INTO cause_branch,cause_time
      FROM causal_events WHERE id=NEW.cause_event_id;
    SELECT branch_id,occurred_at INTO effect_branch,effect_time
      FROM causal_events WHERE id=NEW.effect_event_id;
    IF cause_branch <> effect_branch THEN
        RAISE EXCEPTION 'causal edges cannot cross branches';
    END IF;
    IF NEW.edge_type <> 'CORRELATES' AND cause_time > effect_time THEN
        RAISE EXCEPTION 'a causal predecessor cannot occur after its effect';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER causal_edge_guard
    BEFORE INSERT ON causal_edges
    FOR EACH ROW EXECUTE FUNCTION trace_validate_causal_edge();

-- All v0.7 analytical receipts are append-only. Corrections are new events,
-- edges, snapshots or branches, never destructive rewrites.
CREATE TRIGGER causal_branches_immutable
    BEFORE UPDATE OR DELETE ON causal_branches
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER causal_branches_no_truncate
    BEFORE TRUNCATE ON causal_branches
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

CREATE TRIGGER causal_events_immutable
    BEFORE UPDATE OR DELETE ON causal_events
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER causal_events_no_truncate
    BEFORE TRUNCATE ON causal_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

CREATE TRIGGER causal_edges_immutable
    BEFORE UPDATE OR DELETE ON causal_edges
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER causal_edges_no_truncate
    BEFORE TRUNCATE ON causal_edges
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

CREATE TRIGGER entity_state_snapshots_immutable
    BEFORE UPDATE OR DELETE ON entity_state_snapshots
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER entity_state_snapshots_no_truncate
    BEFORE TRUNCATE ON entity_state_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

CREATE TRIGGER state_transitions_immutable
    BEFORE UPDATE OR DELETE ON state_transitions
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER state_transitions_no_truncate
    BEFORE TRUNCATE ON state_transitions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
