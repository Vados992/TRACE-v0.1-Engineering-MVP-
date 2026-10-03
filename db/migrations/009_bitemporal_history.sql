-- System time is the actual PostgreSQL transaction COMMIT, never a supplied fact date.
DO $$ BEGIN
    IF current_setting('track_commit_timestamp') <> 'on' THEN
        RAISE EXCEPTION 'TRACE requires track_commit_timestamp=on; enable it and restart PostgreSQL before migration 009';
    END IF;
END $$;

CREATE TABLE temporal_commits (
    transaction_id xid8 PRIMARY KEY,
    committed_at timestamptz NOT NULL
);
CREATE TABLE temporal_pending (transaction_id xid8 PRIMARY KEY);
INSERT INTO temporal_pending VALUES(pg_current_xact_id());
CREATE TABLE temporal_control (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    activation_transaction xid8 NOT NULL
);
INSERT INTO temporal_control VALUES (true,pg_current_xact_id());

CREATE TABLE temporal_versions (
    version_id bigserial PRIMARY KEY,
    table_name text NOT NULL,
    record_id uuid NOT NULL,
    transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    operation text NOT NULL CHECK(operation IN ('INSERT','UPDATE','DELETE','BASELINE')),
    row_data jsonb NOT NULL
);
CREATE INDEX temporal_versions_record ON temporal_versions(table_name,record_id,version_id DESC);
CREATE INDEX temporal_versions_transaction ON temporal_versions(transaction_id);

CREATE FUNCTION trace_capture_version() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE data jsonb;
BEGIN
    IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
    data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    INSERT INTO public.temporal_versions(table_name,record_id,operation,row_data)
    VALUES(TG_TABLE_NAME,(data->>'id')::uuid,TG_OP,data);
    INSERT INTO public.temporal_pending VALUES(pg_current_xact_id()) ON CONFLICT DO NOTHING;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION trace_finalize_temporal_commits() RETURNS bigint LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE added bigint; pending xid8[];
BEGIN
    IF current_setting('track_commit_timestamp') <> 'on' THEN
        RAISE EXCEPTION 'PostgreSQL commit timestamp tracking is required';
    END IF;
    SELECT array_agg(transaction_id) INTO pending FROM public.temporal_pending
    WHERE transaction_id<>pg_current_xact_id();
    IF pending IS NULL THEN RETURN 0; END IF;
    INSERT INTO public.temporal_commits(transaction_id,committed_at)
    SELECT tx,pg_xact_commit_timestamp((tx::text::bigint % 4294967296)::text::xid)
    FROM (SELECT unnest(pending) AS tx) ids
    WHERE NOT EXISTS(SELECT 1 FROM public.temporal_commits c WHERE c.transaction_id=ids.tx)
      AND pg_xact_commit_timestamp((tx::text::bigint % 4294967296)::text::xid) IS NOT NULL
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS added=ROW_COUNT;
    DELETE FROM public.temporal_pending p USING public.temporal_commits c
    WHERE p.transaction_id=c.transaction_id AND p.transaction_id=ANY(pending);
    -- Visible committed versions must never disappear because PostgreSQL pruned its tracker.
    IF EXISTS (
        SELECT 1 FROM public.temporal_pending p WHERE p.transaction_id=ANY(pending)
    ) THEN RAISE EXCEPTION 'Unresolved temporal commit; historical reads unavailable; restore commit receipts'; END IF;
    RETURN added;
END $$;

CREATE FUNCTION trace_versions_at(p_table text,p_known_at timestamptz)
RETURNS TABLE(version_id bigint,record_id uuid,known_from timestamptz,operation text,row_data jsonb)
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
    SELECT DISTINCT ON(v.record_id) v.version_id,v.record_id,c.committed_at,v.operation,v.row_data
    FROM public.temporal_versions v JOIN public.temporal_commits c USING(transaction_id)
    WHERE v.table_name=p_table AND c.committed_at<=p_known_at
    ORDER BY v.record_id,c.committed_at DESC,v.version_id DESC
$$;

-- Version facts, evidence links, identities, review states and derived decisions together.
ALTER TABLE case_evidence ADD COLUMN id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE;
DO $$
DECLARE name text;
BEGIN
    FOREACH name IN ARRAY ARRAY[
      'sources','entities','entity_identifiers','entity_names','source_records','raw_artifacts',
      'documents','document_versions','claims','claim_evidence','relationships',
      'relationship_observations','ownership_interests','professional_roles','money_flows',
      'procurement_awards','source_entity_mappings','reconciliation_conflicts',
      'wealth_submissions','conflict_signals','cases','case_evidence','case_events','public_releases'
    ] LOOP
        EXECUTE format('INSERT INTO public.temporal_versions(table_name,record_id,operation,row_data)
                        SELECT %L,id,''BASELINE'',to_jsonb(t) FROM public.%I t',name,name);
        EXECUTE format('CREATE TRIGGER temporal_capture AFTER INSERT OR UPDATE OR DELETE ON public.%I
                        FOR EACH ROW EXECUTE FUNCTION public.trace_capture_version()',name);
        EXECUTE format('CREATE TRIGGER temporal_no_truncate BEFORE TRUNCATE ON public.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION public.reject_audit_mutation()',name);
        EXECUTE format('CREATE FUNCTION public.trace_%I_at(timestamptz) RETURNS SETOF public.%I
                        LANGUAGE sql STABLE SET search_path=pg_catalog,public AS
                        %L',name,name,format(
                        'SELECT (jsonb_populate_record(NULL::public.%I,v.row_data)).*
                         FROM public.trace_versions_at(%L,$1) v WHERE v.operation<>''DELETE''',name,name));
    END LOOP;
END $$;

CREATE TRIGGER temporal_history_immutable BEFORE UPDATE OR DELETE ON temporal_versions
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER temporal_history_no_truncate BEFORE TRUNCATE ON temporal_versions
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER temporal_receipts_immutable BEFORE UPDATE OR DELETE ON temporal_commits
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER temporal_receipts_no_truncate BEFORE TRUNCATE ON temporal_commits
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER temporal_control_immutable BEFORE UPDATE OR DELETE ON temporal_control
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER temporal_control_no_truncate BEFORE TRUNCATE ON temporal_control
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
ALTER TABLE investigations ADD COLUMN known_at timestamptz;
