-- XIDs are local to a PostgreSQL cluster. Logical restore must not reuse old commit receipts.
CREATE FUNCTION trace_cluster_identity() RETURNS text LANGUAGE sql STABLE
SECURITY DEFINER SET search_path=pg_catalog AS $$
    SELECT system_identifier::text FROM pg_control_system()
$$;
ALTER TABLE temporal_versions ADD COLUMN cluster_id text NOT NULL DEFAULT trace_cluster_identity();
ALTER TABLE temporal_commits ADD COLUMN cluster_id text NOT NULL DEFAULT trace_cluster_identity();
ALTER TABLE temporal_pending ADD COLUMN cluster_id text NOT NULL DEFAULT trace_cluster_identity();
ALTER TABLE temporal_control ADD COLUMN activation_cluster text NOT NULL DEFAULT trace_cluster_identity();
ALTER TABLE temporal_commits DROP CONSTRAINT temporal_commits_pkey;
ALTER TABLE temporal_commits ADD PRIMARY KEY(cluster_id,transaction_id);
ALTER TABLE temporal_pending DROP CONSTRAINT temporal_pending_pkey;
ALTER TABLE temporal_pending ADD PRIMARY KEY(cluster_id,transaction_id);

CREATE OR REPLACE FUNCTION trace_finalize_temporal_commits() RETURNS bigint LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE added bigint; pending xid8[]; cluster text := public.trace_cluster_identity();
BEGIN
    IF current_setting('track_commit_timestamp') <> 'on' THEN
        RAISE EXCEPTION 'PostgreSQL commit timestamp tracking is required';
    END IF;
    IF EXISTS(SELECT 1 FROM public.temporal_pending WHERE cluster_id<>cluster) THEN
        RAISE EXCEPTION 'Foreign pending commit receipts after restore; historical timestamps cannot be inferred';
    END IF;
    SELECT array_agg(transaction_id) INTO pending FROM public.temporal_pending
    WHERE cluster_id=cluster AND transaction_id<>pg_current_xact_id();
    IF pending IS NULL THEN RETURN 0; END IF;
    IF EXISTS(SELECT 1 FROM unnest(pending) tx
              WHERE pg_current_xact_id()::text::numeric-tx::text::numeric>=2147483648) THEN
        RAISE EXCEPTION 'Unfinalized commit exceeds safe XID horizon; historical reads unavailable';
    END IF;
    INSERT INTO public.temporal_commits(transaction_id,committed_at,cluster_id)
    SELECT tx,pg_xact_commit_timestamp((tx::text::bigint % 4294967296)::text::xid),cluster
    FROM (SELECT unnest(pending) AS tx) ids
    WHERE NOT EXISTS(SELECT 1 FROM public.temporal_commits c WHERE c.transaction_id=ids.tx AND c.cluster_id=cluster)
      AND pg_xact_commit_timestamp((tx::text::bigint % 4294967296)::text::xid) IS NOT NULL
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS added=ROW_COUNT;
    DELETE FROM public.temporal_pending p USING public.temporal_commits c
    WHERE p.cluster_id=cluster AND c.cluster_id=cluster
      AND p.transaction_id=c.transaction_id AND p.transaction_id=ANY(pending);
    IF EXISTS(SELECT 1 FROM public.temporal_pending p
              WHERE p.cluster_id=cluster AND p.transaction_id=ANY(pending)) THEN
        RAISE EXCEPTION 'Unresolved temporal commit; historical reads unavailable; restore commit receipts';
    END IF;
    RETURN added;
END $$;

CREATE OR REPLACE FUNCTION trace_versions_at(p_table text,p_known_at timestamptz)
RETURNS TABLE(version_id bigint,record_id uuid,known_from timestamptz,operation text,row_data jsonb)
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
    SELECT DISTINCT ON(v.record_id) v.version_id,v.record_id,c.committed_at,v.operation,v.row_data
    FROM public.temporal_versions v JOIN public.temporal_commits c
      ON c.transaction_id=v.transaction_id AND c.cluster_id=v.cluster_id
    WHERE v.table_name=p_table AND c.committed_at<=p_known_at
    ORDER BY v.record_id,c.committed_at DESC,v.version_id DESC
$$;
