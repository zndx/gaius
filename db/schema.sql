\restrict CbjSDoC4JeqeKqMard6L7gvnisVL4Qv9YeePD5XWhs8gSnG5dOuZ58BmT97uf79

-- Dumped from database version 16.10
-- Dumped by pg_dump version 16.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ag_catalog; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_catalog;


--
-- Name: pg_cron; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION pg_cron; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_cron IS 'Job scheduler for PostgreSQL';


--
-- Name: gaius_hx; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA gaius_hx;


--
-- Name: meta; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA meta;


--
-- Name: SCHEMA meta; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA meta IS 'MetaAgent analytics tables for Metabase dashboards';


--
-- Name: age; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS age WITH SCHEMA ag_catalog;


--
-- Name: EXTENSION age; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION age IS 'AGE database extension';


--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: activity_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.activity_type AS ENUM (
    'query',
    'domain_change',
    'swarm_run',
    'tda_compute',
    'projection',
    'kb_create',
    'kb_update',
    'command',
    'startup',
    'shutdown',
    'research_complete',
    'reflection_complete',
    'evolution_cycle'
);


--
-- Name: agenda_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agenda_status AS ENUM (
    'scheduling',
    'on_track',
    'delayed',
    'blocked',
    'fulfilled',
    'failed',
    'degraded'
);


--
-- Name: agenda_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agenda_type AS ENUM (
    'ambient_cycle',
    'swarm',
    'evolution',
    'inference',
    'flow'
);


--
-- Name: aiops_severity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.aiops_severity AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);


--
-- Name: aiops_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.aiops_status AS ENUM (
    'detected',
    'auto_remediated',
    'pending_approval',
    'approved',
    'rejected',
    'failed',
    'resolved'
);


--
-- Name: control_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.control_mode AS ENUM (
    'positive',
    'failure_recovery',
    'restart_recovery'
);


--
-- Name: job_priority; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_priority AS ENUM (
    'critical',
    'high',
    'normal',
    'low'
);


--
-- Name: job_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_status AS ENUM (
    'pending',
    'scheduled',
    'running',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: source_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_type AS ENUM (
    'arxiv',
    'biorxiv',
    'rss',
    'api',
    'scraper',
    'philpapers',
    'docs',
    'brave',
    'philevents'
);


--
-- Name: check_reset_weekly_budget(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.check_reset_weekly_budget() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.week_start != date_trunc('week', CURRENT_DATE)::DATE THEN
        NEW.weekly_used := 0;
        NEW.grok_calls := 0;
        NEW.cerebras_calls := 0;
        NEW.week_start := date_trunc('week', CURRENT_DATE)::DATE;
        NEW.last_reset := NOW();
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: cleanup_research_progress(integer); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.cleanup_research_progress(retention_hours integer DEFAULT 24) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM meta.research_progress
    WHERE created_at < NOW() - (retention_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;


--
-- Name: FUNCTION cleanup_research_progress(retention_hours integer); Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON FUNCTION meta.cleanup_research_progress(retention_hours integer) IS 'Prune research progress events older than retention period';


--
-- Name: complete_fmp_sync_run(integer, character varying, integer, integer, integer, real, real, integer, text); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.complete_fmp_sync_run(p_run_id integer, p_status character varying, p_symbols_processed integer DEFAULT 0, p_filings_fetched integer DEFAULT 0, p_filings_new integer DEFAULT 0, p_analysis_cost real DEFAULT 0.0, p_synthesis_cost real DEFAULT 0.0, p_kb_artifacts integer DEFAULT 0, p_error_message text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE meta.fmp_sync_runs SET
        status = p_status,
        symbols_processed = p_symbols_processed,
        filings_fetched = p_filings_fetched,
        filings_new = p_filings_new,
        analysis_cost_usd = p_analysis_cost,
        synthesis_cost_usd = p_synthesis_cost,
        kb_artifacts_created = p_kb_artifacts,
        completed_at = NOW(),
        error_message = p_error_message
    WHERE id = p_run_id;
END;
$$;


--
-- Name: cron_job_status(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.cron_job_status() RETURNS TABLE(jobid bigint, jobname text, schedule text, active boolean, last_run timestamp with time zone, last_status text)
    LANGUAGE sql
    AS $$
    SELECT
        j.jobid,
        j.jobname,
        j.schedule,
        j.active,
        r.start_time as last_run,
        COALESCE(r.status, 'never_run') as last_status
    FROM cron.job j
    LEFT JOIN LATERAL (
        SELECT start_time, status
        FROM cron.job_run_details
        WHERE jobid = j.jobid
        ORDER BY start_time DESC
        LIMIT 1
    ) r ON TRUE
    WHERE j.jobname LIKE 'meta-%'
    ORDER BY j.jobname;
$$;


--
-- Name: FUNCTION cron_job_status(); Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON FUNCTION meta.cron_job_status() IS 'Check status of meta observability cron jobs';


--
-- Name: notify_flow_event(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.notify_flow_event() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Only notify on status changes to completed/failed
    IF NEW.status IN ('completed', 'failed') AND
       (OLD.status IS NULL OR OLD.status != NEW.status) THEN

        -- Send notification to channel
        PERFORM pg_notify(
            'flow_events',
            json_build_object(
                'run_id', NEW.run_id::text,
                'flow_type', NEW.flow_type,
                'status', NEW.status,
                'started_at', COALESCE(NEW.started_at::text, ''),
                'completed_at', COALESCE(NEW.completed_at::text, ''),
                'duration_ms', COALESCE(NEW.duration_ms, 0)
            )::text
        );

        -- Insert audit record
        INSERT INTO meta.flow_events (
            run_id, flow_type, status, started_at, completed_at, duration_ms
        ) VALUES (
            NEW.run_id, NEW.flow_type, NEW.status,
            NEW.started_at, NEW.completed_at, NEW.duration_ms
        );
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: FUNCTION notify_flow_event(); Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON FUNCTION meta.notify_flow_event() IS 'Trigger function for flow completion LISTEN/NOTIFY';


--
-- Name: notify_research_progress(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.notify_research_progress() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Push notification for every new event
    PERFORM pg_notify(
        'research_progress',
        json_build_object(
            'event_id', NEW.event_id,
            'session_id', NEW.session_id,
            'event_type', NEW.event_type,
            'event_name', NEW.event_name,
            'pass_number', NEW.pass_number,
            'progress', NEW.progress,
            'message', NEW.message,
            'metadata', NEW.metadata
        )::text
    );
    RETURN NEW;
END;
$$;


--
-- Name: FUNCTION notify_research_progress(); Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON FUNCTION meta.notify_research_progress() IS 'Push research progress events via pg_notify on insert';


--
-- Name: prospect_needs_update(character varying); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.prospect_needs_update(p_symbol character varying) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_last_analysis TIMESTAMPTZ;
    v_latest_filing DATE;
BEGIN
    -- Get last analysis time
    SELECT last_analysis_at INTO v_last_analysis
    FROM meta.prospect_strategies
    WHERE symbol = p_symbol
    LIMIT 1;

    -- Get latest filing date
    SELECT MAX(filing_date) INTO v_latest_filing
    FROM meta.sec_filings_cache
    WHERE symbol = p_symbol;

    -- No filings = no update needed
    IF v_latest_filing IS NULL THEN
        RETURN FALSE;
    END IF;

    -- No analysis yet = update needed
    IF v_last_analysis IS NULL THEN
        RETURN TRUE;
    END IF;

    -- New filings since last analysis = update needed
    RETURN v_latest_filing > v_last_analysis::DATE;
END;
$$;


--
-- Name: prospects_daily_check(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.prospects_daily_check() RETURNS TABLE(symbol character varying, needs_update boolean, pending_filings integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.symbol,
        meta.prospect_needs_update(c.symbol) AS needs_update,
        c.pending_filings
    FROM meta.prospect_candidates c
    WHERE c.priority <= 2;  -- Only check high/medium priority
END;
$$;


--
-- Name: start_fmp_sync_run(character varying, character varying, character varying); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.start_fmp_sync_run(p_profile character varying, p_domain character varying, p_run_type character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_run_id INTEGER;
BEGIN
    INSERT INTO meta.fmp_sync_runs (profile, domain, run_type, status)
    VALUES (p_profile, p_domain, p_run_type, 'running')
    RETURNING id INTO v_run_id;

    RETURN v_run_id;
END;
$$;


--
-- Name: sync_prospect_watchlist(character varying[], character varying); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.sync_prospect_watchlist(p_symbols character varying[], p_profile character varying DEFAULT 'zndx'::character varying) RETURNS TABLE(activated integer, archived integer, unchanged integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_activated INTEGER := 0;
    v_archived INTEGER := 0;
    v_unchanged INTEGER := 0;
BEGIN
    -- Activate symbols that are in config but inactive
    UPDATE meta.prospect_candidates
    SET active = TRUE, archived_at = NULL, updated_at = NOW()
    WHERE symbol = ANY(p_symbols) AND active = FALSE;
    GET DIAGNOSTICS v_activated = ROW_COUNT;

    -- Archive symbols that are active but not in config
    UPDATE meta.prospect_candidates
    SET active = FALSE, archived_at = NOW(), updated_at = NOW()
    WHERE symbol NOT IN (SELECT unnest(p_symbols)) AND active = TRUE;
    GET DIAGNOSTICS v_archived = ROW_COUNT;

    -- Count unchanged
    SELECT COUNT(*) INTO v_unchanged
    FROM meta.prospect_candidates
    WHERE symbol = ANY(p_symbols) AND active = TRUE;
    v_unchanged := v_unchanged - v_activated;

    RETURN QUERY SELECT v_activated, v_archived, v_unchanged;
END;
$$;


--
-- Name: FUNCTION sync_prospect_watchlist(p_symbols character varying[], p_profile character varying); Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON FUNCTION meta.sync_prospect_watchlist(p_symbols character varying[], p_profile character varying) IS 'Sync watchlist config to DB: activate configured symbols, archive removed ones';


--
-- Name: update_flow_runs_timestamp(); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.update_flow_runs_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_pending_filings(character varying); Type: FUNCTION; Schema: meta; Owner: -
--

CREATE FUNCTION meta.update_pending_filings(p_symbol character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM meta.sec_filings_cache
    WHERE symbol = p_symbol AND analyzed_at IS NULL;

    UPDATE meta.prospect_candidates
    SET pending_filings = v_count, updated_at = NOW()
    WHERE symbol = p_symbol;

    RETURN v_count;
END;
$$;


--
-- Name: age_available(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.age_available() RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM 1 FROM pg_extension WHERE extname = 'age';
    RETURN FOUND;
END;
$$;


--
-- Name: apply_cron_jobs(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.apply_cron_jobs() RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_job RECORD;
    v_count INTEGER := 0;
BEGIN
    -- Check if pg_cron is available
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RETURN 'pg_cron extension not installed. Jobs stored in scheduled_jobs_config table.';
    END IF;

    FOR v_job IN SELECT * FROM scheduled_jobs_config WHERE enabled LOOP
        EXECUTE format(
            'SELECT cron.schedule(%L, %L, %L)',
            v_job.job_name,
            v_job.schedule,
            v_job.function_call
        );
        v_count := v_count + 1;
    END LOOP;

    RETURN format('Applied %s pg_cron jobs', v_count);
END;
$$;


--
-- Name: archive_stale_content(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.archive_stale_content() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_archived INTEGER := 0;
BEGIN
    -- For now, just mark as processed if old and not written to KB
    UPDATE content_items
    SET metadata = metadata || jsonb_build_object('archived', true, 'archived_at', NOW())
    WHERE fetched_at < NOW() - INTERVAL '90 days'
      AND kb_path IS NULL
      AND NOT (metadata ? 'archived');

    GET DIAGNOSTICS v_archived = ROW_COUNT;
    RETURN v_archived;
END;
$$;


--
-- Name: archive_stale_thoughts(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.archive_stale_thoughts(days_old integer DEFAULT 7) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    UPDATE cognition_thoughts
    SET status = 'archived',
        updated_at = NOW()
    WHERE status = 'active'
      AND created_at < NOW() - (days_old || ' days')::INTERVAL;

    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN archived_count;
END;
$$;


--
-- Name: check_archive_changed(integer, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_archive_changed(p_source_id integer, p_archive_url text, p_new_hash text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_old_hash TEXT;
BEGIN
    SELECT content_hash INTO v_old_hash
    FROM doc_archives
    WHERE source_id = p_source_id AND archive_url = p_archive_url;

    IF v_old_hash IS NULL THEN
        RETURN TRUE;  -- New archive, needs sync
    END IF;

    RETURN v_old_hash != p_new_hash;  -- Changed if hash differs
END;
$$;


--
-- Name: check_content_diversity(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_content_diversity() RETURNS TABLE(should_trigger boolean, reason text, new_content_items integer, new_thoughts integer, domains_active integer, external_ingested integer, days_since_last integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    last_evolution TIMESTAMPTZ;
    v_new_content INTEGER;
    v_new_thoughts INTEGER;
    v_domains INTEGER;
    v_external INTEGER;
    v_days INTEGER;
    -- Configurable thresholds (extended for long-term operation)
    min_content_items INTEGER := 100;  -- New content items with kb_path
    min_thoughts INTEGER := 50;        -- New cognition thoughts
    min_domains INTEGER := 3;          -- Unique domains active
    min_external INTEGER := 50;        -- External content ingested
    min_days INTEGER := 7;             -- Minimum days between cycles
    max_days INTEGER := 30;            -- Force trigger after this
BEGIN
    -- Find last successful evolution cycle
    SELECT MAX(completed_at) INTO last_evolution
    FROM evolution_cycles
    WHERE success = true;

    -- Default to 30 days ago if no evolution yet
    last_evolution := COALESCE(last_evolution, NOW() - INTERVAL '30 days');

    -- Count new content items written to KB
    SELECT COUNT(*) INTO v_new_content
    FROM content_items
    WHERE fetched_at > last_evolution
      AND kb_path IS NOT NULL;

    -- Count new cognition thoughts
    SELECT COUNT(*) INTO v_new_thoughts
    FROM cognition_thoughts
    WHERE created_at > last_evolution;

    -- Count active domains from activity events
    SELECT COUNT(DISTINCT domain) INTO v_domains
    FROM activity_events
    WHERE created_at > last_evolution
      AND domain IS NOT NULL;

    -- Count external content ingested (processed_at indicates ingestion)
    SELECT COUNT(*) INTO v_external
    FROM content_items
    WHERE processed_at > last_evolution;

    -- Days since last evolution
    v_days := EXTRACT(DAY FROM NOW() - last_evolution)::INTEGER;

    -- Determine if we should trigger
    IF v_days >= max_days THEN
        RETURN QUERY SELECT true, 'Max days exceeded - forcing evolution'::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    ELSIF v_days >= min_days AND
          v_new_content >= min_content_items AND
          v_domains >= min_domains AND
          v_external >= min_external THEN
        RETURN QUERY SELECT true, 'Diversity thresholds met'::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    ELSE
        RETURN QUERY SELECT false,
            format('Waiting: content=%s/%s, thoughts=%s/%s, domains=%s/%s, external=%s/%s, days=%s/%s',
                   v_new_content, min_content_items,
                   v_new_thoughts, min_thoughts,
                   v_domains, min_domains,
                   v_external, min_external,
                   v_days, min_days)::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    END IF;
END;
$$;


--
-- Name: FUNCTION check_content_diversity(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.check_content_diversity() IS 'Checks if enough new content has accumulated to trigger evolution.
Returns should_trigger=true if diversity thresholds are met or max_days exceeded.
Called twice daily by pg_cron as the PRIMARY driver of evolution.';


--
-- Name: cleanup_old_fetch_jobs(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cleanup_old_fetch_jobs() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_deleted INTEGER := 0;
BEGIN
    WITH ranked_jobs AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY started_at DESC) as rn
        FROM fetch_jobs
    )
    DELETE FROM fetch_jobs
    WHERE id IN (SELECT id FROM ranked_jobs WHERE rn > 100);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;


--
-- Name: cleanup_theta_consolidation_history(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cleanup_theta_consolidation_history() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_deleted INTEGER := 0;
BEGIN
    WITH ranked_runs AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY started_at DESC) as rn
        FROM theta_consolidation_runs
        WHERE status IN ('completed', 'failed')
    )
    DELETE FROM theta_consolidation_runs
    WHERE id IN (SELECT id FROM ranked_runs WHERE rn > 100);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;


--
-- Name: complete_archive_rotation(integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.complete_archive_rotation(p_rotation_id integer, p_files_moved integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE archive_rotations SET
        status = 'completed',
        files_moved = p_files_moved,
        completed_at = NOW()
    WHERE id = p_rotation_id;
END;
$$;


--
-- Name: complete_archive_sync(integer, text, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.complete_archive_sync(p_archive_id integer, p_content_hash text, p_pages_extracted integer, p_kb_path_prefix text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE doc_archives SET
        status = 'completed',
        content_hash = p_content_hash,
        pages_extracted = p_pages_extracted,
        kb_path_prefix = p_kb_path_prefix,
        processed_at = NOW(),
        error_message = NULL
    WHERE id = p_archive_id;
END;
$$;


--
-- Name: complete_task(integer, jsonb, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.complete_task(p_task_id integer, p_result jsonb DEFAULT NULL::jsonb, p_error text DEFAULT NULL::text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE scheduled_tasks
    SET completed_at = NOW(),
        result = p_result,
        error = p_error
    WHERE id = p_task_id;

    RETURN FOUND;
END;
$$;


--
-- Name: complete_theta_consolidation(integer, real, real, integer, integer, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.complete_theta_consolidation(p_job_id integer, p_urgency real DEFAULT NULL::real, p_drift real DEFAULT NULL::real, p_candidates_evaluated integer DEFAULT 0, p_candidates_selected integer DEFAULT 0, p_documents_augmented integer DEFAULT 0, p_error text DEFAULT NULL::text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE theta_consolidation_runs
    SET status = CASE WHEN p_error IS NULL THEN 'completed' ELSE 'failed' END,
        completed_at = NOW(),
        urgency = p_urgency,
        drift = p_drift,
        candidates_evaluated = p_candidates_evaluated,
        candidates_selected = p_candidates_selected,
        documents_augmented = p_documents_augmented,
        error = p_error,
        metadata = metadata || jsonb_build_object('duration_ms', EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)
    WHERE id = p_job_id AND status = 'running';

    RETURN FOUND;
END;
$$;


--
-- Name: count_exact_duplicates(text, text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.count_exact_duplicates(p_content_hash text, p_profile text DEFAULT 'default'::text, p_days integer DEFAULT 7) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
    SELECT COUNT(*)::INTEGER
    FROM cognition_thoughts
    WHERE content_hash = p_content_hash
      AND profile_name = p_profile
      AND created_at > NOW() - (p_days || ' days')::INTERVAL;
$$;


--
-- Name: FUNCTION count_exact_duplicates(p_content_hash text, p_profile text, p_days integer); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.count_exact_duplicates(p_content_hash text, p_profile text, p_days integer) IS 'Count exact hash matches (semantic similarity uses Qdrant)';


--
-- Name: count_similar_thoughts(text, text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.count_similar_thoughts(p_content_hash text, p_profile text DEFAULT 'default'::text, p_days integer DEFAULT 7) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
    SELECT COUNT(*)::INTEGER
    FROM cognition_thoughts
    WHERE content_hash = p_content_hash
      AND profile_name = p_profile
      AND created_at > NOW() - (p_days || ' days')::INTERVAL;
$$;


--
-- Name: FUNCTION count_similar_thoughts(p_content_hash text, p_profile text, p_days integer); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.count_similar_thoughts(p_content_hash text, p_profile text, p_days integer) IS 'Count recent thoughts with same content hash';


--
-- Name: detect_cognition_delta(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.detect_cognition_delta(p_profile text DEFAULT 'default'::text) RETURNS TABLE(task_type text, reason text)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_last_thought TIMESTAMPTZ;
    v_anomaly_count INTEGER;
BEGIN
    -- Check when cognition last ran
    SELECT MAX(created_at) INTO v_last_thought
    FROM cognition_thoughts
    WHERE profile_name = p_profile;

    -- If no thoughts in 6 hours, trigger cognition
    IF v_last_thought IS NULL OR v_last_thought < NOW() - INTERVAL '6 hours' THEN
        -- Only if not already scheduled
        IF NOT EXISTS (
            SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'cognition_cycle'
              AND picked_up_at IS NULL
        ) THEN
            INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
            VALUES ('cognition_cycle', '{"trigger": "stale_cognition"}', 'delta_detection', NOW());

            RETURN QUERY SELECT 'cognition_cycle'::TEXT, 'No thoughts in 6+ hours'::TEXT;
        END IF;
    END IF;

    -- Check for recent anomalies that need audit
    SELECT COUNT(*) INTO v_anomaly_count
    FROM engine_observations
    WHERE cardinality(anomalies) > 0
      AND observed_at > NOW() - INTERVAL '1 hour'
      AND related_thought_id IS NULL;  -- Not yet processed

    IF v_anomaly_count > 0 THEN
        IF NOT EXISTS (
            SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'engine_audit'
              AND picked_up_at IS NULL
        ) THEN
            INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for, priority)
            VALUES ('engine_audit',
                    jsonb_build_object('anomaly_count', v_anomaly_count),
                    'delta_detection',
                    NOW(),
                    'high');

            RETURN QUERY SELECT 'engine_audit'::TEXT,
                format('%s unprocessed anomalies', v_anomaly_count)::TEXT;
        END IF;
    END IF;

    RETURN;
END;
$$;


--
-- Name: FUNCTION detect_cognition_delta(p_profile text); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.detect_cognition_delta(p_profile text) IS 'Schedule tasks to fill gaps between desired and actual state';


--
-- Name: fail_archive_sync(integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fail_archive_sync(p_archive_id integer, p_error_message text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE doc_archives SET
        status = 'failed',
        error_message = p_error_message,
        processed_at = NOW()
    WHERE id = p_archive_id;
END;
$$;


--
-- Name: get_active_domain(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_active_domain(p_profile_name text) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_domain_name TEXT;
BEGIN
    SELECT pd.name INTO v_domain_name
    FROM profile_domains pd
    JOIN profiles p ON pd.profile_id = p.id
    WHERE p.name = p_profile_name AND pd.is_active = TRUE;

    RETURN v_domain_name;
END;
$$;


--
-- Name: get_archives_needing_sync(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_archives_needing_sync() RETURNS TABLE(archive_id integer, source_name text, archive_url text, status text, retry_count integer, last_error text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        da.id,
        fs.name,
        da.archive_url,
        da.status,
        da.retry_count,
        da.error_message
    FROM doc_archives da
    JOIN feed_sources fs ON da.source_id = fs.id
    WHERE da.status IN ('discovered', 'failed')
      AND (da.retry_count < 3 OR da.status = 'discovered')
    ORDER BY da.discovered_at;
END;
$$;


--
-- Name: get_chain_head(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_chain_head(p_chain_id uuid) RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
    SELECT id FROM cognition_thoughts
    WHERE thought_chain_id = p_chain_id
    ORDER BY generation DESC, created_at DESC
    LIMIT 1;
$$;


--
-- Name: get_current_quarter(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_current_quarter() RETURNS text
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN EXTRACT(YEAR FROM NOW())::TEXT || 'Q' ||
           CEIL(EXTRACT(MONTH FROM NOW()) / 3.0)::TEXT;
END;
$$;


--
-- Name: get_default_profile(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_default_profile() RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_profile_name TEXT;
BEGIN
    -- Get the profile marked as default
    SELECT name INTO v_profile_name
    FROM profiles
    WHERE is_default = TRUE AND active = TRUE;

    -- Fall back to first active profile if no default set
    IF v_profile_name IS NULL THEN
        SELECT name INTO v_profile_name
        FROM profiles
        WHERE active = TRUE
        ORDER BY name
        LIMIT 1;
    END IF;

    RETURN v_profile_name;
END;
$$;


--
-- Name: get_default_profile_and_domain(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_default_profile_and_domain() RETURNS TABLE(profile_name text, domain_name text)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_profile TEXT;
    v_domain TEXT;
BEGIN
    -- Get default profile
    v_profile := get_default_profile();

    IF v_profile IS NOT NULL THEN
        -- Get active domain for that profile
        v_domain := get_active_domain(v_profile);
    END IF;

    RETURN QUERY SELECT v_profile, v_domain;
END;
$$;


--
-- Name: get_doc_sync_summary(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_doc_sync_summary() RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'total_archives', COUNT(*),
        'by_status', jsonb_object_agg(status, cnt),
        'total_pages', SUM(pages_extracted),
        'last_sync', MAX(processed_at)
    ) INTO v_result
    FROM (
        SELECT status, COUNT(*) as cnt, SUM(pages_extracted) as pages_extracted,
               MAX(processed_at) as processed_at
        FROM doc_archives
        GROUP BY status
    ) stats;

    RETURN v_result;
END;
$$;


--
-- Name: get_kb_lineage(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_kb_lineage(p_kb_path text) RETURNS TABLE(kb_path text, source_title text, source_url text, source_type text, iceberg_id text, quality_score double precision, summarized_at timestamp with time zone, lineage_run_id uuid)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        sl.kb_path,
        ci.title,
        ci.url,
        s.source_type,
        sl.iceberg_record_id,
        sl.quality_score,
        ci.summarized_at,
        sl.lineage_run_id
    FROM summary_lineage sl
    JOIN content_items ci ON sl.content_item_id = ci.id
    JOIN sources s ON ci.source_id = s.id
    WHERE sl.kb_path = p_kb_path;
END;
$$;


--
-- Name: get_pending_theta_consolidations(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_pending_theta_consolidations() RETURNS TABLE(job_id integer, slice_id text, scheduled_at timestamp with time zone)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT id, t.slice_id, t.started_at
    FROM theta_consolidation_runs t
    WHERE status = 'scheduled'
    ORDER BY started_at ASC
    LIMIT 10;  -- Process up to 10 at a time
END;
$$;


--
-- Name: get_profile_context(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_profile_context(p_profile_name text, p_domain_name text DEFAULT NULL::text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_result JSONB;
    v_profile_text TEXT;
    v_domain_text TEXT;
    v_profile_prefixes TEXT[];
    v_domain_prefixes TEXT[];
BEGIN
    -- Get profile info
    SELECT profile_text, kb_path_prefixes
    INTO v_profile_text, v_profile_prefixes
    FROM profiles
    WHERE name = p_profile_name;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'Profile not found');
    END IF;

    v_result := jsonb_build_object(
        'profile', p_profile_name,
        'profile_text', COALESCE(v_profile_text, ''),
        'profile_prefixes', COALESCE(v_profile_prefixes, '{}')
    );

    -- Get domain info if specified
    IF p_domain_name IS NOT NULL AND p_domain_name != '' AND p_domain_name != 'open' THEN
        SELECT domain_text, kb_path_prefixes
        INTO v_domain_text, v_domain_prefixes
        FROM profile_domains pd
        JOIN profiles p ON pd.profile_id = p.id
        WHERE p.name = p_profile_name AND pd.name = p_domain_name;

        IF FOUND THEN
            v_result := v_result || jsonb_build_object(
                'domain', p_domain_name,
                'domain_text', COALESCE(v_domain_text, ''),
                'domain_prefixes', COALESCE(v_domain_prefixes, '{}')
            );
        END IF;
    END IF;

    RETURN v_result;
END;
$$;


--
-- Name: get_scheduled_jobs_status(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_scheduled_jobs_status() RETURNS TABLE(jobid bigint, jobname text, schedule text, command text, nodename text, active boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    -- Check if cron schema exists (pg_cron installed)
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        RETURN QUERY
        SELECT
            j.jobid,
            j.jobname::text,
            j.schedule::text,
            j.command::text,
            j.nodename::text,
            j.active
        FROM cron.job j
        WHERE j.database = current_database()
        ORDER BY j.jobname;
    ELSE
        -- Return empty if pg_cron not installed
        RETURN;
    END IF;
END;
$$;


--
-- Name: FUNCTION get_scheduled_jobs_status(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.get_scheduled_jobs_status() IS 'Returns all pg_cron jobs for this database. Use: SELECT * FROM get_scheduled_jobs_status();
Uses SECURITY DEFINER to allow access regardless of cron schema permissions.';


--
-- Name: get_thought_chain(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_thought_chain(p_chain_id uuid) RETURNS uuid[]
    LANGUAGE sql STABLE
    AS $$
    SELECT array_agg(id ORDER BY generation, created_at)
    FROM cognition_thoughts
    WHERE thought_chain_id = p_chain_id;
$$;


--
-- Name: increment_ambient_cycle(integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.increment_ambient_cycle(p_tasks_in_cycle integer DEFAULT 0, p_successful_in_cycle integer DEFAULT 0) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE ambient_daemon_state
    SET
        cycles_completed = cycles_completed + 1,
        total_tasks = total_tasks + p_tasks_in_cycle,
        successful_tasks = successful_tasks + p_successful_in_cycle,
        updated_at = NOW()
    WHERE id = 1 AND running = TRUE;
END;
$$;


--
-- Name: is_duplicate_thought(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_duplicate_thought(p_content_hash text, p_profile text DEFAULT 'default'::text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM cognition_thoughts
        WHERE content_hash = p_content_hash
          AND profile_name = p_profile
          AND status = 'active'
    );
$$;


--
-- Name: FUNCTION is_duplicate_thought(p_content_hash text, p_profile text); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.is_duplicate_thought(p_content_hash text, p_profile text) IS 'Check if exact content hash exists (semantic similarity uses Qdrant)';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: scheduled_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_tasks (
    id integer NOT NULL,
    task_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    priority text DEFAULT 'normal'::text,
    scheduled_for timestamp with time zone DEFAULT now() NOT NULL,
    source text DEFAULT 'manual'::text,
    picked_up_at timestamp with time zone,
    completed_at timestamp with time zone,
    result jsonb,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE scheduled_tasks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scheduled_tasks IS 'Generic task dispatch for pg_cron and daemon execution';


--
-- Name: pick_up_task(text[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.pick_up_task(p_task_types text[] DEFAULT NULL::text[]) RETURNS public.scheduled_tasks
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_task scheduled_tasks;
BEGIN
    UPDATE scheduled_tasks
    SET picked_up_at = NOW()
    WHERE id = (
        SELECT id FROM scheduled_tasks
        WHERE picked_up_at IS NULL
          AND scheduled_for <= NOW()
          AND (p_task_types IS NULL OR task_type = ANY(p_task_types))
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            scheduled_for
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING * INTO v_task;

    RETURN v_task;
END;
$$;


--
-- Name: FUNCTION pick_up_task(p_task_types text[]); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.pick_up_task(p_task_types text[]) IS 'Atomically claim a pending task for execution';


--
-- Name: record_lineage_event(uuid, text, text, text, jsonb, jsonb, jsonb, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.record_lineage_event(p_run_id uuid, p_job_namespace text, p_job_name text, p_run_state text, p_inputs jsonb DEFAULT '[]'::jsonb, p_outputs jsonb DEFAULT '[]'::jsonb, p_facets jsonb DEFAULT '{}'::jsonb, p_parent_run_id uuid DEFAULT NULL::uuid) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_event_id INTEGER;
BEGIN
    INSERT INTO lineage_events (
        run_id, job_namespace, job_name, run_state,
        inputs, outputs, facets, parent_run_id
    ) VALUES (
        p_run_id, p_job_namespace, p_job_name, p_run_state,
        p_inputs, p_outputs, p_facets, p_parent_run_id
    ) RETURNING id INTO v_event_id;

    RETURN v_event_id;
END;
$$;


--
-- Name: rotate_domain_archive(integer, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rotate_domain_archive(p_archive_id integer, p_source_kb_path text, p_archive_kb_path text) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_rotation_id INTEGER;
    v_quarter TEXT;
    v_version TEXT;
BEGIN
    v_quarter := get_current_quarter();

    -- Get version from archive
    SELECT version INTO v_version
    FROM doc_archives
    WHERE id = p_archive_id;

    -- Create rotation record
    INSERT INTO archive_rotations (
        quarter, doc_archive_id, source_kb_path, archive_kb_path,
        version_at_archive, status
    )
    VALUES (
        v_quarter, p_archive_id, p_source_kb_path, p_archive_kb_path,
        v_version, 'pending'
    )
    RETURNING id INTO v_rotation_id;

    RETURN v_rotation_id;
END;
$$;


--
-- Name: rotate_quarterly_archives(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rotate_quarterly_archives() RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_quarter TEXT;
    v_archive RECORD;
    v_rotation_id INTEGER;
    v_results JSONB := '[]'::JSONB;
BEGIN
    v_quarter := get_current_quarter();

    -- Find all completed archives that haven't been rotated this quarter
    FOR v_archive IN
        SELECT da.id, da.kb_path_prefix, da.version, da.content_hash,
               da.source_id, fs.name as source_name
        FROM doc_archives da
        JOIN feed_sources fs ON da.source_id = fs.id
        WHERE da.status = 'completed'
          AND da.kb_path_prefix IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM archive_rotations ar
              WHERE ar.doc_archive_id = da.id
                AND ar.quarter = v_quarter
          )
    LOOP
        -- Create rotation record for each
        v_rotation_id := rotate_domain_archive(
            v_archive.id,
            v_archive.kb_path_prefix,
            'archive/' || v_quarter || '/' ||
                REPLACE(v_archive.kb_path_prefix, 'current/', '')
        );

        v_results := v_results || jsonb_build_object(
            'archive_id', v_archive.id,
            'rotation_id', v_rotation_id,
            'source', v_archive.source_name,
            'source_path', v_archive.kb_path_prefix,
            'version', v_archive.version
        );
    END LOOP;

    RETURN jsonb_build_object(
        'quarter', v_quarter,
        'rotations_scheduled', jsonb_array_length(v_results),
        'details', v_results
    );
END;
$$;


--
-- Name: schedule_due_fetches(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.schedule_due_fetches() RETURNS TABLE(source_name text, job_id integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        fs.name,
        schedule_fetch(fs.name)
    FROM feed_sources fs
    WHERE fs.active = true
      AND (
          fs.last_fetch_at IS NULL
          OR fs.last_fetch_at < NOW() - (fs.fetch_interval_minutes || ' minutes')::INTERVAL
      );
END;
$$;


--
-- Name: schedule_fetch(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.schedule_fetch(p_source_name text) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_source_id INTEGER;
    v_job_id INTEGER;
BEGIN
    SELECT id INTO v_source_id FROM feed_sources WHERE name = p_source_name AND active = true;

    IF v_source_id IS NULL THEN
        RAISE NOTICE 'Source % not found or inactive', p_source_name;
        RETURN NULL;
    END IF;

    INSERT INTO fetch_jobs (source_id, status, metadata)
    VALUES (v_source_id, 'scheduled', jsonb_build_object('scheduled_by', 'pg_cron'))
    RETURNING id INTO v_job_id;

    -- Update last_fetch_at to prevent duplicate scheduling
    UPDATE feed_sources SET last_fetch_at = NOW() WHERE id = v_source_id;

    RETURN v_job_id;
END;
$$;


--
-- Name: schedule_theta_consolidation(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.schedule_theta_consolidation(p_slice_id text DEFAULT NULL::text) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_slice_id TEXT;
    v_job_id INTEGER;
    v_existing INTEGER;
BEGIN
    -- Default to current week if not specified
    v_slice_id := COALESCE(p_slice_id, to_char(NOW(), 'YYYY-"W"IW'));

    -- Check for existing pending job for this slice
    SELECT id INTO v_existing
    FROM theta_consolidation_runs
    WHERE slice_id = v_slice_id
      AND status IN ('scheduled', 'running');

    IF v_existing IS NOT NULL THEN
        RAISE NOTICE 'Consolidation already pending for slice %', v_slice_id;
        RETURN NULL;
    END IF;

    -- Create new scheduled job
    INSERT INTO theta_consolidation_runs (slice_id, status, metadata)
    VALUES (v_slice_id, 'scheduled', jsonb_build_object('scheduled_by', 'pg_cron', 'scheduled_at', NOW()))
    RETURNING id INTO v_job_id;

    RAISE NOTICE 'Scheduled consolidation job % for slice %', v_job_id, v_slice_id;
    RETURN v_job_id;
END;
$$;


--
-- Name: set_active_domain(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_active_domain(p_profile_name text, p_domain_name text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_profile_id INTEGER;
BEGIN
    -- Get profile ID
    SELECT id INTO v_profile_id
    FROM profiles
    WHERE name = p_profile_name;

    IF v_profile_id IS NULL THEN
        RAISE EXCEPTION 'Profile "%" not found', p_profile_name;
    END IF;

    -- Deactivate all domains for this profile
    UPDATE profile_domains
    SET is_active = FALSE, updated_at = NOW()
    WHERE profile_id = v_profile_id AND is_active = TRUE;

    -- Handle 'open' or NULL as clearing the domain
    IF p_domain_name IS NULL OR p_domain_name = '' OR p_domain_name = 'open' THEN
        RETURN TRUE;
    END IF;

    -- Activate the specified domain (upsert)
    INSERT INTO profile_domains (profile_id, name, is_active)
    VALUES (v_profile_id, p_domain_name, TRUE)
    ON CONFLICT (profile_id, name)
    DO UPDATE SET is_active = TRUE, updated_at = NOW();

    RETURN TRUE;
END;
$$;


--
-- Name: set_default_profile(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_default_profile(p_profile_name text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Clear any existing default
    UPDATE profiles SET is_default = FALSE WHERE is_default = TRUE;

    -- Set the new default
    UPDATE profiles SET is_default = TRUE WHERE name = p_profile_name AND active = TRUE;

    -- Return whether the update succeeded
    RETURN FOUND;
END;
$$;


--
-- Name: start_archive_sync(integer, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.start_archive_sync(p_source_id integer, p_archive_url text, p_version text DEFAULT NULL::text) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_archive_id INTEGER;
BEGIN
    INSERT INTO doc_archives (source_id, archive_url, version, status)
    VALUES (p_source_id, p_archive_url, p_version, 'downloading')
    ON CONFLICT (source_id, archive_url)
    DO UPDATE SET
        status = 'downloading',
        version = COALESCE(p_version, doc_archives.version),
        retry_count = doc_archives.retry_count + 1
    RETURNING id INTO v_archive_id;

    RETURN v_archive_id;
END;
$$;


--
-- Name: start_theta_consolidation(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.start_theta_consolidation(p_job_id integer) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE theta_consolidation_runs
    SET status = 'running',
        started_at = NOW()
    WHERE id = p_job_id AND status = 'scheduled';

    RETURN FOUND;
END;
$$;


--
-- Name: time_since_last_cognition(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.time_since_last_cognition(p_profile text DEFAULT 'default'::text) RETURNS interval
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        NOW() - (
            SELECT completed_at
            FROM cognition_cycles
            WHERE profile_name = p_profile
              AND success = TRUE
            ORDER BY completed_at DESC
            LIMIT 1
        ),
        INTERVAL '999 days'
    );
$$;


--
-- Name: time_since_last_session(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.time_since_last_session(p_profile text DEFAULT 'default'::text) RETURNS interval
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        NOW() - (
            SELECT ended_at
            FROM sessions
            WHERE profile_name = p_profile
              AND ended_at IS NOT NULL
            ORDER BY ended_at DESC
            LIMIT 1
        ),
        INTERVAL '999 days'
    );
$$;


--
-- Name: ambient_daemon_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ambient_daemon_state (
    id integer DEFAULT 1 NOT NULL,
    running boolean DEFAULT false NOT NULL,
    baseline_only boolean DEFAULT false NOT NULL,
    max_cycles integer,
    cycles_completed integer DEFAULT 0 NOT NULL,
    total_tasks integer DEFAULT 0 NOT NULL,
    successful_tasks integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone,
    stopped_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ambient_daemon_state_singleton CHECK ((id = 1))
);


--
-- Name: TABLE ambient_daemon_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ambient_daemon_state IS 'Singleton table for ambient daemon state persistence. Auto-restart on engine restart.';


--
-- Name: update_ambient_daemon_state(boolean, boolean, integer, integer, integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_ambient_daemon_state(p_running boolean, p_baseline_only boolean DEFAULT false, p_max_cycles integer DEFAULT NULL::integer, p_cycles_completed integer DEFAULT 0, p_total_tasks integer DEFAULT 0, p_successful_tasks integer DEFAULT 0) RETURNS public.ambient_daemon_state
    LANGUAGE plpgsql
    AS $$
DECLARE
    result ambient_daemon_state;
BEGIN
    UPDATE ambient_daemon_state
    SET
        running = p_running,
        baseline_only = p_baseline_only,
        max_cycles = p_max_cycles,
        cycles_completed = p_cycles_completed,
        total_tasks = p_total_tasks,
        successful_tasks = p_successful_tasks,
        started_at = CASE
            WHEN p_running AND NOT running THEN NOW()  -- Starting fresh
            WHEN p_running THEN started_at             -- Keep existing start time
            ELSE NULL                                   -- Stopped
        END,
        stopped_at = CASE
            WHEN NOT p_running AND running THEN NOW()  -- Just stopped
            ELSE stopped_at                             -- Keep existing
        END,
        updated_at = NOW()
    WHERE id = 1
    RETURNING * INTO result;

    RETURN result;
END;
$$;


--
-- Name: update_calibration_summary(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_calibration_summary() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO calibration_summaries (agent_id, total_calibrations, drift_count, avg_delta, max_delta)
    VALUES (NEW.agent_id, 1,
            CASE WHEN NEW.drift_detected THEN 1 ELSE 0 END,
            NEW.delta,
            ABS(NEW.delta))
    ON CONFLICT (agent_id) DO UPDATE SET
        total_calibrations = calibration_summaries.total_calibrations + 1,
        drift_count = calibration_summaries.drift_count +
            CASE WHEN NEW.drift_detected THEN 1 ELSE 0 END,
        avg_delta = (calibration_summaries.avg_delta * calibration_summaries.total_calibrations + NEW.delta) /
            (calibration_summaries.total_calibrations + 1),
        max_delta = GREATEST(calibration_summaries.max_delta, ABS(NEW.delta)),
        needs_recalibration = CASE
            WHEN ABS(NEW.delta) > 0.15 THEN TRUE
            ELSE calibration_summaries.needs_recalibration
        END,
        updated_at = NOW();

    RETURN NEW;
END;
$$;


--
-- Name: update_current_state(text, integer, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_current_state(p_kb_root text, p_snapshot_id integer, p_state_json jsonb) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
    new_gen BIGINT;
BEGIN
    -- Get next generation (atomic)
    INSERT INTO current_state (kb_root, snapshot_id, generation, state_json)
    VALUES (p_kb_root, p_snapshot_id, 1, p_state_json)
    ON CONFLICT (kb_root) DO UPDATE SET
        snapshot_id = EXCLUDED.snapshot_id,
        generation = current_state.generation + 1,
        state_json = EXCLUDED.state_json,
        updated_at = NOW()
    RETURNING generation INTO new_gen;

    RETURN new_gen;
END;
$$;


--
-- Name: FUNCTION update_current_state(p_kb_root text, p_snapshot_id integer, p_state_json jsonb); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.update_current_state(p_kb_root text, p_snapshot_id integer, p_state_json jsonb) IS 'Atomically update state with incremented generation. Returns new generation.';


--
-- Name: update_health_observer_timestamp(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_health_observer_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: upsert_current_state_if_newer(text, integer, bigint, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.upsert_current_state_if_newer(p_kb_root text, p_snapshot_id integer, p_generation bigint, p_state_json jsonb) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    updated BOOLEAN;
BEGIN
    INSERT INTO current_state (kb_root, snapshot_id, generation, state_json)
    VALUES (p_kb_root, p_snapshot_id, p_generation, p_state_json)
    ON CONFLICT (kb_root) DO UPDATE SET
        snapshot_id = EXCLUDED.snapshot_id,
        generation = EXCLUDED.generation,
        state_json = EXCLUDED.state_json,
        updated_at = NOW()
    WHERE current_state.generation < EXCLUDED.generation;

    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated > 0;
END;
$$;


--
-- Name: FUNCTION upsert_current_state_if_newer(p_kb_root text, p_snapshot_id integer, p_generation bigint, p_state_json jsonb); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.upsert_current_state_if_newer(p_kb_root text, p_snapshot_id integer, p_generation bigint, p_state_json jsonb) IS 'Idempotent update: only applies if incoming generation > current.';


--
-- Name: x_can_request(character varying, character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_can_request(p_user_id character varying, p_endpoint_group character varying DEFAULT 'bookmarks'::character varying) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_reset_at TIMESTAMPTZ;
    v_remaining INTEGER;
BEGIN
    SELECT reset_at, requests_remaining INTO v_reset_at, v_remaining
    FROM x_rate_limits
    WHERE user_id = p_user_id AND endpoint_group = p_endpoint_group;

    -- No rate limit record = allow (first request)
    IF NOT FOUND THEN
        RETURN TRUE;
    END IF;

    -- Past reset time = allow
    IF v_reset_at IS NOT NULL AND v_reset_at <= NOW() THEN
        RETURN TRUE;
    END IF;

    -- Have remaining quota
    IF v_remaining > 0 THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$;


--
-- Name: x_check_token_refresh(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_check_token_refresh(p_user_id character varying) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_expires_at TIMESTAMPTZ;
    v_has_refresh BOOLEAN;
BEGIN
    SELECT expires_at, refresh_token IS NOT NULL INTO v_expires_at, v_has_refresh
    FROM x_oauth_tokens
    WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        RETURN FALSE;  -- No token
    END IF;

    -- Needs refresh if expires within 5 minutes
    IF v_expires_at IS NOT NULL AND v_expires_at <= NOW() + INTERVAL '5 minutes' THEN
        RETURN v_has_refresh;
    END IF;

    RETURN FALSE;  -- Token still valid
END;
$$;


--
-- Name: x_cleanup_pending_auths(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_cleanup_pending_auths() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM x_oauth_pending WHERE expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;


--
-- Name: x_complete_sync_run(integer, character varying, integer, integer, integer, character varying, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_complete_sync_run(p_run_id integer, p_status character varying, p_bookmarks_fetched integer DEFAULT 0, p_bookmarks_new integer DEFAULT 0, p_folders_synced integer DEFAULT 0, p_pagination_token character varying DEFAULT NULL::character varying, p_error_message text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE x_sync_runs SET
        status = p_status,
        bookmarks_fetched = p_bookmarks_fetched,
        bookmarks_new = p_bookmarks_new,
        folders_synced = p_folders_synced,
        pagination_token = p_pagination_token,
        completed_at = NOW(),
        error_message = p_error_message
    WHERE id = p_run_id;
END;
$$;


--
-- Name: x_get_auto_sync_status(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_get_auto_sync_status(p_user_id character varying) RETURNS TABLE(active boolean, folders_total integer, folders_synced integer, folders_remaining integer, iterations integer, max_iterations integer, next_run_at timestamp with time zone, estimated_completion timestamp with time zone)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.is_active,
        s.folders_total,
        s.folders_synced,
        s.folders_total - s.folders_synced,
        s.sync_iterations,
        s.max_iterations,
        s.next_run_at,
        CASE
            WHEN s.folders_synced = 0 THEN NULL
            ELSE NOW() + (
                ((s.folders_total - s.folders_synced)::FLOAT /
                 GREATEST(s.folders_synced::FLOAT / GREATEST(s.sync_iterations, 1), 1)) *
                s.interval_minutes
            ) * INTERVAL '1 minute'
        END AS estimated_completion
    FROM x_auto_sync_schedules s
    WHERE s.user_id = p_user_id;
END;
$$;


--
-- Name: x_get_due_auto_syncs(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_get_due_auto_syncs() RETURNS TABLE(user_id character varying, folders_remaining integer, iterations integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.user_id,
        s.folders_total - s.folders_synced AS folders_remaining,
        s.sync_iterations
    FROM x_auto_sync_schedules s
    JOIN x_oauth_tokens t ON t.user_id = s.user_id
    WHERE s.is_active = TRUE
      AND s.next_run_at <= NOW()
      AND t.expires_at > NOW()  -- Token still valid
    ORDER BY s.next_run_at ASC
    LIMIT 5;  -- Process up to 5 users at a time
END;
$$;


--
-- Name: x_get_next_request(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_get_next_request(p_user_id character varying) RETURNS TABLE(request_id integer, request_type character varying, endpoint character varying, pagination_token character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Only return if rate limit allows
    IF NOT x_can_request(p_user_id) THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT r.id, r.request_type, r.endpoint, r.pagination_token
    FROM x_api_requests r
    WHERE r.user_id = p_user_id
      AND r.status = 'queued'
    ORDER BY r.priority DESC, r.queued_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
END;
$$;


--
-- Name: x_is_auto_sync_active(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_is_auto_sync_active(p_user_id character varying) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM x_auto_sync_schedules
        WHERE user_id = p_user_id AND is_active = TRUE
    );
END;
$$;


--
-- Name: x_process_request_queue(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_process_request_queue() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_processed INTEGER := 0;
    v_request RECORD;
BEGIN
    -- Find users with queued requests that can proceed
    FOR v_request IN
        SELECT DISTINCT r.user_id
        FROM x_api_requests r
        WHERE r.status = 'queued'
          AND x_can_request(r.user_id)
    LOOP
        -- Mark one request per user as ready for processing
        UPDATE x_api_requests
        SET status = 'executing', started_at = NOW()
        WHERE id = (
            SELECT id FROM x_api_requests
            WHERE user_id = v_request.user_id AND status = 'queued'
            ORDER BY priority DESC, queued_at
            LIMIT 1
        );

        v_processed := v_processed + 1;
    END LOOP;

    RETURN v_processed;
END;
$$;


--
-- Name: x_queue_bookmark_sync(character varying, integer, character varying, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_queue_bookmark_sync(p_user_id character varying, p_sync_run_id integer, p_pagination_token character varying DEFAULT NULL::character varying, p_priority integer DEFAULT 0) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_request_id INTEGER;
BEGIN
    INSERT INTO x_api_requests (user_id, request_type, endpoint, status, priority, pagination_token, sync_run_id)
    VALUES (
        p_user_id,
        'bookmarks',
        format('/2/users/%s/bookmarks', p_user_id),
        'queued',
        p_priority,
        p_pagination_token,
        p_sync_run_id
    )
    RETURNING id INTO v_request_id;

    RETURN v_request_id;
END;
$$;


--
-- Name: x_record_request(character varying, character varying, integer, integer, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_record_request(p_user_id character varying, p_endpoint_group character varying, p_remaining integer, p_limit integer, p_reset_at timestamp with time zone) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO x_rate_limits (user_id, endpoint_group, requests_remaining, requests_limit, reset_at, last_request_at, updated_at)
    VALUES (p_user_id, p_endpoint_group, p_remaining, p_limit, p_reset_at, NOW(), NOW())
    ON CONFLICT (user_id) DO UPDATE SET
        endpoint_group = EXCLUDED.endpoint_group,
        requests_remaining = EXCLUDED.requests_remaining,
        requests_limit = EXCLUDED.requests_limit,
        reset_at = EXCLUDED.reset_at,
        last_request_at = NOW(),
        updated_at = NOW();
END;
$$;


--
-- Name: x_start_auto_sync(character varying, integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_start_auto_sync(p_user_id character varying, p_folders_total integer DEFAULT 0, p_interval_minutes integer DEFAULT 16) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_next_run TIMESTAMPTZ;
BEGIN
    -- Schedule first continuation run after rate limit window
    v_next_run := NOW() + (p_interval_minutes || ' minutes')::INTERVAL;

    INSERT INTO x_auto_sync_schedules (
        user_id, is_active, next_run_at, folders_total, interval_minutes, metadata
    ) VALUES (
        p_user_id, TRUE, v_next_run, p_folders_total, p_interval_minutes,
        jsonb_build_object('started_at', NOW(), 'trigger', 'manual')
    )
    ON CONFLICT (user_id) DO UPDATE SET
        is_active = TRUE,
        next_run_at = v_next_run,
        folders_total = COALESCE(NULLIF(p_folders_total, 0), x_auto_sync_schedules.folders_total),
        folders_synced = 0,  -- Reset progress
        sync_iterations = 0,
        interval_minutes = p_interval_minutes,
        updated_at = NOW(),
        completed_at = NULL,
        last_error = NULL,
        metadata = jsonb_build_object('restarted_at', NOW(), 'trigger', 'manual');

    RAISE NOTICE 'Started auto-sync for user %, next run at %', p_user_id, v_next_run;
    RETURN TRUE;
END;
$$;


--
-- Name: x_start_sync_run(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_start_sync_run(p_user_id character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_run_id INTEGER;
BEGIN
    INSERT INTO x_sync_runs (user_id, status)
    VALUES (p_user_id, 'running')
    RETURNING id INTO v_run_id;

    RETURN v_run_id;
END;
$$;


--
-- Name: x_stop_auto_sync(character varying, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_stop_auto_sync(p_user_id character varying, p_reason text DEFAULT 'manual'::text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE x_auto_sync_schedules SET
        is_active = FALSE,
        completed_at = NOW(),
        metadata = metadata || jsonb_build_object('stop_reason', p_reason, 'stopped_at', NOW())
    WHERE user_id = p_user_id AND is_active = TRUE;

    IF FOUND THEN
        RAISE NOTICE 'Stopped auto-sync for user %, reason: %', p_user_id, p_reason;
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$;


--
-- Name: x_trigger_daily_sync(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_trigger_daily_sync() RETURNS TABLE(user_id character varying, run_id integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT t.user_id, x_start_sync_run(t.user_id)
    FROM x_oauth_tokens t
    WHERE t.refresh_token IS NOT NULL;  -- Only users with valid tokens
END;
$$;


--
-- Name: x_trigger_due_auto_syncs(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_trigger_due_auto_syncs() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_count INTEGER := 0;
    v_user RECORD;
BEGIN
    FOR v_user IN SELECT * FROM x_get_due_auto_syncs()
    LOOP
        -- Use pg_notify to alert the engine
        PERFORM pg_notify(
            'x_auto_sync_due',
            json_build_object(
                'user_id', v_user.user_id,
                'folders_remaining', v_user.folders_remaining,
                'iteration', v_user.iterations + 1
            )::TEXT
        );
        v_count := v_count + 1;

        RAISE NOTICE 'Triggered auto-sync for user %, iteration %',
            v_user.user_id, v_user.iterations + 1;
    END LOOP;

    RETURN v_count;
END;
$$;


--
-- Name: x_update_auto_sync_progress(character varying, integer, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_update_auto_sync_progress(p_user_id character varying, p_folders_synced_this_batch integer, p_folders_remaining integer, p_error text DEFAULT NULL::text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_schedule RECORD;
    v_next_run TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_schedule FROM x_auto_sync_schedules WHERE user_id = p_user_id;

    IF NOT FOUND OR NOT v_schedule.is_active THEN
        RETURN FALSE;
    END IF;

    -- Update progress
    UPDATE x_auto_sync_schedules SET
        folders_synced = folders_synced + p_folders_synced_this_batch,
        sync_iterations = sync_iterations + 1,
        updated_at = NOW(),
        last_error = p_error
    WHERE user_id = p_user_id;

    -- Check completion conditions
    IF p_folders_remaining = 0 THEN
        -- All done!
        PERFORM x_stop_auto_sync(p_user_id, 'completed');
        RETURN TRUE;
    END IF;

    IF v_schedule.sync_iterations + 1 >= v_schedule.max_iterations THEN
        -- Hit iteration limit
        PERFORM x_stop_auto_sync(p_user_id, 'max_iterations');
        RETURN TRUE;
    END IF;

    -- Schedule next iteration
    v_next_run := NOW() + (v_schedule.interval_minutes || ' minutes')::INTERVAL;
    UPDATE x_auto_sync_schedules SET next_run_at = v_next_run WHERE user_id = p_user_id;

    RETURN TRUE;
END;
$$;


--
-- Name: x_upsert_folder(character varying, character varying, character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.x_upsert_folder(p_x_folder_id character varying, p_user_id character varying, p_name character varying) RETURNS character varying
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_kb_path VARCHAR(1024);
    v_safe_name VARCHAR(255);
BEGIN
    -- Sanitize folder name for filesystem
    v_safe_name := regexp_replace(lower(p_name), '[^a-z0-9_-]', '_', 'g');
    v_kb_path := format('current/bookmarks/%s/', v_safe_name);

    INSERT INTO x_bookmark_folders (x_folder_id, user_id, name, kb_path)
    VALUES (p_x_folder_id, p_user_id, p_name, v_kb_path)
    ON CONFLICT (x_folder_id) DO UPDATE SET
        name = EXCLUDED.name,
        updated_at = NOW()
    RETURNING kb_path INTO v_kb_path;

    RETURN v_kb_path;
END;
$$;


--
-- Name: _ag_label_vertex; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx._ag_label_vertex (
    id ag_catalog.graphid NOT NULL,
    properties ag_catalog.agtype DEFAULT ag_catalog.agtype_build_map() NOT NULL
);


--
-- Name: Dataset; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."Dataset" (
)
INHERITS (gaius_hx._ag_label_vertex);


--
-- Name: Dataset_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."Dataset_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: Dataset_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."Dataset_id_seq" OWNED BY gaius_hx."Dataset".id;


--
-- Name: _ag_label_edge; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx._ag_label_edge (
    id ag_catalog.graphid NOT NULL,
    start_id ag_catalog.graphid NOT NULL,
    end_id ag_catalog.graphid NOT NULL,
    properties ag_catalog.agtype DEFAULT ag_catalog.agtype_build_map() NOT NULL
);


--
-- Name: EXECUTES; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."EXECUTES" (
)
INHERITS (gaius_hx._ag_label_edge);


--
-- Name: EXECUTES_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."EXECUTES_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: EXECUTES_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."EXECUTES_id_seq" OWNED BY gaius_hx."EXECUTES".id;


--
-- Name: INPUT_TO; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."INPUT_TO" (
)
INHERITS (gaius_hx._ag_label_edge);


--
-- Name: INPUT_TO_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."INPUT_TO_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: INPUT_TO_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."INPUT_TO_id_seq" OWNED BY gaius_hx."INPUT_TO".id;


--
-- Name: Job; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."Job" (
)
INHERITS (gaius_hx._ag_label_vertex);


--
-- Name: Job_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."Job_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: Job_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."Job_id_seq" OWNED BY gaius_hx."Job".id;


--
-- Name: OUTPUTS; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."OUTPUTS" (
)
INHERITS (gaius_hx._ag_label_edge);


--
-- Name: OUTPUTS_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."OUTPUTS_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: OUTPUTS_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."OUTPUTS_id_seq" OWNED BY gaius_hx."OUTPUTS".id;


--
-- Name: PARENT; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."PARENT" (
)
INHERITS (gaius_hx._ag_label_edge);


--
-- Name: PARENT_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."PARENT_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: PARENT_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."PARENT_id_seq" OWNED BY gaius_hx."PARENT".id;


--
-- Name: Run; Type: TABLE; Schema: gaius_hx; Owner: -
--

CREATE TABLE gaius_hx."Run" (
)
INHERITS (gaius_hx._ag_label_vertex);


--
-- Name: Run_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx."Run_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: Run_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx."Run_id_seq" OWNED BY gaius_hx."Run".id;


--
-- Name: _ag_label_edge_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx._ag_label_edge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: _ag_label_edge_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx._ag_label_edge_id_seq OWNED BY gaius_hx._ag_label_edge.id;


--
-- Name: _ag_label_vertex_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx._ag_label_vertex_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 281474976710655
    CACHE 1;


--
-- Name: _ag_label_vertex_id_seq; Type: SEQUENCE OWNED BY; Schema: gaius_hx; Owner: -
--

ALTER SEQUENCE gaius_hx._ag_label_vertex_id_seq OWNED BY gaius_hx._ag_label_vertex.id;


--
-- Name: _label_id_seq; Type: SEQUENCE; Schema: gaius_hx; Owner: -
--

CREATE SEQUENCE gaius_hx._label_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 65535
    CACHE 1
    CYCLE;


--
-- Name: agenda_incidents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agenda_incidents (
    id integer NOT NULL,
    incident_id uuid DEFAULT gen_random_uuid() NOT NULL,
    agenda_id text NOT NULL,
    agenda_type public.agenda_type NOT NULL,
    phases jsonb NOT NULL,
    current_phase_index integer DEFAULT 0,
    scheduler_plan_id text,
    makespan_projection_ms integer,
    actual_duration_ms integer DEFAULT 0,
    makespan_variance_pct real DEFAULT 0.0,
    status public.agenda_status DEFAULT 'scheduling'::public.agenda_status NOT NULL,
    control_mode public.control_mode DEFAULT 'positive'::public.control_mode NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    baseline_departed_at timestamp with time zone,
    baseline_restored_at timestamp with time zone,
    resolved_at timestamp with time zone,
    severity_score integer DEFAULT 0,
    endpoint_transitions jsonb DEFAULT '[]'::jsonb,
    healing_event_ids jsonb DEFAULT '[]'::jsonb,
    escalation_reason text,
    source_operation_id uuid,
    acp_escalated boolean DEFAULT false,
    acp_escalated_at timestamp with time zone
);


--
-- Name: TABLE agenda_incidents; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agenda_incidents IS 'Agenda-centric incident tracking - success = makespan fulfillment + positive control';


--
-- Name: COLUMN agenda_incidents.agenda_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.agenda_id IS 'WorkloadRequest.workload_id - correlates with orchestrator';


--
-- Name: COLUMN agenda_incidents.phases; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.phases IS 'Ordered capability phases: [{name, required_capabilities, target_endpoints}]';


--
-- Name: COLUMN agenda_incidents.makespan_variance_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.makespan_variance_pct IS 'Deviation from OR-Tools projection: (actual - projected) / projected';


--
-- Name: COLUMN agenda_incidents.control_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.control_mode IS 'How transitions occurred: positive (planned), failure_recovery, restart_recovery';


--
-- Name: COLUMN agenda_incidents.escalation_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.escalation_reason IS 'Why this operation became an incident (e.g., "control_degraded", "makespan_exceeded", "phase_blocked")';


--
-- Name: COLUMN agenda_incidents.source_operation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.source_operation_id IS 'Links back to agenda_operations if escalated from there';


--
-- Name: COLUMN agenda_incidents.acp_escalated; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_incidents.acp_escalated IS 'Whether this incident was escalated to ACP for intervention';


--
-- Name: active_incidents; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.active_incidents AS
 SELECT incident_id,
    agenda_id,
    (agenda_type)::text AS agenda_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    escalation_reason,
    severity_score,
    acp_escalated,
    acp_escalated_at,
    created_at,
    (now() - created_at) AS age,
    ((phases -> current_phase_index) ->> 'name'::text) AS blocked_at_phase
   FROM public.agenda_incidents ai
  WHERE (status <> ALL (ARRAY['fulfilled'::public.agenda_status, 'failed'::public.agenda_status, 'degraded'::public.agenda_status]))
  ORDER BY severity_score DESC, created_at;


--
-- Name: VIEW active_incidents; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.active_incidents IS 'Currently active incidents requiring attention - for ACP/Health dashboard';


--
-- Name: agenda_phase_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agenda_phase_events (
    id bigint NOT NULL,
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    agenda_incident_id integer,
    phase_index integer NOT NULL,
    phase_name text NOT NULL,
    event_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    projected_duration_ms integer,
    actual_duration_ms integer,
    control_mode public.control_mode DEFAULT 'positive'::public.control_mode NOT NULL,
    endpoint text,
    endpoint_from_state text,
    endpoint_to_state text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: TABLE agenda_phase_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agenda_phase_events IS 'Event-sourced log of agenda phase transitions';


--
-- Name: COLUMN agenda_phase_events.control_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_phase_events.control_mode IS 'Control mode at time of event - may differ from agenda-level';


--
-- Name: agenda_phase_metrics; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.agenda_phase_metrics AS
 SELECT date_trunc('hour'::text, created_at) AS hour,
    phase_name,
    event_type,
    (control_mode)::text AS control_mode,
    count(*) AS event_count,
    (avg(actual_duration_ms))::integer AS avg_duration_ms,
    (percentile_cont((0.50)::double precision) WITHIN GROUP (ORDER BY ((actual_duration_ms)::double precision)))::integer AS p50_duration_ms,
    (percentile_cont((0.95)::double precision) WITHIN GROUP (ORDER BY ((actual_duration_ms)::double precision)))::integer AS p95_duration_ms,
    (percentile_cont((0.99)::double precision) WITHIN GROUP (ORDER BY ((actual_duration_ms)::double precision)))::integer AS p99_duration_ms
   FROM public.agenda_phase_events ape
  WHERE (actual_duration_ms IS NOT NULL)
  GROUP BY (date_trunc('hour'::text, created_at)), phase_name, event_type, (control_mode)::text
  ORDER BY (date_trunc('hour'::text, created_at)) DESC;


--
-- Name: VIEW agenda_phase_metrics; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.agenda_phase_metrics IS 'Hourly phase-level metrics with latency percentiles for Metabase';


--
-- Name: agenda_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agenda_operations (
    id integer NOT NULL,
    operation_id uuid DEFAULT gen_random_uuid() NOT NULL,
    workload_id text NOT NULL,
    workload_type public.agenda_type NOT NULL,
    phases jsonb DEFAULT '[]'::jsonb NOT NULL,
    current_phase_index integer DEFAULT 0,
    scheduler_plan_id text,
    makespan_projection_ms integer,
    actual_duration_ms integer DEFAULT 0,
    makespan_variance_pct real DEFAULT 0.0,
    status public.agenda_status DEFAULT 'scheduling'::public.agenda_status NOT NULL,
    control_mode public.control_mode DEFAULT 'positive'::public.control_mode NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    endpoint_transitions jsonb DEFAULT '[]'::jsonb,
    escalated_to_incident_id integer
);


--
-- Name: TABLE agenda_operations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agenda_operations IS 'All workload executions for state recovery and operational metrics';


--
-- Name: COLUMN agenda_operations.workload_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_operations.workload_id IS 'WorkloadRequest.workload_id - correlates with orchestrator';


--
-- Name: COLUMN agenda_operations.escalated_to_incident_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agenda_operations.escalated_to_incident_id IS 'Links to agenda_incidents if operation became an incident';


--
-- Name: agenda_resolution_daily; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.agenda_resolution_daily AS
 SELECT date_trunc('day'::text, completed_at) AS day,
    (workload_type)::text AS agenda_type,
    count(*) AS total_completed,
    (sum(
        CASE
            WHEN (status = 'fulfilled'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS fulfilled_count,
    (sum(
        CASE
            WHEN (status = 'degraded'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS degraded_count,
    (sum(
        CASE
            WHEN (status = 'failed'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS failed_count,
    (avg(actual_duration_ms))::integer AS avg_completion_time_ms,
    (avg(makespan_variance_pct))::real AS avg_makespan_variance_pct,
        CASE
            WHEN (count(*) > 0) THEN ((sum(
            CASE
                WHEN (status = 'fulfilled'::public.agenda_status) THEN 1
                ELSE 0
            END))::real / (count(*))::real)
            ELSE (0)::real
        END AS fulfillment_rate,
        CASE
            WHEN (count(*) > 0) THEN ((sum(
            CASE
                WHEN (escalated_to_incident_id IS NOT NULL) THEN 1
                ELSE 0
            END))::real / (count(*))::real)
            ELSE (0)::real
        END AS escalation_rate
   FROM public.agenda_operations ao
  WHERE (completed_at IS NOT NULL)
  GROUP BY (date_trunc('day'::text, completed_at)), (workload_type)::text
  ORDER BY (date_trunc('day'::text, completed_at)) DESC;


--
-- Name: VIEW agenda_resolution_daily; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.agenda_resolution_daily IS 'Daily operation completion metrics with fulfillment and escalation rates';


--
-- Name: agent_performance; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.agent_performance (
    agent_id text NOT NULL,
    date date NOT NULL,
    active_version_id text,
    evaluations_count integer DEFAULT 0,
    avg_overall_score double precision,
    evolution_cycles integer DEFAULT 0,
    improvement_percent double precision
);


--
-- Name: alert_thresholds; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.alert_thresholds (
    metric_name character varying(64) NOT NULL,
    category character varying(32) NOT NULL,
    description text,
    warning_threshold double precision,
    critical_threshold double precision,
    comparison character varying(8) DEFAULT '>='::character varying,
    enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE alert_thresholds; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.alert_thresholds IS 'Alert thresholds for Metabase dashboard alerts';


--
-- Name: ambient_cycle_metrics; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.ambient_cycle_metrics AS
 SELECT date_trunc('hour'::text, created_at) AS hour,
    (workload_type)::text AS agenda_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    count(*) AS cycle_count,
    (avg(actual_duration_ms))::integer AS avg_duration_ms,
    (avg(makespan_variance_pct))::real AS avg_variance_pct,
    (sum(
        CASE
            WHEN (status = 'fulfilled'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS fulfilled_count,
    (sum(
        CASE
            WHEN (status = 'degraded'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS degraded_count,
    (sum(
        CASE
            WHEN (status = 'failed'::public.agenda_status) THEN 1
            ELSE 0
        END))::integer AS failed_count,
    (sum(
        CASE
            WHEN (control_mode <> 'positive'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS non_positive_count,
    (sum(
        CASE
            WHEN (escalated_to_incident_id IS NOT NULL) THEN 1
            ELSE 0
        END))::integer AS escalated_count
   FROM public.agenda_operations ao
  GROUP BY (date_trunc('hour'::text, created_at)), (workload_type)::text, (status)::text, (control_mode)::text
  ORDER BY (date_trunc('hour'::text, created_at)) DESC;


--
-- Name: VIEW ambient_cycle_metrics; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.ambient_cycle_metrics IS 'Hourly aggregate metrics from agenda_operations for Metabase dashboards';


--
-- Name: audit_budget_pool; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.audit_budget_pool (
    pool_id text NOT NULL,
    weekly_limit integer DEFAULT 50 NOT NULL,
    weekly_used integer DEFAULT 0 NOT NULL,
    grok_calls integer DEFAULT 0 NOT NULL,
    cerebras_calls integer DEFAULT 0 NOT NULL,
    week_start date DEFAULT (date_trunc('week'::text, (CURRENT_DATE)::timestamp with time zone))::date NOT NULL,
    last_reset timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE audit_budget_pool; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.audit_budget_pool IS 'Shared weekly budget pool for remote LLM calls (Grok + Cerebras)';


--
-- Name: COLUMN audit_budget_pool.pool_id; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.audit_budget_pool.pool_id IS 'Pool identifier (e.g., weekly_audit)';


--
-- Name: COLUMN audit_budget_pool.weekly_limit; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.audit_budget_pool.weekly_limit IS 'Maximum calls per week across all providers';


--
-- Name: COLUMN audit_budget_pool.weekly_used; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.audit_budget_pool.weekly_used IS 'Total calls used this week (Grok + Cerebras)';


--
-- Name: audit_recommendations; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.audit_recommendations (
    id integer NOT NULL,
    audit_id uuid,
    category text NOT NULL,
    severity text NOT NULL,
    title text NOT NULL,
    description text,
    suggested_implementation text,
    affected_component text,
    status text DEFAULT 'pending'::text,
    accepted_at timestamp with time zone,
    implemented_at timestamp with time zone,
    verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE audit_recommendations; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.audit_recommendations IS 'Actionable recommendations from audits for Atropos RL';


--
-- Name: audit_recommendations_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.audit_recommendations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_recommendations_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.audit_recommendations_id_seq OWNED BY meta.audit_recommendations.id;


--
-- Name: control_mode_health; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.control_mode_health AS
 SELECT date_trunc('day'::text, created_at) AS day,
    count(*) AS total_operations,
    (sum(
        CASE
            WHEN (control_mode = 'positive'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS positive_control_count,
    (sum(
        CASE
            WHEN (control_mode = 'failure_recovery'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS failure_recovery_count,
    (sum(
        CASE
            WHEN (control_mode = 'restart_recovery'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS restart_recovery_count,
        CASE
            WHEN (count(*) > 0) THEN ((sum(
            CASE
                WHEN (control_mode = 'positive'::public.control_mode) THEN 1
                ELSE 0
            END))::real / (count(*))::real)
            ELSE (0)::real
        END AS positive_control_rate,
    (sum(
        CASE
            WHEN (escalated_to_incident_id IS NOT NULL) THEN 1
            ELSE 0
        END))::integer AS escalation_count
   FROM public.agenda_operations ao
  WHERE (created_at > (now() - '7 days'::interval))
  GROUP BY (date_trunc('day'::text, created_at))
  ORDER BY (date_trunc('day'::text, created_at)) DESC;


--
-- Name: VIEW control_mode_health; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.control_mode_health IS 'Daily control mode health from operations, showing positive vs recovery transitions';


--
-- Name: data_dependencies; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.data_dependencies (
    id integer NOT NULL,
    source_dataset_id text,
    target_dataset_id text,
    via_job_id text,
    first_observed timestamp with time zone,
    last_observed timestamp with time zone,
    occurrence_count integer DEFAULT 1
);


--
-- Name: data_dependencies_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.data_dependencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_dependencies_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.data_dependencies_id_seq OWNED BY meta.data_dependencies.id;


--
-- Name: dataset_catalog; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.dataset_catalog (
    dataset_id text NOT NULL,
    namespace text NOT NULL,
    name text NOT NULL,
    first_seen timestamp with time zone,
    last_seen timestamp with time zone,
    total_reads integer DEFAULT 0,
    total_writes integer DEFAULT 0
);


--
-- Name: document_clusters; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.document_clusters (
    id integer NOT NULL,
    snapshot_id integer,
    cluster_id integer,
    centroid_x integer,
    centroid_y integer,
    document_count integer,
    dominant_domain text,
    topic_keywords text[],
    avg_persistence double precision
);


--
-- Name: document_clusters_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.document_clusters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_clusters_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.document_clusters_id_seq OWNED BY meta.document_clusters.id;


--
-- Name: endpoint_transition_metrics; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.endpoint_transition_metrics AS
 SELECT date_trunc('hour'::text, created_at) AS hour,
    endpoint,
    endpoint_from_state,
    endpoint_to_state,
    (control_mode)::text AS control_mode,
    count(*) AS transition_count,
    (sum(
        CASE
            WHEN (control_mode = 'positive'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS positive_count,
    (sum(
        CASE
            WHEN (control_mode = 'failure_recovery'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS failure_recovery_count,
    (sum(
        CASE
            WHEN (control_mode = 'restart_recovery'::public.control_mode) THEN 1
            ELSE 0
        END))::integer AS restart_recovery_count
   FROM public.agenda_phase_events ape
  WHERE ((endpoint IS NOT NULL) AND (endpoint_from_state IS NOT NULL) AND (endpoint_to_state IS NOT NULL))
  GROUP BY (date_trunc('hour'::text, created_at)), endpoint, endpoint_from_state, endpoint_to_state, (control_mode)::text
  ORDER BY (date_trunc('hour'::text, created_at)) DESC;


--
-- Name: VIEW endpoint_transition_metrics; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.endpoint_transition_metrics IS 'Endpoint state transitions by control mode for Metabase';


--
-- Name: flow_events; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.flow_events (
    event_id integer NOT NULL,
    run_id uuid NOT NULL,
    flow_type text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE flow_events; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.flow_events IS 'Audit trail for flow completion events (LISTEN/NOTIFY)';


--
-- Name: COLUMN flow_events.run_id; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.flow_events.run_id IS 'References meta.flow_runs';


--
-- Name: COLUMN flow_events.flow_type; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.flow_events.flow_type IS 'Type of flow (ResearchFlow, ArxivDoclingFlow, etc.)';


--
-- Name: COLUMN flow_events.status; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.flow_events.status IS 'Terminal status: completed or failed';


--
-- Name: flow_events_event_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.flow_events_event_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_events_event_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.flow_events_event_id_seq OWNED BY meta.flow_events.event_id;


--
-- Name: flow_runs; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.flow_runs (
    run_id uuid NOT NULL,
    flow_type text NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    duration_ms integer,
    status text,
    inputs_count integer DEFAULT 0,
    outputs_count integer DEFAULT 0,
    metadata jsonb DEFAULT '{}'::jsonb,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: fmea_rpn_timeseries; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.fmea_rpn_timeseries (
    failure_mode_id character varying(32) NOT NULL,
    hour timestamp with time zone NOT NULL,
    avg_rpn double precision,
    min_rpn integer,
    max_rpn integer,
    outcome_count integer DEFAULT 0,
    success_count integer DEFAULT 0,
    failure_count integer DEFAULT 0
);


--
-- Name: TABLE fmea_rpn_timeseries; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.fmea_rpn_timeseries IS 'Hourly RPN aggregates for FMEA trend analysis in Metabase';


--
-- Name: fmp_sync_runs; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.fmp_sync_runs (
    id integer NOT NULL,
    profile character varying(64) DEFAULT 'zndx'::character varying NOT NULL,
    domain character varying(64) DEFAULT 'prospecting'::character varying NOT NULL,
    run_type character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    symbols_processed integer DEFAULT 0,
    filings_fetched integer DEFAULT 0,
    filings_new integer DEFAULT 0,
    holders_fetched integer DEFAULT 0,
    analysis_cost_usd real DEFAULT 0.0,
    synthesis_cost_usd real DEFAULT 0.0,
    kb_artifacts_created integer DEFAULT 0,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE fmp_sync_runs; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.fmp_sync_runs IS 'FMP sync operation history with cost tracking';


--
-- Name: COLUMN fmp_sync_runs.analysis_cost_usd; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.fmp_sync_runs.analysis_cost_usd IS 'Cerebras GLM 4.7 analysis cost';


--
-- Name: COLUMN fmp_sync_runs.synthesis_cost_usd; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.fmp_sync_runs.synthesis_cost_usd IS 'XAI Grok synthesis cost';


--
-- Name: fmp_sync_runs_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.fmp_sync_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fmp_sync_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.fmp_sync_runs_id_seq OWNED BY meta.fmp_sync_runs.id;


--
-- Name: gpu_hourly_stats; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.gpu_hourly_stats (
    hour timestamp with time zone NOT NULL,
    gpu_index smallint NOT NULL,
    samples integer DEFAULT 0,
    memory_min_mb real,
    memory_max_mb real,
    memory_avg_mb real,
    util_min_pct real,
    util_max_pct real,
    util_avg_pct real,
    temp_max_c real,
    power_avg_w real
);


--
-- Name: TABLE gpu_hourly_stats; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.gpu_hourly_stats IS 'Hourly GPU rollups with 30-day retention for Metabase time series';


--
-- Name: gpu_minute_stats; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.gpu_minute_stats (
    minute timestamp with time zone NOT NULL,
    gpu_index smallint NOT NULL,
    samples integer DEFAULT 0,
    memory_min_mb real,
    memory_max_mb real,
    memory_avg_mb real,
    util_min_pct real,
    util_max_pct real,
    util_avg_pct real,
    temp_max_c real,
    power_avg_w real
);


--
-- Name: TABLE gpu_minute_stats; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.gpu_minute_stats IS 'Minute-level GPU stats with 24h retention for Metabase time series';


--
-- Name: gpu_utilization; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.gpu_utilization (
    "timestamp" timestamp with time zone NOT NULL,
    gpu_index integer NOT NULL,
    memory_used_mb integer,
    memory_total_mb integer,
    utilization_percent double precision,
    temperature_c integer,
    active_endpoint text
);


--
-- Name: incident_summary; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.incident_summary AS
 SELECT date_trunc('day'::text, created_at) AS day,
    (agenda_type)::text AS agenda_type,
    escalation_reason,
    count(*) AS incident_count,
    (sum(
        CASE
            WHEN acp_escalated THEN 1
            ELSE 0
        END))::integer AS acp_escalated_count,
    (avg(severity_score))::integer AS avg_severity,
    (avg(EXTRACT(epoch FROM (COALESCE(resolved_at, now()) - created_at))))::integer AS avg_resolution_seconds
   FROM public.agenda_incidents ai
  WHERE (created_at > (now() - '30 days'::interval))
  GROUP BY (date_trunc('day'::text, created_at)), (agenda_type)::text, escalation_reason
  ORDER BY (date_trunc('day'::text, created_at)) DESC, (count(*)) DESC;


--
-- Name: VIEW incident_summary; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.incident_summary IS 'Daily incident summary by type and escalation reason';


--
-- Name: inference_hourly; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.inference_hourly (
    hour timestamp with time zone NOT NULL,
    model character varying(128) NOT NULL,
    endpoint character varying(64) DEFAULT ''::character varying NOT NULL,
    request_count integer DEFAULT 0,
    tokens_total bigint DEFAULT 0,
    tokens_avg real,
    latency_min_ms real,
    latency_max_ms real,
    latency_p50_ms real,
    latency_p95_ms real,
    latency_p99_ms real,
    errors_count integer DEFAULT 0
);


--
-- Name: TABLE inference_hourly; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.inference_hourly IS 'Hourly inference metrics with percentiles for Metabase time series';


--
-- Name: inference_throughput; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.inference_throughput (
    hour timestamp with time zone NOT NULL,
    model text NOT NULL,
    requests_count integer DEFAULT 0,
    tokens_generated bigint DEFAULT 0,
    avg_latency_ms double precision,
    p95_latency_ms double precision
);


--
-- Name: institutional_holders_cache; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.institutional_holders_cache (
    id integer NOT NULL,
    symbol character varying(16) NOT NULL,
    holder_name character varying(255) NOT NULL,
    holder_cik character varying(32),
    shares bigint,
    shares_change bigint,
    shares_change_pct real,
    value_usd bigint,
    filing_date date,
    fetched_at timestamp with time zone DEFAULT now(),
    iceberg_exchange_id uuid
);


--
-- Name: TABLE institutional_holders_cache; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.institutional_holders_cache IS 'Cached institutional holders from FMP 13F data';


--
-- Name: institutional_holders_cache_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.institutional_holders_cache_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_holders_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.institutional_holders_cache_id_seq OWNED BY meta.institutional_holders_cache.id;


--
-- Name: job_catalog; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.job_catalog (
    job_id text NOT NULL,
    namespace text NOT NULL,
    name text NOT NULL,
    first_run timestamp with time zone,
    last_run timestamp with time zone,
    total_runs integer DEFAULT 0,
    success_count integer DEFAULT 0,
    failure_count integer DEFAULT 0,
    avg_duration_ms double precision
);


--
-- Name: kb_topology; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.kb_topology (
    snapshot_id integer NOT NULL,
    computed_at timestamp with time zone,
    n_documents integer,
    coverage double precision,
    h0_count integer,
    h1_count integer,
    h2_count integer,
    entropy double precision,
    avg_curvature double precision,
    avg_complexity double precision
);


--
-- Name: lineage_sankey_agg; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.lineage_sankey_agg (
    time_window text NOT NULL,
    window_start timestamp with time zone NOT NULL,
    source_namespace text NOT NULL,
    source_name text NOT NULL,
    target_namespace text NOT NULL,
    target_name text NOT NULL,
    via_job text DEFAULT ''::text NOT NULL,
    flow_count integer DEFAULT 1,
    bytes_transferred bigint DEFAULT 0,
    computed_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE lineage_sankey_agg; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.lineage_sankey_agg IS 'Pre-aggregated lineage edges for Sankey visualization in Metabase v52+';


--
-- Name: metaagent_audits; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.metaagent_audits (
    id integer NOT NULL,
    audit_id uuid DEFAULT gen_random_uuid() NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    scope text DEFAULT 'full'::text NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    summary text,
    findings jsonb DEFAULT '[]'::jsonb,
    tokens_used integer DEFAULT 0,
    provider text,
    kb_path text,
    duration_ms integer GENERATED ALWAYS AS (((EXTRACT(epoch FROM (completed_at - started_at)) * (1000)::numeric))::integer) STORED,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE metaagent_audits; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.metaagent_audits IS 'Weekly MetaAgent audit results with LLM analysis';


--
-- Name: metaagent_audits_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.metaagent_audits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: metaagent_audits_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.metaagent_audits_id_seq OWNED BY meta.metaagent_audits.id;


--
-- Name: metaagent_queries; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.metaagent_queries (
    query_hash text NOT NULL,
    query_text text NOT NULL,
    domains text[],
    answer text,
    dot_graph text,
    evidence jsonb DEFAULT '[]'::jsonb,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    cache_hits integer DEFAULT 0,
    last_hit_at timestamp with time zone
);


--
-- Name: TABLE metaagent_queries; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.metaagent_queries IS 'MetaAgent query result cache for expensive analytics queries';


--
-- Name: metabase_models; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.metabase_models (
    id integer NOT NULL,
    card_id integer NOT NULL,
    name text NOT NULL,
    source_table text NOT NULL,
    description text,
    display_type text DEFAULT 'table'::text,
    created_at timestamp with time zone DEFAULT now(),
    last_synced_at timestamp with time zone,
    sync_status text DEFAULT 'active'::text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE metabase_models; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.metabase_models IS 'Registry of Metabase models synced from meta.* schema';


--
-- Name: metabase_models_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.metabase_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: metabase_models_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.metabase_models_id_seq OWNED BY meta.metabase_models.id;


--
-- Name: metabase_sync_runs; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.metabase_sync_runs (
    id integer NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    full_refresh boolean DEFAULT false NOT NULL,
    models_synced integer DEFAULT 0,
    models_failed integer DEFAULT 0,
    dashboards_synced integer DEFAULT 0,
    dashboards_failed integer DEFAULT 0,
    error_message text,
    duration_ms integer GENERATED ALWAYS AS (((EXTRACT(epoch FROM (completed_at - started_at)) * (1000)::numeric))::integer) STORED
);


--
-- Name: TABLE metabase_sync_runs; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.metabase_sync_runs IS 'History of Metabase model/dashboard sync operations';


--
-- Name: metabase_sync_runs_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.metabase_sync_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: metabase_sync_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.metabase_sync_runs_id_seq OWNED BY meta.metabase_sync_runs.id;


--
-- Name: ngrc_models; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.ngrc_models (
    id integer NOT NULL,
    domain text NOT NULL,
    trained_at timestamp with time zone DEFAULT now(),
    n_training_snapshots integer,
    training_time_span_hours double precision,
    reservoir_size integer DEFAULT 500,
    spectral_radius double precision DEFAULT 0.9,
    input_scaling double precision DEFAULT 0.1,
    leaking_rate double precision DEFAULT 0.3,
    model_weights bytea,
    kb_modulation_weights bytea,
    validation_mse double precision,
    forecast_horizon_steps integer,
    stability_radius double precision,
    is_active boolean DEFAULT true
);


--
-- Name: TABLE ngrc_models; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.ngrc_models IS 'NG-RC models that learn dx/dt = f(x, KB(t)). Enables forward dynamics prediction without LLM calls.';


--
-- Name: COLUMN ngrc_models.kb_modulation_weights; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.ngrc_models.kb_modulation_weights IS 'Maps KB state to flow field modulation for non-autonomous dynamics: dx/dt = f(x, KB(t))';


--
-- Name: ngrc_models_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.ngrc_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ngrc_models_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.ngrc_models_id_seq OWNED BY meta.ngrc_models.id;


--
-- Name: nifi_flows; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.nifi_flows (
    id integer NOT NULL,
    flow_id text NOT NULL,
    flow_name text NOT NULL,
    process_group_id text,
    metaflow_name text,
    processor_count integer DEFAULT 0,
    connection_count integer DEFAULT 0,
    status text DEFAULT 'projected'::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: nifi_flows_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.nifi_flows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nifi_flows_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.nifi_flows_id_seq OWNED BY meta.nifi_flows.id;


--
-- Name: phase_change_profiles; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.phase_change_profiles (
    change_type text NOT NULL,
    sample_count integer DEFAULT 0 NOT NULL,
    total_duration_ms bigint DEFAULT 0 NOT NULL,
    min_duration_ms integer,
    max_duration_ms integer,
    failures integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE phase_change_profiles; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.phase_change_profiles IS 'Accumulated phase change timing statistics for decision support. Requires ~70 samples (~1 week baseline) before enabling threshold-based interventions.';


--
-- Name: COLUMN phase_change_profiles.change_type; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.change_type IS 'Phase change type: colnomic_load, instruct_restore, reasoning_load, baseline_restore';


--
-- Name: COLUMN phase_change_profiles.sample_count; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.sample_count IS 'Number of successful convergences';


--
-- Name: COLUMN phase_change_profiles.total_duration_ms; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.total_duration_ms IS 'Sum of all convergence durations in milliseconds';


--
-- Name: COLUMN phase_change_profiles.min_duration_ms; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.min_duration_ms IS 'Fastest recorded convergence in milliseconds';


--
-- Name: COLUMN phase_change_profiles.max_duration_ms; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.max_duration_ms IS 'Slowest recorded convergence in milliseconds';


--
-- Name: COLUMN phase_change_profiles.failures; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.phase_change_profiles.failures IS 'Count of failed phase change attempts';


--
-- Name: prospect_candidates; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.prospect_candidates (
    id integer NOT NULL,
    symbol character varying(16) NOT NULL,
    company_name character varying(255),
    exchange character varying(32),
    cik character varying(32),
    sector character varying(64),
    industry character varying(128),
    last_filing_date date,
    last_filing_type character varying(16),
    pending_filings integer DEFAULT 0,
    priority integer DEFAULT 2,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    active boolean DEFAULT true,
    archived_at timestamp with time zone
);


--
-- Name: TABLE prospect_candidates; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.prospect_candidates IS 'Prospect watchlist candidates from config/prospects/watchlist.conf';


--
-- Name: COLUMN prospect_candidates.cik; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_candidates.cik IS 'SEC Central Index Key for EDGAR filings';


--
-- Name: COLUMN prospect_candidates.pending_filings; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_candidates.pending_filings IS 'Count of new filings awaiting analysis';


--
-- Name: COLUMN prospect_candidates.active; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_candidates.active IS 'Whether symbol is in active watchlist config';


--
-- Name: COLUMN prospect_candidates.archived_at; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_candidates.archived_at IS 'When symbol was removed from config (soft archive)';


--
-- Name: prospect_candidates_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.prospect_candidates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prospect_candidates_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.prospect_candidates_id_seq OWNED BY meta.prospect_candidates.id;


--
-- Name: prospect_strategies; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.prospect_strategies (
    id integer NOT NULL,
    symbol character varying(16) NOT NULL,
    profile character varying(64) DEFAULT 'zndx'::character varying NOT NULL,
    domain character varying(64) DEFAULT 'prospecting'::character varying NOT NULL,
    category character varying(32) DEFAULT 'watch'::character varying,
    allocation_weight real DEFAULT 0.0,
    target_weight real DEFAULT 0.0,
    conviction real DEFAULT 0.0,
    last_analysis_at timestamp with time zone,
    needs_update boolean DEFAULT false,
    thesis text,
    risk_notes text,
    kb_artifact_path character varying(512),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE prospect_strategies; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.prospect_strategies IS 'Investment strategy state per candidate per profile/domain';


--
-- Name: COLUMN prospect_strategies.category; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_strategies.category IS 'Position lifecycle: watch → research → position → exit';


--
-- Name: COLUMN prospect_strategies.conviction; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.prospect_strategies.conviction IS 'LLM-derived conviction score (0-1)';


--
-- Name: prospect_strategies_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.prospect_strategies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prospect_strategies_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.prospect_strategies_id_seq OWNED BY meta.prospect_strategies.id;


--
-- Name: quality_assessments; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.quality_assessments (
    id integer NOT NULL,
    source_type text NOT NULL,
    source_id text NOT NULL,
    coherence_score real,
    coverage_score real,
    novelty_score real,
    weighted_reward real GENERATED ALWAYS AS (((((0.4)::double precision * COALESCE(coherence_score, (0)::real)) + ((0.35)::double precision * COALESCE(coverage_score, (0)::real))) + ((0.25)::double precision * COALESCE(novelty_score, (0)::real)))) STORED,
    is_textbook_quality boolean GENERATED ALWAYS AS ((((((0.4)::double precision * COALESCE(coherence_score, (0)::real)) + ((0.35)::double precision * COALESCE(coverage_score, (0)::real))) + ((0.25)::double precision * COALESCE(novelty_score, (0)::real))) >= (0.85)::double precision)) STORED,
    evaluator_type text NOT NULL,
    evaluation_model text,
    created_at timestamp with time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT quality_assessments_coherence_score_check CHECK (((coherence_score >= (0)::double precision) AND (coherence_score <= (1)::double precision))),
    CONSTRAINT quality_assessments_coverage_score_check CHECK (((coverage_score >= (0)::double precision) AND (coverage_score <= (1)::double precision))),
    CONSTRAINT quality_assessments_novelty_score_check CHECK (((novelty_score >= (0)::double precision) AND (novelty_score <= (1)::double precision)))
);


--
-- Name: TABLE quality_assessments; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.quality_assessments IS 'Quality scores for synthetic data (textbook quality = weighted_reward >= 0.85)';


--
-- Name: COLUMN quality_assessments.weighted_reward; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.quality_assessments.weighted_reward IS '0.4*coherence + 0.35*coverage + 0.25*novelty';


--
-- Name: quality_assessments_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.quality_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.quality_assessments_id_seq OWNED BY meta.quality_assessments.id;


--
-- Name: recent_agendas_summary; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.recent_agendas_summary AS
 SELECT workload_id AS agenda_id,
    (workload_type)::text AS agenda_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    current_phase_index,
    ((phases -> current_phase_index) ->> 'name'::text) AS current_phase_name,
    makespan_projection_ms,
    actual_duration_ms,
    makespan_variance_pct,
    0 AS severity_score,
    created_at,
    completed_at AS resolved_at,
    (EXTRACT(epoch FROM (COALESCE(completed_at, now()) - created_at)))::integer AS elapsed_seconds,
    jsonb_array_length(endpoint_transitions) AS transition_count,
    (escalated_to_incident_id IS NOT NULL) AS is_escalated
   FROM public.agenda_operations ao
  WHERE (created_at > (now() - '24:00:00'::interval))
  ORDER BY created_at DESC;


--
-- Name: VIEW recent_agendas_summary; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.recent_agendas_summary IS 'Last 24 hours of operations for Metabase real-time dashboard';


--
-- Name: research_progress; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.research_progress (
    event_id bigint NOT NULL,
    session_id text NOT NULL,
    event_type integer NOT NULL,
    event_name text NOT NULL,
    pass_number integer DEFAULT 0,
    progress real DEFAULT 0.0,
    message text DEFAULT ''::text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE research_progress; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.research_progress IS 'Fine-grained ResearchFlow progress events for TUI streaming';


--
-- Name: COLUMN research_progress.session_id; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.session_id IS 'Research session ID (e.g., res_20260114_070504)';


--
-- Name: COLUMN research_progress.event_type; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.event_type IS 'Event type enum (matches ResearchFlowEvent.Type proto)';


--
-- Name: COLUMN research_progress.event_name; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.event_name IS 'Human-readable event name (e.g., pass_search, converged)';


--
-- Name: COLUMN research_progress.pass_number; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.pass_number IS 'Current pass number (1-indexed, 0 for non-pass events)';


--
-- Name: COLUMN research_progress.progress; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.progress IS 'Progress 0.0-1.0 for progress bar display';


--
-- Name: COLUMN research_progress.metadata; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_progress.metadata IS 'Additional event data (q_value, sources_count, etc.)';


--
-- Name: research_progress_event_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.research_progress_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_progress_event_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.research_progress_event_id_seq OWNED BY meta.research_progress.event_id;


--
-- Name: research_state; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.research_state (
    session_id text NOT NULL,
    query text NOT NULL,
    pass_number integer DEFAULT 0 NOT NULL,
    converged boolean DEFAULT false NOT NULL,
    convergence_reason text DEFAULT ''::text,
    q_value real DEFAULT 0.5,
    reward_components jsonb DEFAULT '{}'::jsonb,
    timing jsonb DEFAULT '{}'::jsonb,
    tracker_state jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE research_state; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.research_state IS 'Research session state for engine-coordinated multi-pass';


--
-- Name: COLUMN research_state.session_id; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.session_id IS 'Unique session ID (e.g., res_20260114_070504)';


--
-- Name: COLUMN research_state.query; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.query IS 'Research query string';


--
-- Name: COLUMN research_state.pass_number; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.pass_number IS 'Current pass number (1-indexed)';


--
-- Name: COLUMN research_state.converged; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.converged IS 'True if research has converged';


--
-- Name: COLUMN research_state.convergence_reason; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.convergence_reason IS 'Reason for convergence (e.g., drift_converged:0.05)';


--
-- Name: COLUMN research_state.tracker_state; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.research_state.tracker_state IS 'Serialized ConvergenceTracker state';


--
-- Name: sec_filings_cache; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.sec_filings_cache (
    id integer NOT NULL,
    symbol character varying(16) NOT NULL,
    filing_type character varying(16) NOT NULL,
    filing_date date NOT NULL,
    accepted_date timestamp with time zone,
    cik character varying(32),
    accession_number character varying(32),
    final_link text,
    filing_hash character varying(64),
    analyzed_at timestamp with time zone,
    analysis_model character varying(64),
    analysis_result jsonb,
    iceberg_exchange_id uuid,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE sec_filings_cache; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.sec_filings_cache IS 'Cached SEC filings from FMP with analysis status';


--
-- Name: COLUMN sec_filings_cache.iceberg_exchange_id; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.sec_filings_cache.iceberg_exchange_id IS 'Reference to raw.fmp_exchange Iceberg record';


--
-- Name: sec_filings_cache_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.sec_filings_cache_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sec_filings_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.sec_filings_cache_id_seq OWNED BY meta.sec_filings_cache.id;


--
-- Name: semantic_attractors; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.semantic_attractors (
    id integer NOT NULL,
    domain text NOT NULL,
    name text NOT NULL,
    description text,
    current_embedding double precision[],
    current_grid_x integer,
    current_grid_y integer,
    last_observed timestamp with time zone DEFAULT now(),
    position_history jsonb,
    mean_well_depth double precision,
    total_drift_distance double precision,
    first_observed timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    merged_into_id integer,
    split_from_id integer
);


--
-- Name: TABLE semantic_attractors; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.semantic_attractors IS 'Named stable states in semantic space. Tracks ontological drift as meanings evolve.';


--
-- Name: semantic_attractors_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.semantic_attractors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: semantic_attractors_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.semantic_attractors_id_seq OWNED BY meta.semantic_attractors.id;


--
-- Name: semantic_regions; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.semantic_regions (
    region_id integer NOT NULL,
    name text,
    grid_bounds jsonb,
    document_paths text[],
    dominant_topics text[],
    boundary_curvature double precision,
    computed_at timestamp with time zone
);


--
-- Name: semantic_regions_region_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.semantic_regions_region_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: semantic_regions_region_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.semantic_regions_region_id_seq OWNED BY meta.semantic_regions.region_id;


--
-- Name: swarm_agent_positions; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.swarm_agent_positions (
    id integer NOT NULL,
    snapshot_id integer NOT NULL,
    agent_role text NOT NULL,
    embedding double precision[],
    grid_x integer,
    grid_y integer,
    top_features jsonb,
    distance_from_consensus double precision,
    trace_history jsonb,
    CONSTRAINT valid_agent_grid_x CHECK (((grid_x >= 0) AND (grid_x <= 18))),
    CONSTRAINT valid_agent_grid_y CHECK (((grid_y >= 0) AND (grid_y <= 18)))
);


--
-- Name: TABLE swarm_agent_positions; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.swarm_agent_positions IS 'Individual agent positions within a swarm snapshot. Captures CLT embeddings and grid positions.';


--
-- Name: swarm_agent_positions_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.swarm_agent_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: swarm_agent_positions_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.swarm_agent_positions_id_seq OWNED BY meta.swarm_agent_positions.id;


--
-- Name: swarm_snapshots; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.swarm_snapshots (
    snapshot_id integer NOT NULL,
    run_id uuid NOT NULL,
    domain text NOT NULL,
    captured_at timestamp with time zone DEFAULT now(),
    kb_version text,
    kb_document_count integer,
    kb_last_modified timestamp with time zone,
    consensus_embedding double precision[],
    consensus_variance double precision,
    consensus_grid_x integer,
    consensus_grid_y integer,
    h0_count integer,
    h1_count integer,
    position_entropy double precision,
    feature_entropy double precision,
    n_agents integer,
    query_text text,
    CONSTRAINT valid_grid_x CHECK (((consensus_grid_x >= 0) AND (consensus_grid_x <= 18))),
    CONSTRAINT valid_grid_y CHECK (((consensus_grid_y >= 0) AND (consensus_grid_y <= 18)))
);


--
-- Name: TABLE swarm_snapshots; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.swarm_snapshots IS 'Point-in-time capture of swarm state. Each run is a snapshot of a living topology.';


--
-- Name: swarm_snapshots_snapshot_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.swarm_snapshots_snapshot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: swarm_snapshots_snapshot_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.swarm_snapshots_snapshot_id_seq OWNED BY meta.swarm_snapshots.snapshot_id;


--
-- Name: sync_watermarks; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.sync_watermarks (
    sync_type text NOT NULL,
    last_sync_at timestamp with time zone,
    last_event_id bigint,
    records_synced integer DEFAULT 0
);


--
-- Name: topology_drift; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.topology_drift (
    id integer NOT NULL,
    domain text NOT NULL,
    computed_at timestamp with time zone DEFAULT now(),
    time_window_hours integer DEFAULT 24,
    n_snapshots integer,
    centroid_drift_velocity double precision[],
    drift_magnitude double precision,
    drift_direction_grid_x double precision,
    drift_direction_grid_y double precision,
    well_depth double precision,
    lyapunov_exponent double precision,
    mean_variance double precision,
    variance_trend double precision,
    kb_growth_rate double precision,
    kb_modification_rate double precision,
    drift_anomaly_score double precision,
    is_bifurcation boolean DEFAULT false
);


--
-- Name: TABLE topology_drift; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TABLE meta.topology_drift IS 'Tracks how consensus positions change over time. Enables drift detection and well-depth measurement.';


--
-- Name: COLUMN topology_drift.well_depth; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.topology_drift.well_depth IS '1/variance - measures entrenchment. High = deep well = stable but potentially stuck.';


--
-- Name: COLUMN topology_drift.lyapunov_exponent; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON COLUMN meta.topology_drift.lyapunov_exponent IS 'Negative = stable attractor, positive = chaotic/unstable, near-zero = edge of chaos.';


--
-- Name: topology_drift_id_seq; Type: SEQUENCE; Schema: meta; Owner: -
--

CREATE SEQUENCE meta.topology_drift_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: topology_drift_id_seq; Type: SEQUENCE OWNED BY; Schema: meta; Owner: -
--

ALTER SEQUENCE meta.topology_drift_id_seq OWNED BY meta.topology_drift.id;


--
-- Name: fmea_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fmea_catalog (
    failure_mode_id character varying(32) NOT NULL,
    category character varying(32) NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    base_severity integer NOT NULL,
    base_occurrence integer NOT NULL,
    base_detection integer NOT NULL,
    detection_method character varying(64),
    detection_query text,
    detection_threshold jsonb DEFAULT '{}'::jsonb,
    recommended_actions text[],
    escalation_tier integer DEFAULT 0,
    preventive_controls text[],
    detective_controls text[],
    mitigative_controls text[],
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT fmea_catalog_base_detection_check CHECK (((base_detection >= 1) AND (base_detection <= 10))),
    CONSTRAINT fmea_catalog_base_occurrence_check CHECK (((base_occurrence >= 1) AND (base_occurrence <= 10))),
    CONSTRAINT fmea_catalog_base_severity_check CHECK (((base_severity >= 1) AND (base_severity <= 10)))
);


--
-- Name: TABLE fmea_catalog; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fmea_catalog IS 'FMEA failure mode definitions with S/O/D scores';


--
-- Name: COLUMN fmea_catalog.failure_mode_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fmea_catalog.failure_mode_id IS 'Unique ID: GPU_001, VLLM_002, MQ_003, etc.';


--
-- Name: COLUMN fmea_catalog.base_severity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fmea_catalog.base_severity IS 'Severity score 1-10: impact on system availability';


--
-- Name: COLUMN fmea_catalog.base_occurrence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fmea_catalog.base_occurrence IS 'Occurrence score 1-10: probability of recurrence';


--
-- Name: COLUMN fmea_catalog.base_detection; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fmea_catalog.base_detection IS 'Detection score 1-10: ability to detect before impact (1=certain, 10=none)';


--
-- Name: healing_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.healing_events (
    id bigint NOT NULL,
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    sequence_id uuid NOT NULL,
    sequence_num integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_type character varying(32) NOT NULL,
    endpoint character varying(64) NOT NULL,
    tier integer NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    aiops_event_id integer,
    failure_mode_id character varying(32)
);


--
-- Name: TABLE healing_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.healing_events IS 'Event-sourced audit log for self-healing attempts - append only';


--
-- Name: COLUMN healing_events.sequence_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.healing_events.sequence_id IS 'Groups all events for one healing sequence (issue detection through resolution)';


--
-- Name: COLUMN healing_events.sequence_num; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.healing_events.sequence_num IS 'Order within sequence, auto-incremented per sequence';


--
-- Name: COLUMN healing_events.event_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.healing_events.event_type IS 'Event classification: sequence_started/completed, tier_entered/exhausted, attempt_started/succeeded/failed, cooldown_started/cleared, circuit_breaker_tripped/reset';


--
-- Name: COLUMN healing_events.payload; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.healing_events.payload IS 'Event-specific data varying by event_type';


--
-- Name: v_incident_lifecycle; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_incident_lifecycle AS
 WITH sequence_bounds AS (
         SELECT healing_events.sequence_id,
            min(healing_events.created_at) FILTER (WHERE ((healing_events.event_type)::text = 'sequence_started'::text)) AS started_at,
            max(healing_events.created_at) FILTER (WHERE ((healing_events.event_type)::text = 'sequence_completed'::text)) AS completed_at,
            max(
                CASE
                    WHEN ((healing_events.event_type)::text = 'sequence_completed'::text) THEN (healing_events.payload ->> 'outcome'::text)
                    ELSE NULL::text
                END) AS outcome,
            max(
                CASE
                    WHEN ((healing_events.event_type)::text = 'sequence_completed'::text) THEN healing_events.tier
                    ELSE NULL::integer
                END) AS final_tier,
            max((healing_events.endpoint)::text) AS endpoint,
            max((healing_events.failure_mode_id)::text) AS failure_mode_id,
            count(*) AS event_count
           FROM public.healing_events
          WHERE (healing_events.created_at > (now() - '30 days'::interval))
          GROUP BY healing_events.sequence_id
        )
 SELECT s.sequence_id,
    s.started_at,
    s.completed_at,
    s.outcome,
    s.final_tier,
    s.endpoint,
    s.failure_mode_id,
    c.category,
    c.name AS failure_name,
    s.event_count,
    (EXTRACT(epoch FROM (s.completed_at - s.started_at)) * (1000)::numeric) AS duration_ms,
        CASE
            WHEN (s.completed_at IS NULL) THEN 'active'::text
            WHEN (s.outcome = 'success'::text) THEN 'resolved'::text
            WHEN (s.outcome = 'failure'::text) THEN 'failed'::text
            ELSE 'escalated'::text
        END AS status,
        CASE
            WHEN (s.final_tier <= 2) THEN true
            ELSE false
        END AS auto_resolved
   FROM (sequence_bounds s
     LEFT JOIN public.fmea_catalog c ON ((s.failure_mode_id = (c.failure_mode_id)::text)));


--
-- Name: VIEW v_incident_lifecycle; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_incident_lifecycle IS 'Incident lifecycle from detection to resolution for Metabase';


--
-- Name: v_autonomous_healing_summary; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_autonomous_healing_summary AS
 SELECT date_trunc('day'::text, started_at) AS day,
    count(*) AS total_incidents,
    count(*) FILTER (WHERE (status = 'resolved'::text)) AS resolved,
    count(*) FILTER (WHERE (status = 'active'::text)) AS active,
    count(*) FILTER (WHERE ((status = 'escalated'::text) OR (status = 'failed'::text))) AS escalated,
    count(*) FILTER (WHERE auto_resolved) AS auto_resolved,
    round(((100.0 * (count(*) FILTER (WHERE auto_resolved))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS auto_rate_pct,
    avg(duration_ms) FILTER (WHERE (status = 'resolved'::text)) AS avg_resolution_ms,
    percentile_cont((0.50)::double precision) WITHIN GROUP (ORDER BY ((duration_ms)::double precision)) FILTER (WHERE (status = 'resolved'::text)) AS p50_resolution_ms
   FROM meta.v_incident_lifecycle
  WHERE (started_at > (now() - '30 days'::interval))
  GROUP BY (date_trunc('day'::text, started_at))
  ORDER BY (date_trunc('day'::text, started_at)) DESC;


--
-- Name: VIEW v_autonomous_healing_summary; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_autonomous_healing_summary IS 'Daily autonomous healing summary for Metabase dashboards';


--
-- Name: v_budget_status; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_budget_status AS
 SELECT pool_id,
    weekly_limit,
    weekly_used,
    (weekly_limit - weekly_used) AS weekly_remaining,
    grok_calls,
    cerebras_calls,
    round((((weekly_used)::numeric / (NULLIF(weekly_limit, 0))::numeric) * (100)::numeric), 1) AS usage_pct,
    week_start,
    last_reset,
        CASE
            WHEN (weekly_used >= weekly_limit) THEN 'exhausted'::text
            WHEN ((weekly_used)::numeric >= ((weekly_limit)::numeric * 0.8)) THEN 'low'::text
            WHEN ((weekly_used)::numeric >= ((weekly_limit)::numeric * 0.5)) THEN 'moderate'::text
            ELSE 'healthy'::text
        END AS budget_health
   FROM meta.audit_budget_pool;


--
-- Name: VIEW v_budget_status; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_budget_status IS 'Current pooled budget status for Metabase dashboard';


--
-- Name: fmea_outcomes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fmea_outcomes (
    id integer NOT NULL,
    failure_mode_id character varying(32) NOT NULL,
    aiops_event_id integer,
    mlops_event_id integer,
    rpn_score integer NOT NULL,
    severity integer NOT NULL,
    occurrence integer NOT NULL,
    detection integer NOT NULL,
    action_taken character varying(128),
    tier_used integer,
    success boolean NOT NULL,
    duration_ms integer,
    downtime_seconds integer,
    sla_breach boolean DEFAULT false,
    detection_lead_time_seconds integer,
    detected_by character varying(32),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE fmea_outcomes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fmea_outcomes IS 'Remediation outcomes for adaptive S/O/D learning';


--
-- Name: v_fmea_remediation_effectiveness; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_fmea_remediation_effectiveness AS
 SELECT o.failure_mode_id,
    c.category,
    c.name AS failure_name,
    o.action_taken,
    o.tier_used,
    count(*) AS attempts,
    sum(
        CASE
            WHEN o.success THEN 1
            ELSE 0
        END) AS successes,
    sum(
        CASE
            WHEN (NOT o.success) THEN 1
            ELSE 0
        END) AS failures,
    round(((100.0 * (sum(
        CASE
            WHEN o.success THEN 1
            ELSE 0
        END))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS success_rate_pct,
    avg(o.duration_ms) AS avg_duration_ms,
    percentile_cont((0.95)::double precision) WITHIN GROUP (ORDER BY ((o.duration_ms)::double precision)) AS p95_duration_ms,
    avg(o.downtime_seconds) AS avg_downtime_seconds,
    sum(
        CASE
            WHEN o.sla_breach THEN 1
            ELSE 0
        END) AS sla_breaches
   FROM (public.fmea_outcomes o
     JOIN public.fmea_catalog c ON (((o.failure_mode_id)::text = (c.failure_mode_id)::text)))
  WHERE (o.created_at > (now() - '30 days'::interval))
  GROUP BY o.failure_mode_id, c.category, c.name, o.action_taken, o.tier_used;


--
-- Name: VIEW v_fmea_remediation_effectiveness; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_fmea_remediation_effectiveness IS 'Remediation strategy effectiveness metrics for FMEA in Metabase';


--
-- Name: fmea_occurrences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fmea_occurrences (
    id integer NOT NULL,
    failure_mode_id character varying(32) NOT NULL,
    occurred_at timestamp with time zone DEFAULT now(),
    endpoint character varying(64),
    context jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE fmea_occurrences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fmea_occurrences IS 'History of failure mode occurrences for calculating O score';


--
-- Name: v_fmea_risk_heatmap; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_fmea_risk_heatmap AS
 WITH recent_rpn AS (
         SELECT DISTINCT ON (fmea_outcomes.failure_mode_id) fmea_outcomes.failure_mode_id,
            fmea_outcomes.rpn_score AS last_rpn,
            fmea_outcomes.severity AS last_s,
            fmea_outcomes.occurrence AS last_o,
            fmea_outcomes.detection AS last_d,
            fmea_outcomes.created_at AS last_occurrence_at
           FROM public.fmea_outcomes
          ORDER BY fmea_outcomes.failure_mode_id, fmea_outcomes.created_at DESC
        ), occurrence_stats AS (
         SELECT fmea_occurrences.failure_mode_id,
            count(*) FILTER (WHERE (fmea_occurrences.occurred_at > (now() - '24:00:00'::interval))) AS occurrences_24h,
            count(*) FILTER (WHERE (fmea_occurrences.occurred_at > (now() - '7 days'::interval))) AS occurrences_7d,
            count(*) AS total_occurrences
           FROM public.fmea_occurrences
          GROUP BY fmea_occurrences.failure_mode_id
        )
 SELECT c.failure_mode_id,
    c.category,
    c.name,
    c.description,
    c.base_severity,
    c.base_occurrence,
    c.base_detection,
    ((c.base_severity * c.base_occurrence) * c.base_detection) AS base_rpn,
    COALESCE(r.last_rpn, ((c.base_severity * c.base_occurrence) * c.base_detection)) AS current_rpn,
    r.last_s AS current_severity,
    r.last_o AS current_occurrence,
    r.last_d AS current_detection,
    COALESCE(os.occurrences_24h, (0)::bigint) AS occurrences_24h,
    COALESCE(os.occurrences_7d, (0)::bigint) AS occurrences_7d,
    COALESCE(os.total_occurrences, (0)::bigint) AS total_occurrences,
    r.last_occurrence_at,
        CASE
            WHEN (COALESCE(r.last_rpn, ((c.base_severity * c.base_occurrence) * c.base_detection)) <= 100) THEN 'TIER_0'::text
            WHEN (COALESCE(r.last_rpn, ((c.base_severity * c.base_occurrence) * c.base_detection)) <= 200) THEN 'TIER_1'::text
            WHEN (COALESCE(r.last_rpn, ((c.base_severity * c.base_occurrence) * c.base_detection)) <= 400) THEN 'TIER_2'::text
            ELSE 'MANUAL'::text
        END AS risk_tier,
    c.escalation_tier,
    c.recommended_actions
   FROM ((public.fmea_catalog c
     LEFT JOIN recent_rpn r ON (((c.failure_mode_id)::text = (r.failure_mode_id)::text)))
     LEFT JOIN occurrence_stats os ON (((c.failure_mode_id)::text = (os.failure_mode_id)::text)));


--
-- Name: VIEW v_fmea_risk_heatmap; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_fmea_risk_heatmap IS 'FMEA risk heatmap showing current RPN scores, occurrence stats, and risk tiers for Metabase';


--
-- Name: v_mttr_metrics; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_mttr_metrics AS
 SELECT c.category,
    i.failure_mode_id,
    c.name AS failure_name,
    i.final_tier,
    count(*) AS incident_count,
    count(*) FILTER (WHERE (i.status = 'resolved'::text)) AS resolved_count,
    count(*) FILTER (WHERE (i.status = 'active'::text)) AS active_count,
    avg(i.duration_ms) FILTER (WHERE (i.status = 'resolved'::text)) AS avg_mttr_ms,
    percentile_cont((0.50)::double precision) WITHIN GROUP (ORDER BY ((i.duration_ms)::double precision)) FILTER (WHERE (i.status = 'resolved'::text)) AS p50_mttr_ms,
    percentile_cont((0.95)::double precision) WITHIN GROUP (ORDER BY ((i.duration_ms)::double precision)) FILTER (WHERE (i.status = 'resolved'::text)) AS p95_mttr_ms,
    min(i.duration_ms) FILTER (WHERE (i.status = 'resolved'::text)) AS min_mttr_ms,
    max(i.duration_ms) FILTER (WHERE (i.status = 'resolved'::text)) AS max_mttr_ms
   FROM (meta.v_incident_lifecycle i
     LEFT JOIN public.fmea_catalog c ON ((i.failure_mode_id = (c.failure_mode_id)::text)))
  WHERE (i.started_at > (now() - '30 days'::interval))
  GROUP BY c.category, i.failure_mode_id, c.name, i.final_tier;


--
-- Name: VIEW v_mttr_metrics; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_mttr_metrics IS 'Mean Time To Resolve metrics by failure mode and tier for Metabase';


--
-- Name: v_phase_change_stats; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_phase_change_stats AS
 SELECT change_type,
    sample_count,
    failures,
        CASE
            WHEN (sample_count > 0) THEN round(((total_duration_ms)::numeric / (sample_count)::numeric), 1)
            ELSE NULL::numeric
        END AS avg_duration_ms,
    min_duration_ms,
    max_duration_ms,
        CASE
            WHEN ((sample_count + failures) > 0) THEN round((((failures)::numeric / ((sample_count + failures))::numeric) * (100)::numeric), 2)
            ELSE (0)::numeric
        END AS failure_rate_pct,
    (sample_count >= 70) AS has_statistical_power,
    updated_at
   FROM meta.phase_change_profiles
  ORDER BY change_type;


--
-- Name: VIEW v_phase_change_stats; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_phase_change_stats IS 'Phase change profiles with computed statistics. has_statistical_power indicates whether sufficient samples exist for decision support.';


--
-- Name: content_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_items (
    id integer NOT NULL,
    source_id integer,
    external_id text,
    url text,
    title text NOT NULL,
    authors text[],
    summary text,
    content_type text DEFAULT 'text/plain'::text,
    metadata jsonb DEFAULT '{}'::jsonb,
    published_at timestamp with time zone,
    fetched_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone,
    kb_path text,
    embedding_id text,
    iceberg_id text,
    iceberg_snapshot_id bigint,
    summarized_at timestamp with time zone,
    summary_kb_path text,
    summary_excluded boolean DEFAULT false,
    exclusion_reason text,
    heuristic_score integer,
    llm_quality_score integer,
    content_hash text
);


--
-- Name: TABLE content_items; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.content_items IS 'Content metadata (PostgreSQL) - raw content stored in Iceberg via iceberg_id link.
See gaius.hx module for Iceberg access.';


--
-- Name: COLUMN content_items.iceberg_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.iceberg_id IS 'UUID linking to raw.content table in Iceberg data lake (gaius.hx)';


--
-- Name: COLUMN content_items.iceberg_snapshot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.iceberg_snapshot_id IS 'Iceberg snapshot ID when content was written, for time-travel queries';


--
-- Name: COLUMN content_items.summarized_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.summarized_at IS 'When this content was summarized to KB';


--
-- Name: COLUMN content_items.summary_kb_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.summary_kb_path IS 'KB path where summary was written';


--
-- Name: COLUMN content_items.summary_excluded; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.summary_excluded IS 'Whether content was excluded from summarization';


--
-- Name: COLUMN content_items.exclusion_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.exclusion_reason IS 'Why content was excluded (quality, relevance, etc.)';


--
-- Name: v_pipeline_funnel; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_pipeline_funnel AS
 SELECT date_trunc('day'::text, fetched_at) AS day,
    count(*) AS fetched,
    count(*) FILTER (WHERE (heuristic_score IS NOT NULL)) AS scored_heuristic,
    count(*) FILTER (WHERE (heuristic_score >= 30)) AS passed_heuristic,
    count(*) FILTER (WHERE (llm_quality_score IS NOT NULL)) AS scored_llm,
    count(*) FILTER (WHERE (llm_quality_score >= 50)) AS passed_llm,
    count(*) FILTER (WHERE (processed_at IS NOT NULL)) AS written_to_kb,
    count(*) FILTER (WHERE (summary_excluded = true)) AS excluded,
    round(((100.0 * (count(*) FILTER (WHERE (heuristic_score >= 30)))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS heuristic_yield_pct,
    round(((100.0 * (count(*) FILTER (WHERE (llm_quality_score >= 50)))::numeric) / (NULLIF(count(*) FILTER (WHERE (heuristic_score >= 30)), 0))::numeric), 1) AS llm_yield_pct,
    round(((100.0 * (count(*) FILTER (WHERE (processed_at IS NOT NULL)))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS total_yield_pct
   FROM public.content_items
  WHERE (fetched_at > (now() - '30 days'::interval))
  GROUP BY (date_trunc('day'::text, fetched_at))
  ORDER BY (date_trunc('day'::text, fetched_at)) DESC;


--
-- Name: VIEW v_pipeline_funnel; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_pipeline_funnel IS 'Content pipeline conversion funnel with daily yields for Metabase';


--
-- Name: fetch_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fetch_jobs (
    id integer NOT NULL,
    source_id integer,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    status text DEFAULT 'running'::text,
    items_fetched integer DEFAULT 0,
    items_new integer DEFAULT 0,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: v_pipeline_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_pipeline_status AS
 SELECT 'fetch'::text AS stage,
    count(*) FILTER (WHERE (fetch_jobs.status = 'pending'::text)) AS pending,
    count(*) FILTER (WHERE ((fetch_jobs.status = 'completed'::text) AND (fetch_jobs.completed_at > (now() - '01:00:00'::interval)))) AS completed_1h,
    0 AS backlog_warn,
    100 AS backlog_critical
   FROM public.fetch_jobs
UNION ALL
 SELECT 'heuristic_triage'::text AS stage,
    count(*) FILTER (WHERE (content_items.heuristic_score IS NULL)) AS pending,
    count(*) FILTER (WHERE ((content_items.heuristic_score IS NOT NULL) AND (content_items.fetched_at > (now() - '01:00:00'::interval)))) AS completed_1h,
    200 AS backlog_warn,
    500 AS backlog_critical
   FROM public.content_items
UNION ALL
 SELECT 'llm_triage'::text AS stage,
    count(*) FILTER (WHERE ((content_items.heuristic_score >= 30) AND (content_items.llm_quality_score IS NULL) AND (NOT COALESCE(content_items.summary_excluded, false)))) AS pending,
    count(*) FILTER (WHERE ((content_items.llm_quality_score IS NOT NULL) AND (content_items.fetched_at > (now() - '01:00:00'::interval)))) AS completed_1h,
    100 AS backlog_warn,
    300 AS backlog_critical
   FROM public.content_items
UNION ALL
 SELECT 'kb_write'::text AS stage,
    count(*) FILTER (WHERE ((content_items.llm_quality_score >= 50) AND (content_items.processed_at IS NULL) AND (NOT COALESCE(content_items.summary_excluded, false)))) AS pending,
    count(*) FILTER (WHERE ((content_items.processed_at IS NOT NULL) AND (content_items.processed_at > (now() - '01:00:00'::interval)))) AS completed_1h,
    50 AS backlog_warn,
    150 AS backlog_critical
   FROM public.content_items;


--
-- Name: v_pipeline_health; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_pipeline_health AS
 SELECT stage,
    pending,
    completed_1h,
    backlog_warn,
    backlog_critical,
        CASE
            WHEN (pending >= backlog_critical) THEN 'critical'::text
            WHEN (pending >= backlog_warn) THEN 'warning'::text
            ELSE 'healthy'::text
        END AS health_status,
        CASE
            WHEN (pending >= backlog_critical) THEN 3
            WHEN (pending >= backlog_warn) THEN 2
            ELSE 1
        END AS health_level,
    round(((100.0 * (completed_1h)::numeric) / (NULLIF((pending + completed_1h), 0))::numeric), 1) AS throughput_pct
   FROM public.v_pipeline_status ps;


--
-- Name: VIEW v_pipeline_health; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_pipeline_health IS 'Pipeline health status with severity levels for Metabase';


--
-- Name: v_prospects_status; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_prospects_status AS
 SELECT c.symbol,
    c.company_name,
    c.exchange,
    c.priority,
    c.pending_filings,
    c.last_filing_date,
    c.last_filing_type,
    c.active,
    c.archived_at,
    s.category,
    s.conviction,
    s.allocation_weight,
    s.target_weight,
    s.last_analysis_at,
    s.needs_update,
    s.profile,
    s.domain,
    ( SELECT count(*) AS count
           FROM meta.sec_filings_cache f
          WHERE ((f.symbol)::text = (c.symbol)::text)) AS total_filings,
    ( SELECT count(*) AS count
           FROM meta.institutional_holders_cache h
          WHERE ((h.symbol)::text = (c.symbol)::text)) AS holder_count,
    meta.prospect_needs_update(c.symbol) AS update_recommended
   FROM (meta.prospect_candidates c
     LEFT JOIN meta.prospect_strategies s ON (((s.symbol)::text = (c.symbol)::text)))
  WHERE (c.active = true)
  ORDER BY c.priority, c.symbol;


--
-- Name: VIEW v_prospects_status; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_prospects_status IS 'Consolidated prospects status for active candidates only';


--
-- Name: v_quality_summary; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_quality_summary AS
 SELECT source_type,
    count(*) AS total_assessments,
    count(*) FILTER (WHERE is_textbook_quality) AS textbook_quality_count,
    round((avg(coherence_score))::numeric, 3) AS avg_coherence,
    round((avg(coverage_score))::numeric, 3) AS avg_coverage,
    round((avg(novelty_score))::numeric, 3) AS avg_novelty,
    round((avg(weighted_reward))::numeric, 3) AS avg_weighted_reward,
    round((((count(*) FILTER (WHERE is_textbook_quality))::numeric / (NULLIF(count(*), 0))::numeric) * (100)::numeric), 1) AS textbook_quality_pct
   FROM meta.quality_assessments
  GROUP BY source_type;


--
-- Name: VIEW v_quality_summary; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_quality_summary IS 'Aggregated quality metrics by source type';


--
-- Name: v_recent_audits; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_recent_audits AS
 SELECT audit_id,
    started_at,
    completed_at,
    scope,
    status,
    provider,
    tokens_used,
    duration_ms,
    kb_path,
    COALESCE(jsonb_array_length(findings), 0) AS findings_count,
    ( SELECT count(*) AS count
           FROM meta.audit_recommendations r
          WHERE (r.audit_id = a.audit_id)) AS recommendations_count
   FROM meta.metaagent_audits a
  ORDER BY started_at DESC
 LIMIT 20;


--
-- Name: VIEW v_recent_audits; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_recent_audits IS 'Recent audit runs with finding/recommendation counts';


--
-- Name: v_recommendation_funnel; Type: VIEW; Schema: meta; Owner: -
--

CREATE VIEW meta.v_recommendation_funnel AS
 SELECT status,
    count(*) AS count,
    array_agg(DISTINCT category) AS categories,
    array_agg(DISTINCT severity) AS severities
   FROM meta.audit_recommendations
  GROUP BY status
  ORDER BY
        CASE status
            WHEN 'pending'::text THEN 1
            WHEN 'accepted'::text THEN 2
            WHEN 'implemented'::text THEN 3
            WHEN 'verified'::text THEN 4
            WHEN 'rejected'::text THEN 5
            ELSE NULL::integer
        END;


--
-- Name: VIEW v_recommendation_funnel; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON VIEW meta.v_recommendation_funnel IS 'Recommendation status funnel for self-improvement tracking';


--
-- Name: action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    type text NOT NULL,
    model_id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    parameters text,
    parameter_mappings text,
    visualization_settings text,
    public_uuid character(36),
    made_public_by_id integer,
    creator_id integer,
    archived boolean DEFAULT false NOT NULL,
    entity_id character(21)
);


--
-- Name: TABLE action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.action IS 'An action is something you can do, such as run a readwrite query';


--
-- Name: COLUMN action.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.created_at IS 'The timestamp of when the action was created';


--
-- Name: COLUMN action.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.updated_at IS 'The timestamp of when the action was updated';


--
-- Name: COLUMN action.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.type IS 'Type of action';


--
-- Name: COLUMN action.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.model_id IS 'The associated model';


--
-- Name: COLUMN action.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.name IS 'The name of the action';


--
-- Name: COLUMN action.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.description IS 'The description of the action';


--
-- Name: COLUMN action.parameters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.parameters IS 'The saved parameters for this action';


--
-- Name: COLUMN action.parameter_mappings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.parameter_mappings IS 'The saved parameter mappings for this action';


--
-- Name: COLUMN action.visualization_settings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.visualization_settings IS 'The UI visualization_settings for this action';


--
-- Name: COLUMN action.public_uuid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.public_uuid IS 'Unique UUID used to in publically-accessible links to this Action.';


--
-- Name: COLUMN action.made_public_by_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.made_public_by_id IS 'The ID of the User who first publically shared this Action.';


--
-- Name: COLUMN action.creator_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.creator_id IS 'The user who created the action';


--
-- Name: COLUMN action.archived; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.archived IS 'Whether or not the action has been archived';


--
-- Name: COLUMN action.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.action.entity_id IS 'Random NanoID tag for unique identity.';


--
-- Name: action_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.action ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.action_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: active_agendas; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.active_agendas AS
 SELECT incident_id,
    agenda_id,
    (agenda_type)::text AS agenda_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    current_phase_index,
    ((phases -> current_phase_index) ->> 'name'::text) AS current_phase_name,
    makespan_projection_ms,
    actual_duration_ms,
    makespan_variance_pct,
    severity_score,
    created_at,
    baseline_departed_at,
    escalation_reason,
    acp_escalated,
    (now() - created_at) AS elapsed
   FROM public.agenda_incidents ai
  WHERE (status <> ALL (ARRAY['fulfilled'::public.agenda_status, 'failed'::public.agenda_status, 'degraded'::public.agenda_status]));


--
-- Name: agent_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_versions (
    version_id text NOT NULL,
    agent_id text NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    created_by text DEFAULT 'system'::text,
    parent_version text,
    is_active boolean DEFAULT false,
    metrics jsonb DEFAULT '{}'::jsonb,
    evaluation_count integer DEFAULT 0,
    avg_overall_score double precision DEFAULT 0.0,
    best_overall_score double precision DEFAULT 0.0,
    change_notes text DEFAULT ''::text
);


--
-- Name: active_agent_configs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.active_agent_configs AS
 SELECT agent_id,
    version_id,
    config,
    avg_overall_score,
    evaluation_count,
    created_at
   FROM public.agent_versions
  WHERE (is_active = true);


--
-- Name: active_operations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.active_operations AS
 SELECT operation_id,
    workload_id,
    (workload_type)::text AS workload_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    current_phase_index,
    ((phases -> current_phase_index) ->> 'name'::text) AS current_phase_name,
    makespan_projection_ms,
    actual_duration_ms,
    makespan_variance_pct,
    created_at,
    started_at,
    (now() - created_at) AS elapsed,
    (escalated_to_incident_id IS NOT NULL) AS is_escalated
   FROM public.agenda_operations ao
  WHERE (status <> ALL (ARRAY['fulfilled'::public.agenda_status, 'failed'::public.agenda_status, 'degraded'::public.agenda_status]));


--
-- Name: VIEW active_operations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.active_operations IS 'Currently active workload operations';


--
-- Name: activity_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_events (
    id integer NOT NULL,
    event_type public.activity_type NOT NULL,
    profile_name text,
    domain text,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: activity_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.activity_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: activity_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.activity_events_id_seq OWNED BY public.activity_events.id;


--
-- Name: activity_this_week; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.activity_this_week AS
 SELECT date(created_at) AS day,
    event_type,
    count(*) AS count
   FROM public.activity_events
  WHERE (created_at >= date_trunc('week'::text, (CURRENT_DATE)::timestamp with time zone))
  GROUP BY (date(created_at)), event_type
  ORDER BY (date(created_at)) DESC, event_type;


--
-- Name: activity_today; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.activity_today AS
 SELECT event_type,
    count(*) AS count,
    max(created_at) AS last_at
   FROM public.activity_events
  WHERE (created_at >= CURRENT_DATE)
  GROUP BY event_type;


--
-- Name: agenda_health_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.agenda_health_summary AS
 SELECT (agenda_type)::text AS agenda_type,
    (status)::text AS status,
    (control_mode)::text AS control_mode,
    count(*) AS count,
    avg(makespan_variance_pct) AS avg_variance_pct,
    avg(severity_score) AS avg_severity,
    max(created_at) AS latest
   FROM public.agenda_incidents
  WHERE (created_at > (now() - '7 days'::interval))
  GROUP BY agenda_type, status, control_mode
  ORDER BY (agenda_type)::text, (status)::text;


--
-- Name: VIEW agenda_health_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.agenda_health_summary IS 'Aggregate stats by agenda type and status';


--
-- Name: agenda_incidents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agenda_incidents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agenda_incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agenda_incidents_id_seq OWNED BY public.agenda_incidents.id;


--
-- Name: agenda_operations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agenda_operations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agenda_operations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agenda_operations_id_seq OWNED BY public.agenda_operations.id;


--
-- Name: agenda_phase_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agenda_phase_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agenda_phase_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agenda_phase_events_id_seq OWNED BY public.agenda_phase_events.id;


--
-- Name: agent_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_evaluations (
    id integer NOT NULL,
    version_id text NOT NULL,
    overall_score double precision NOT NULL,
    dimension_scores jsonb DEFAULT '{}'::jsonb,
    summary text,
    strengths jsonb DEFAULT '[]'::jsonb,
    weaknesses jsonb DEFAULT '[]'::jsonb,
    improvement_suggestions jsonb DEFAULT '[]'::jsonb,
    task_prompt text,
    agent_output text,
    context text,
    evaluator_model text,
    tokens_used integer DEFAULT 0,
    latency_ms integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    eval_type text DEFAULT 'training'::text,
    task_category text,
    task_difficulty double precision,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: agent_evaluations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_evaluations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_evaluations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_evaluations_id_seq OWNED BY public.agent_evaluations.id;


--
-- Name: agent_version_history; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.agent_version_history AS
 SELECT v.agent_id,
    v.version_id,
    v.parent_version,
    v.is_active,
    v.avg_overall_score,
    v.evaluation_count,
    v.created_at,
    v.change_notes,
    p.version_id AS parent_exists
   FROM (public.agent_versions v
     LEFT JOIN public.agent_versions p ON ((v.parent_version = p.version_id)))
  ORDER BY v.agent_id, v.created_at DESC;


--
-- Name: aiops_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aiops_events (
    id integer NOT NULL,
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    category character varying(64) NOT NULL,
    severity public.aiops_severity NOT NULL,
    status public.aiops_status DEFAULT 'detected'::public.aiops_status NOT NULL,
    endpoint character varying(64),
    description text NOT NULL,
    context jsonb DEFAULT '{}'::jsonb,
    remediation_action character varying(255),
    remediation_result jsonb,
    approved_by character varying(64),
    approved_at timestamp with time zone,
    resolved_at timestamp with time zone,
    failure_mode_id character varying(32),
    runtime_severity integer,
    runtime_occurrence integer,
    runtime_detection integer,
    rpn_score integer,
    CONSTRAINT aiops_events_rpn_score_check CHECK (((rpn_score >= 1) AND (rpn_score <= 1000))),
    CONSTRAINT aiops_events_runtime_detection_check CHECK (((runtime_detection >= 1) AND (runtime_detection <= 10))),
    CONSTRAINT aiops_events_runtime_occurrence_check CHECK (((runtime_occurrence >= 1) AND (runtime_occurrence <= 10))),
    CONSTRAINT aiops_events_runtime_severity_check CHECK (((runtime_severity >= 1) AND (runtime_severity <= 10)))
);


--
-- Name: TABLE aiops_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.aiops_events IS 'Infrastructure health events with remediation tracking';


--
-- Name: COLUMN aiops_events.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.aiops_events.category IS 'Event type: stuck_state, gpu_error, memory_pressure, endpoint_failure';


--
-- Name: COLUMN aiops_events.approved_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.aiops_events.approved_by IS 'system for auto-remediation, user identifier for manual approval';


--
-- Name: COLUMN aiops_events.failure_mode_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.aiops_events.failure_mode_id IS 'Link to FMEA catalog entry';


--
-- Name: COLUMN aiops_events.rpn_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.aiops_events.rpn_score IS 'Risk Priority Number = S × O × D (1-1000)';


--
-- Name: aiops_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aiops_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aiops_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aiops_events_id_seq OWNED BY public.aiops_events.id;


--
-- Name: ambient_daemon_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ambient_daemon_status AS
 SELECT running,
    baseline_only,
    max_cycles,
    cycles_completed,
        CASE
            WHEN (max_cycles IS NOT NULL) THEN (max_cycles - cycles_completed)
            ELSE NULL::integer
        END AS cycles_remaining,
    total_tasks,
    successful_tasks,
        CASE
            WHEN (total_tasks > 0) THEN round((((successful_tasks)::numeric / (total_tasks)::numeric) * (100)::numeric), 1)
            ELSE NULL::numeric
        END AS success_rate_pct,
    started_at,
    stopped_at,
    updated_at,
        CASE
            WHEN (running AND (started_at IS NOT NULL)) THEN (EXTRACT(epoch FROM (now() - started_at)))::integer
            ELSE NULL::integer
        END AS uptime_seconds
   FROM public.ambient_daemon_state
  WHERE (id = 1);


--
-- Name: api_key; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_key (
    id integer NOT NULL,
    user_id integer,
    key character varying(254) NOT NULL,
    key_prefix character varying(7) NOT NULL,
    creator_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    name character varying(254) NOT NULL,
    updated_by_id integer NOT NULL,
    scope character varying(64)
);


--
-- Name: TABLE api_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.api_key IS 'An API Key';


--
-- Name: COLUMN api_key.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.id IS 'The ID of the API Key itself';


--
-- Name: COLUMN api_key.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.user_id IS 'The ID of the user who this API Key acts as';


--
-- Name: COLUMN api_key.key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.key IS 'The hashed API key';


--
-- Name: COLUMN api_key.key_prefix; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.key_prefix IS 'The first 7 characters of the unhashed key';


--
-- Name: COLUMN api_key.creator_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.creator_id IS 'The ID of the user that created this API key';


--
-- Name: COLUMN api_key.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.created_at IS 'The timestamp when the key was created';


--
-- Name: COLUMN api_key.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.updated_at IS 'The timestamp when the key was last updated';


--
-- Name: COLUMN api_key.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.name IS 'The user-defined name of the API key.';


--
-- Name: COLUMN api_key.updated_by_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.updated_by_id IS 'The ID of the user that last updated this API key';


--
-- Name: COLUMN api_key.scope; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.api_key.scope IS 'The scope of the API key, if applicable';


--
-- Name: api_key_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.api_key ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.api_key_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: application_permissions_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.application_permissions_revision (
    id integer NOT NULL,
    before text NOT NULL,
    after text NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    remark text
);


--
-- Name: application_permissions_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.application_permissions_revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.application_permissions_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: archive_rotations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archive_rotations (
    id integer NOT NULL,
    quarter text NOT NULL,
    doc_archive_id integer,
    source_kb_path text NOT NULL,
    archive_kb_path text NOT NULL,
    version_at_archive text,
    status text DEFAULT 'pending'::text,
    files_moved integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


--
-- Name: TABLE archive_rotations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.archive_rotations IS 'Tracks quarterly archive rotations. Docs are moved to archive/ on version change.';


--
-- Name: archive_rotations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.archive_rotations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: archive_rotations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.archive_rotations_id_seq OWNED BY public.archive_rotations.id;


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id integer NOT NULL,
    topic character varying(32) NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    end_timestamp timestamp with time zone,
    user_id integer,
    model character varying(32),
    model_id integer,
    details text NOT NULL
);


--
-- Name: TABLE audit_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.audit_log IS 'Used to store application events for auditing use cases';


--
-- Name: COLUMN audit_log.topic; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.topic IS 'The topic of a given audit event';


--
-- Name: COLUMN audit_log."timestamp"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log."timestamp" IS 'The time an event was recorded';


--
-- Name: COLUMN audit_log.end_timestamp; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.end_timestamp IS 'The time an event ended, if applicable';


--
-- Name: COLUMN audit_log.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.user_id IS 'The user who performed an action or triggered an event';


--
-- Name: COLUMN audit_log.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.model IS 'The name of the model this event applies to (e.g. Card, Dashboard), if applicable';


--
-- Name: COLUMN audit_log.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.model_id IS 'The ID of the model this event applies to, if applicable';


--
-- Name: COLUMN audit_log.details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.details IS 'A JSON map with metadata about the event';


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.audit_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: best_agent_versions; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.best_agent_versions AS
 SELECT DISTINCT ON (agent_id) agent_id,
    version_id,
    avg_overall_score,
    evaluation_count,
    config
   FROM public.agent_versions
  WHERE (evaluation_count >= 3)
  ORDER BY agent_id, avg_overall_score DESC;


--
-- Name: bookmark_ordering; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bookmark_ordering (
    id integer NOT NULL,
    user_id integer NOT NULL,
    type character varying(255) NOT NULL,
    item_id integer NOT NULL,
    ordering integer NOT NULL
);


--
-- Name: bookmark_ordering_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.bookmark_ordering ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.bookmark_ordering_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cache_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cache_config (
    id integer NOT NULL,
    model character varying(32) NOT NULL,
    model_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    strategy text NOT NULL,
    config text NOT NULL,
    state text,
    invalidated_at timestamp with time zone,
    next_run_at timestamp with time zone,
    refresh_automatically boolean DEFAULT false
);


--
-- Name: TABLE cache_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cache_config IS 'Cache Configuration';


--
-- Name: COLUMN cache_config.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.id IS 'Unique ID';


--
-- Name: COLUMN cache_config.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.model IS 'Name of an entity model';


--
-- Name: COLUMN cache_config.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.model_id IS 'ID of the said entity';


--
-- Name: COLUMN cache_config.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.created_at IS 'Timestamp when the config was inserted';


--
-- Name: COLUMN cache_config.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.updated_at IS 'Timestamp when the config was updated';


--
-- Name: COLUMN cache_config.strategy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.strategy IS 'caching strategy name';


--
-- Name: COLUMN cache_config.config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.config IS 'caching strategy configuration';


--
-- Name: COLUMN cache_config.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.state IS 'state for strategies needing to keep some data between runs';


--
-- Name: COLUMN cache_config.invalidated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.invalidated_at IS 'indicates when a cache was invalidated last time for schedule-based strategies';


--
-- Name: COLUMN cache_config.next_run_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.next_run_at IS 'keeps next time to run for schedule-based strategies';


--
-- Name: COLUMN cache_config.refresh_automatically; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cache_config.refresh_automatically IS 'Whether or not we should automatically refresh cache results when a cache expires';


--
-- Name: cache_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cache_config ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.cache_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: evolution_calibrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_calibrations (
    id integer NOT NULL,
    agent_id text NOT NULL,
    version_id text,
    objective_name text NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    local_score double precision NOT NULL,
    calibration_score double precision NOT NULL,
    delta double precision GENERATED ALWAYS AS ((calibration_score - local_score)) STORED,
    local_breakdown jsonb DEFAULT '{}'::jsonb,
    calibration_breakdown jsonb DEFAULT '{}'::jsonb,
    drift_detected boolean DEFAULT false,
    drift_magnitude double precision,
    objective_path text,
    document_path text,
    gate_results jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    latency_ms integer,
    tokens_used integer,
    cost_usd double precision,
    CONSTRAINT evolution_calibrations_provider_check CHECK ((provider = ANY (ARRAY['cerebras'::text, 'xai'::text, 'anthropic'::text])))
);


--
-- Name: calibration_health; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.calibration_health AS
 SELECT agent_id,
    count(*) AS total_calibrations,
    count(*) FILTER (WHERE drift_detected) AS drift_count,
    avg(delta) AS avg_delta,
    max(abs(delta)) AS max_abs_delta,
    avg(local_score) AS avg_local_score,
    avg(calibration_score) AS avg_calibration_score,
    corr(local_score, calibration_score) AS score_correlation,
        CASE
            WHEN (avg(delta) > (0.1)::double precision) THEN 'under_scoring'::text
            WHEN (avg(delta) < ('-0.1'::numeric)::double precision) THEN 'over_scoring'::text
            ELSE 'calibrated'::text
        END AS calibration_status,
    max(created_at) AS last_calibration
   FROM public.evolution_calibrations
  WHERE (created_at > (now() - '7 days'::interval))
  GROUP BY agent_id;


--
-- Name: calibration_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calibration_summaries (
    id integer NOT NULL,
    agent_id text NOT NULL,
    total_calibrations integer DEFAULT 0,
    drift_count integer DEFAULT 0,
    avg_delta double precision DEFAULT 0.0,
    max_delta double precision DEFAULT 0.0,
    cerebras_count integer DEFAULT 0,
    xai_count integer DEFAULT 0,
    local_calibrated boolean DEFAULT false,
    confidence_score double precision DEFAULT 0.0,
    needs_recalibration boolean DEFAULT false,
    last_recalibration_at timestamp with time zone,
    window_start timestamp with time zone DEFAULT (now() - '7 days'::interval),
    window_end timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: calibration_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.calibration_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: calibration_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.calibration_summaries_id_seq OWNED BY public.calibration_summaries.id;


--
-- Name: card_bookmark; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.card_bookmark (
    id integer NOT NULL,
    user_id integer NOT NULL,
    card_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: card_bookmark_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.card_bookmark ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.card_bookmark_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: card_label; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.card_label (
    id integer NOT NULL,
    card_id integer NOT NULL,
    label_id integer NOT NULL
);


--
-- Name: card_label_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.card_label ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.card_label_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: channel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel (
    id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    type character varying(32) NOT NULL,
    details text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: TABLE channel; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.channel IS 'Channel configurations';


--
-- Name: COLUMN channel.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.id IS 'Unique ID';


--
-- Name: COLUMN channel.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.name IS 'channel name';


--
-- Name: COLUMN channel.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.description IS 'channel description';


--
-- Name: COLUMN channel.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.type IS 'Channel type';


--
-- Name: COLUMN channel.details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.details IS 'Channel details, used to store authentication information or channel-specific settings';


--
-- Name: COLUMN channel.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.active IS 'whether the channel is active';


--
-- Name: COLUMN channel.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.created_at IS 'Timestamp when the channel was inserted';


--
-- Name: COLUMN channel.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel.updated_at IS 'Timestamp when the channel was updated';


--
-- Name: channel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.channel ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.channel_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: channel_template; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel_template (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    channel_type character varying(64) NOT NULL,
    details text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: TABLE channel_template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.channel_template IS 'custom template for the channel';


--
-- Name: COLUMN channel_template.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel_template.name IS 'the name of the template';


--
-- Name: COLUMN channel_template.channel_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel_template.channel_type IS 'the channel type of the template';


--
-- Name: COLUMN channel_template.details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel_template.details IS 'the details of the template';


--
-- Name: COLUMN channel_template.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel_template.created_at IS 'The timestamp of when the template was created';


--
-- Name: COLUMN channel_template.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.channel_template.updated_at IS 'The timestamp of when the template was last updated';


--
-- Name: channel_template_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.channel_template ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.channel_template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cloud_migration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cloud_migration (
    id integer NOT NULL,
    external_id text NOT NULL,
    upload_url text NOT NULL,
    state character varying(32) DEFAULT 'init'::character varying NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: TABLE cloud_migration; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cloud_migration IS 'Migrate to cloud directly from Metabase';


--
-- Name: COLUMN cloud_migration.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.id IS 'Unique ID';


--
-- Name: COLUMN cloud_migration.external_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.external_id IS 'Matching ID in Cloud for this migration';


--
-- Name: COLUMN cloud_migration.upload_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.upload_url IS 'URL where the backup will be uploaded to';


--
-- Name: COLUMN cloud_migration.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.state IS 'Current state of the migration: init, setup, dump, upload, done, error, cancelled';


--
-- Name: COLUMN cloud_migration.progress; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.progress IS 'Number between 0 to 100 representing progress as a percentage';


--
-- Name: COLUMN cloud_migration.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.created_at IS 'Timestamp when the config was inserted';


--
-- Name: COLUMN cloud_migration.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cloud_migration.updated_at IS 'Timestamp when the config was updated';


--
-- Name: cloud_migration_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cloud_migration ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.cloud_migration_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cognition_cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cognition_cycles (
    id integer NOT NULL,
    profile_name text DEFAULT 'default'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms integer,
    trigger_reason text NOT NULL,
    thoughts_generated integer DEFAULT 0,
    patterns_detected integer DEFAULT 0,
    connections_found integer DEFAULT 0,
    model_used text,
    tokens_used integer DEFAULT 0,
    content_items_analyzed integer DEFAULT 0,
    kb_entries_scanned integer DEFAULT 0,
    error text,
    success boolean DEFAULT true
);


--
-- Name: cognition_cycles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cognition_cycles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cognition_cycles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cognition_cycles_id_seq OWNED BY public.cognition_cycles.id;


--
-- Name: cognition_thoughts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cognition_thoughts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    thought_type text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    summary text,
    domains text[] DEFAULT '{}'::text[],
    kb_paths text[] DEFAULT '{}'::text[],
    source_entries text[] DEFAULT '{}'::text[],
    related_thoughts uuid[] DEFAULT '{}'::uuid[],
    salience double precision DEFAULT 0.5,
    confidence double precision DEFAULT 0.5,
    novelty double precision DEFAULT 0.5,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    surfaced_at timestamp with time zone,
    expires_at timestamp with time zone,
    profile_name text DEFAULT 'default'::text,
    generator_model text,
    tokens_used integer DEFAULT 0,
    generation_context jsonb DEFAULT '{}'::jsonb,
    predecessor_id uuid,
    generation integer DEFAULT 0,
    thought_chain_id uuid,
    note_path text,
    content_hash text
);


--
-- Name: COLUMN cognition_thoughts.predecessor_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cognition_thoughts.predecessor_id IS 'UUID of the thought that this thought builds upon';


--
-- Name: COLUMN cognition_thoughts.generation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cognition_thoughts.generation IS 'Depth in thought chain (0 = root thought)';


--
-- Name: COLUMN cognition_thoughts.thought_chain_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cognition_thoughts.thought_chain_id IS 'Groups related thoughts into chains';


--
-- Name: COLUMN cognition_thoughts.note_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cognition_thoughts.note_path IS 'Path to the markdown note in scratch/';


--
-- Name: COLUMN cognition_thoughts.content_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cognition_thoughts.content_hash IS 'SHA256 hash for exact duplicate detection (semantic similarity uses Qdrant)';


--
-- Name: collection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection (
    id integer NOT NULL,
    name text NOT NULL,
    description text,
    archived boolean DEFAULT false NOT NULL,
    location character varying(254) DEFAULT '/'::character varying NOT NULL,
    personal_owner_id integer,
    slug character varying(510) NOT NULL,
    namespace character varying(254),
    authority_level character varying(255),
    entity_id character(21),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    type character varying(256),
    is_sample boolean DEFAULT false NOT NULL,
    archive_operation_id character(36),
    archived_directly boolean
);


--
-- Name: COLUMN collection.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.collection.created_at IS 'Timestamp of when this Collection was created.';


--
-- Name: COLUMN collection.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.collection.type IS 'This is used to differentiate instance-analytics collections from all other collections.';


--
-- Name: COLUMN collection.is_sample; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.collection.is_sample IS 'Is the collection part of the sample content?';


--
-- Name: COLUMN collection.archive_operation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.collection.archive_operation_id IS 'The UUID of the trash operation. Each time you trash a collection subtree, you get a unique ID.';


--
-- Name: COLUMN collection.archived_directly; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.collection.archived_directly IS 'Whether the item was trashed independently or as a subcollection';


--
-- Name: collection_bookmark; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection_bookmark (
    id integer NOT NULL,
    user_id integer NOT NULL,
    collection_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: collection_bookmark_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.collection_bookmark ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.collection_bookmark_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: collection_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.collection ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.collection_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: collection_permission_graph_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection_permission_graph_revision (
    id integer NOT NULL,
    before text NOT NULL,
    after text NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    remark text
);


--
-- Name: collection_permission_graph_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.collection_permission_graph_revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.collection_permission_graph_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: command_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.command_history (
    id integer NOT NULL,
    client_id text NOT NULL,
    kb_root text,
    command text NOT NULL,
    args_json jsonb,
    success boolean,
    offline boolean DEFAULT false,
    result_json jsonb,
    duration_ms integer,
    executed_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE command_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.command_history IS 'Unified command history across all entry points.';


--
-- Name: COLUMN command_history.offline; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.command_history.offline IS 'True if command was attempted while Engine unavailable.';


--
-- Name: command_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.command_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: command_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.command_history_id_seq OWNED BY public.command_history.id;


--
-- Name: connection_impersonations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.connection_impersonations (
    id integer NOT NULL,
    db_id integer NOT NULL,
    group_id integer NOT NULL,
    attribute text
);


--
-- Name: TABLE connection_impersonations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.connection_impersonations IS 'Table for holding connection impersonation policies';


--
-- Name: COLUMN connection_impersonations.db_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.connection_impersonations.db_id IS 'ID of the database this connection impersonation policy affects';


--
-- Name: COLUMN connection_impersonations.group_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.connection_impersonations.group_id IS 'ID of the permissions group this connection impersonation policy affects';


--
-- Name: COLUMN connection_impersonations.attribute; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.connection_impersonations.attribute IS 'User attribute associated with the database role to use for this connection impersonation policy';


--
-- Name: connection_impersonations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.connection_impersonations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.connection_impersonations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: content_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.content_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: content_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.content_items_id_seq OWNED BY public.content_items.id;


--
-- Name: content_translation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_translation (
    id integer NOT NULL,
    locale character varying(5) NOT NULL,
    msgid text NOT NULL,
    msgstr text NOT NULL
);


--
-- Name: TABLE content_translation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.content_translation IS 'Content translations';


--
-- Name: COLUMN content_translation.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_translation.id IS 'Unique ID';


--
-- Name: COLUMN content_translation.locale; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_translation.locale IS 'Locale';


--
-- Name: COLUMN content_translation.msgid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_translation.msgid IS 'The raw string';


--
-- Name: COLUMN content_translation.msgstr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_translation.msgstr IS 'The translation';


--
-- Name: content_translation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.content_translation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.content_translation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: core_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.core_session (
    id character varying(254) NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    anti_csrf_token text,
    key_hashed character varying(254) NOT NULL
);


--
-- Name: COLUMN core_session.key_hashed; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_session.key_hashed IS 'Hashed version of the session key';


--
-- Name: core_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.core_user (
    id integer NOT NULL,
    email public.citext NOT NULL,
    first_name character varying(254),
    last_name character varying(254),
    password character varying(254),
    password_salt character varying(254) DEFAULT 'default'::character varying,
    date_joined timestamp with time zone NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    reset_token character varying(254),
    reset_triggered bigint,
    is_qbnewb boolean DEFAULT true NOT NULL,
    login_attributes text,
    updated_at timestamp with time zone,
    sso_source character varying(254),
    locale character varying(5),
    is_datasetnewb boolean DEFAULT true NOT NULL,
    settings text,
    type character varying(64) DEFAULT 'personal'::character varying NOT NULL,
    entity_id character(21),
    deactivated_at timestamp with time zone,
    tenant_id integer,
    jwt_attributes text
);


--
-- Name: COLUMN core_user.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_user.type IS 'The type of user';


--
-- Name: COLUMN core_user.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_user.entity_id IS 'NanoID tag for each user';


--
-- Name: COLUMN core_user.deactivated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_user.deactivated_at IS 'The timestamp at which a user was deactivated';


--
-- Name: COLUMN core_user.tenant_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_user.tenant_id IS 'The ID of the tenant for this user';


--
-- Name: COLUMN core_user.jwt_attributes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.core_user.jwt_attributes IS 'JSON object containing attributes set through jwt';


--
-- Name: core_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.core_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.core_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: corpus_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.corpus_versions (
    id integer NOT NULL,
    version_id character varying(128) NOT NULL,
    document_count integer DEFAULT 0 NOT NULL,
    vocabulary_size integer DEFAULT 0 NOT NULL,
    minio_path text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE corpus_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.corpus_versions IS 'Tracks corpus snapshots for incremental topic model training';


--
-- Name: corpus_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.corpus_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: corpus_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.corpus_versions_id_seq OWNED BY public.corpus_versions.id;


--
-- Name: current_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.current_state (
    kb_root text NOT NULL,
    snapshot_id integer,
    generation bigint DEFAULT 0,
    state_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE current_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.current_state IS 'Cached grid state for instant TUI startup. Denormalized for fast reads.';


--
-- Name: COLUMN current_state.generation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.current_state.generation IS 'Monotonic counter for sync protocol. Only update if incoming > current.';


--
-- Name: COLUMN current_state.state_json; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.current_state.state_json IS 'Complete GridState as JSON: documents, clusters, allocations, tda, geometry.';


--
-- Name: daily_eval_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_eval_summaries (
    id integer NOT NULL,
    eval_date date NOT NULL,
    total_cycles integer DEFAULT 0,
    successful_cycles integer DEFAULT 0,
    total_improvement_percent double precision DEFAULT 0.0,
    agent_summaries jsonb DEFAULT '{}'::jsonb,
    held_out_results jsonb DEFAULT '{}'::jsonb,
    trend_direction text,
    trend_confidence double precision,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: daily_eval_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_eval_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_eval_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_eval_summaries_id_seq OWNED BY public.daily_eval_summaries.id;


--
-- Name: daily_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_summaries (
    id integer NOT NULL,
    summary_date date NOT NULL,
    profile_name text,
    content text NOT NULL,
    highlights jsonb DEFAULT '[]'::jsonb,
    metrics jsonb DEFAULT '{}'::jsonb,
    generated_at timestamp with time zone DEFAULT now(),
    generator_model text
);


--
-- Name: daily_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_summaries_id_seq OWNED BY public.daily_summaries.id;


--
-- Name: dashboard_bookmark; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboard_bookmark (
    id integer NOT NULL,
    user_id integer NOT NULL,
    dashboard_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dashboard_bookmark_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dashboard_bookmark ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dashboard_bookmark_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dashboard_favorite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboard_favorite (
    id integer NOT NULL,
    user_id integer NOT NULL,
    dashboard_id integer NOT NULL
);


--
-- Name: dashboard_favorite_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dashboard_favorite ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dashboard_favorite_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dashboard_tab; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboard_tab (
    id integer NOT NULL,
    dashboard_id integer NOT NULL,
    name text NOT NULL,
    "position" integer NOT NULL,
    entity_id character(21),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE dashboard_tab; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.dashboard_tab IS 'Join table connecting dashboard to dashboardcards';


--
-- Name: COLUMN dashboard_tab.dashboard_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab.dashboard_id IS 'The dashboard that a tab is on';


--
-- Name: COLUMN dashboard_tab.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab.name IS 'Displayed name of the tab';


--
-- Name: COLUMN dashboard_tab."position"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab."position" IS 'Position of the tab with respect to others tabs in dashboard';


--
-- Name: COLUMN dashboard_tab.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab.entity_id IS 'Random NanoID tag for unique identity.';


--
-- Name: COLUMN dashboard_tab.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab.created_at IS 'The timestamp at which the tab was created';


--
-- Name: COLUMN dashboard_tab.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dashboard_tab.updated_at IS 'The timestamp at which the tab was last updated';


--
-- Name: dashboard_tab_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dashboard_tab ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dashboard_tab_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dashboardcard_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboardcard_series (
    id integer NOT NULL,
    dashboardcard_id integer NOT NULL,
    card_id integer NOT NULL,
    "position" integer NOT NULL
);


--
-- Name: dashboardcard_series_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dashboardcard_series ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dashboardcard_series_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: data_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_permissions (
    id integer NOT NULL,
    group_id integer NOT NULL,
    perm_type character varying(64) NOT NULL,
    db_id integer NOT NULL,
    schema_name character varying(254),
    table_id integer,
    perm_value character varying(64) NOT NULL
);


--
-- Name: TABLE data_permissions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.data_permissions IS 'A table to store database and table permissions';


--
-- Name: COLUMN data_permissions.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.id IS 'The ID of the permission';


--
-- Name: COLUMN data_permissions.group_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.group_id IS 'The ID of the associated permission group';


--
-- Name: COLUMN data_permissions.perm_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.perm_type IS 'The type of the permission (e.g. "data", "collection", "download"...)';


--
-- Name: COLUMN data_permissions.db_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.db_id IS 'A database ID, for DB and table-level permissions';


--
-- Name: COLUMN data_permissions.schema_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.schema_name IS 'A schema name, for table-level permissions';


--
-- Name: COLUMN data_permissions.table_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.table_id IS 'A table ID';


--
-- Name: COLUMN data_permissions.perm_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.data_permissions.perm_value IS 'The value this permission is set to.';


--
-- Name: data_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.data_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.data_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: databasechangelog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.databasechangelog (
    id character varying(255) NOT NULL,
    author character varying(255) NOT NULL,
    filename character varying(255) NOT NULL,
    dateexecuted timestamp without time zone NOT NULL,
    orderexecuted integer NOT NULL,
    exectype character varying(10) NOT NULL,
    md5sum character varying(35),
    description character varying(255),
    comments character varying(255),
    tag character varying(255),
    liquibase character varying(20),
    contexts character varying(255),
    labels character varying(255),
    deployment_id character varying(10)
);


--
-- Name: db_router; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.db_router (
    id integer NOT NULL,
    database_id integer NOT NULL,
    user_attribute character varying(254) NOT NULL
);


--
-- Name: TABLE db_router; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.db_router IS 'Configuration for Database Routers. Currently just holds which user attribute each
configured router database should use to choose a mirror database to route to.';


--
-- Name: COLUMN db_router.database_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.db_router.database_id IS 'The ID of the database this is for.';


--
-- Name: COLUMN db_router.user_attribute; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.db_router.user_attribute IS 'The user attribute used to redirect users to a different database.';


--
-- Name: db_router_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.db_router ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.db_router_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dependency; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dependency (
    id integer NOT NULL,
    model character varying(32) NOT NULL,
    model_id integer NOT NULL,
    dependent_on_model character varying(32) NOT NULL,
    dependent_on_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: dependency_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dependency ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dependency_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dimension; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dimension (
    id integer NOT NULL,
    field_id integer NOT NULL,
    name character varying(254) NOT NULL,
    type character varying(254) NOT NULL,
    human_readable_field_id integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    entity_id character(21)
);


--
-- Name: dimension_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dimension ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dimension_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: doc_archives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.doc_archives (
    id integer NOT NULL,
    source_id integer NOT NULL,
    archive_url text NOT NULL,
    version text,
    content_hash text,
    status text DEFAULT 'discovered'::text,
    kb_path_prefix text,
    pages_extracted integer DEFAULT 0,
    error_message text,
    retry_count integer DEFAULT 0,
    discovered_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone
);


--
-- Name: TABLE doc_archives; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.doc_archives IS 'Tracks documentation archives discovered for ETL processing.';


--
-- Name: COLUMN doc_archives.content_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.doc_archives.content_hash IS 'SHA-256 hash of archive content for incremental sync (skip if unchanged).';


--
-- Name: doc_archives_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.doc_archives_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: doc_archives_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.doc_archives_id_seq OWNED BY public.doc_archives.id;


--
-- Name: feed_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feed_sources (
    id integer NOT NULL,
    name text NOT NULL,
    source_type public.source_type NOT NULL,
    base_url text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb,
    fetch_interval_minutes integer DEFAULT 60,
    active boolean DEFAULT true,
    last_fetch_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: doc_sync_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.doc_sync_status AS
 SELECT fs.name AS source_name,
    fs.source_type,
    da.archive_url,
    da.version,
    da.status,
    da.pages_extracted,
    da.kb_path_prefix,
    da.processed_at,
    da.error_message,
        CASE
            WHEN (da.status = 'completed'::text) THEN (EXTRACT(epoch FROM (now() - da.processed_at)) / (86400)::numeric)
            ELSE NULL::numeric
        END AS days_since_sync
   FROM (public.doc_archives da
     JOIN public.feed_sources fs ON ((da.source_id = fs.id)))
  ORDER BY da.processed_at DESC NULLS LAST;


--
-- Name: document_topics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_topics (
    id integer NOT NULL,
    document_id character varying(256) NOT NULL,
    model_id integer,
    topics jsonb NOT NULL,
    top_words jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE document_topics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.document_topics IS 'Topic assignments for documents';


--
-- Name: document_topics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_topics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_topics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_topics_id_seq OWNED BY public.document_topics.id;


--
-- Name: engine_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.engine_observations (
    id integer NOT NULL,
    source text NOT NULL,
    observation_type text DEFAULT 'normal'::text NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb,
    anomalies text[] DEFAULT '{}'::text[],
    notes text,
    related_thought_id uuid,
    related_cycle_id integer,
    observed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE engine_observations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.engine_observations IS 'Observations from engine monitoring for cognition auditing';


--
-- Name: engine_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.engine_observations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: engine_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.engine_observations_id_seq OWNED BY public.engine_observations.id;


--
-- Name: eval_score_comparison; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.eval_score_comparison AS
 SELECT e.version_id,
    v.agent_id,
    avg(e.overall_score) FILTER (WHERE (e.eval_type = 'training'::text)) AS training_score,
    avg(e.overall_score) FILTER (WHERE (e.eval_type = 'held_out'::text)) AS held_out_score,
    count(*) FILTER (WHERE (e.eval_type = 'training'::text)) AS training_count,
    count(*) FILTER (WHERE (e.eval_type = 'held_out'::text)) AS held_out_count,
    (avg(e.overall_score) FILTER (WHERE (e.eval_type = 'training'::text)) - avg(e.overall_score) FILTER (WHERE (e.eval_type = 'held_out'::text))) AS overfit_gap
   FROM (public.agent_evaluations e
     JOIN public.agent_versions v ON ((e.version_id = v.version_id)))
  GROUP BY e.version_id, v.agent_id
 HAVING (count(*) FILTER (WHERE (e.eval_type = 'held_out'::text)) > 0);


--
-- Name: evolution_calibrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.evolution_calibrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: evolution_calibrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.evolution_calibrations_id_seq OWNED BY public.evolution_calibrations.id;


--
-- Name: evolution_cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evolution_cycles (
    id integer NOT NULL,
    agent_id text NOT NULL,
    version_before text,
    version_after text,
    strategy text NOT NULL,
    trigger_type text DEFAULT 'idle'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    duration_ms integer,
    success boolean DEFAULT false NOT NULL,
    preempted boolean DEFAULT false,
    improvement_percent double precision DEFAULT 0.0,
    training_scores jsonb DEFAULT '{}'::jsonb,
    held_out_scores jsonb DEFAULT '{}'::jsonb,
    curriculum_phase text,
    gpu_utilization double precision,
    notes text
);


--
-- Name: evolution_cycles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.evolution_cycles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: evolution_cycles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.evolution_cycles_id_seq OWNED BY public.evolution_cycles.id;


--
-- Name: evolution_performance; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.evolution_performance AS
 SELECT agent_id,
    count(*) AS total_cycles,
    count(*) FILTER (WHERE success) AS successful_cycles,
    avg(improvement_percent) FILTER (WHERE success) AS avg_improvement,
    max(improvement_percent) AS best_improvement,
    avg((EXTRACT(epoch FROM (completed_at - started_at)) * (1000)::numeric)) AS avg_duration_ms,
    max(started_at) AS last_cycle_at
   FROM public.evolution_cycles
  WHERE (started_at > (now() - '7 days'::interval))
  GROUP BY agent_id;


--
-- Name: external_routing_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_routing_metrics (
    id integer NOT NULL,
    task_type text NOT NULL,
    provider text NOT NULL,
    latency_ms integer,
    tokens_used integer,
    quality_score real,
    fallback_chain text[],
    fallback_reason text,
    endpoint text,
    incident_fingerprint text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE external_routing_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.external_routing_metrics IS 'Tracks external API routing decisions and performance';


--
-- Name: COLUMN external_routing_metrics.task_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.external_routing_metrics.task_type IS 'Task category: diagnosis, planning, code_gen, verification, documentation';


--
-- Name: COLUMN external_routing_metrics.fallback_chain; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.external_routing_metrics.fallback_chain IS 'Array of providers tried before successful completion';


--
-- Name: external_routing_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.external_routing_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: external_routing_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.external_routing_metrics_id_seq OWNED BY public.external_routing_metrics.id;


--
-- Name: feed_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.feed_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: feed_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.feed_sources_id_seq OWNED BY public.feed_sources.id;


--
-- Name: fetch_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fetch_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fetch_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fetch_jobs_id_seq OWNED BY public.fetch_jobs.id;


--
-- Name: field_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.field_usage (
    id integer NOT NULL,
    field_id integer NOT NULL,
    query_execution_id integer NOT NULL,
    used_in character varying(25) NOT NULL,
    filter_op character varying(25),
    aggregation_function character varying(25),
    breakout_temporal_unit character varying(25),
    breakout_binning_strategy character varying(25),
    breakout_binning_num_bins integer,
    breakout_binning_bin_width integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE field_usage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.field_usage IS 'Used to store field usage during query execution';


--
-- Name: COLUMN field_usage.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.id IS 'Unique ID';


--
-- Name: COLUMN field_usage.field_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.field_id IS 'ID of the field';


--
-- Name: COLUMN field_usage.query_execution_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.query_execution_id IS 'referenced query execution';


--
-- Name: COLUMN field_usage.used_in; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.used_in IS 'which part of the query the field was used in';


--
-- Name: COLUMN field_usage.filter_op; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.filter_op IS 'filter''s operator that applied to the field';


--
-- Name: COLUMN field_usage.aggregation_function; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.aggregation_function IS 'the aggregation function that field applied to';


--
-- Name: COLUMN field_usage.breakout_temporal_unit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.breakout_temporal_unit IS 'temporal unit options of the breakout';


--
-- Name: COLUMN field_usage.breakout_binning_strategy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.breakout_binning_strategy IS 'the strategy of breakout';


--
-- Name: COLUMN field_usage.breakout_binning_num_bins; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.breakout_binning_num_bins IS 'The numbin option of breakout';


--
-- Name: COLUMN field_usage.breakout_binning_bin_width; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.breakout_binning_bin_width IS 'The numbin option of breakout';


--
-- Name: COLUMN field_usage.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.field_usage.created_at IS 'The time a field usage was recorded';


--
-- Name: field_usage_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.field_usage ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.field_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fmea_adjustments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fmea_adjustments (
    id integer NOT NULL,
    failure_mode_id character varying(32) NOT NULL,
    endpoint character varying(64),
    hour_of_day integer,
    adjusted_severity integer,
    adjusted_occurrence integer,
    adjusted_detection integer,
    sample_count integer DEFAULT 0,
    last_updated timestamp with time zone DEFAULT now(),
    CONSTRAINT fmea_adjustments_adjusted_detection_check CHECK (((adjusted_detection >= 1) AND (adjusted_detection <= 10))),
    CONSTRAINT fmea_adjustments_adjusted_occurrence_check CHECK (((adjusted_occurrence >= 1) AND (adjusted_occurrence <= 10))),
    CONSTRAINT fmea_adjustments_adjusted_severity_check CHECK (((adjusted_severity >= 1) AND (adjusted_severity <= 10))),
    CONSTRAINT fmea_adjustments_hour_of_day_check CHECK (((hour_of_day >= 0) AND (hour_of_day <= 23)))
);


--
-- Name: TABLE fmea_adjustments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fmea_adjustments IS 'Context-specific S/O/D adjustments learned from outcomes';


--
-- Name: fmea_adjustments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fmea_adjustments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fmea_adjustments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fmea_adjustments_id_seq OWNED BY public.fmea_adjustments.id;


--
-- Name: fmea_occurrences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fmea_occurrences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fmea_occurrences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fmea_occurrences_id_seq OWNED BY public.fmea_occurrences.id;


--
-- Name: fmea_outcomes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fmea_outcomes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fmea_outcomes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fmea_outcomes_id_seq OWNED BY public.fmea_outcomes.id;


--
-- Name: github_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.github_issues (
    id integer NOT NULL,
    fingerprint text NOT NULL,
    issue_number integer NOT NULL,
    repo text NOT NULL,
    issue_url text,
    sequence_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    last_updated_at timestamp with time zone,
    recurrence_count integer DEFAULT 0,
    status text DEFAULT 'open'::text,
    CONSTRAINT github_issues_status_check CHECK ((status = ANY (ARRAY['open'::text, 'closed'::text, 'stale'::text])))
);


--
-- Name: TABLE github_issues; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.github_issues IS 'Tracks GitHub issues created for health incidents';


--
-- Name: COLUMN github_issues.fingerprint; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.github_issues.fingerprint IS 'Unique incident identifier: FAILURE_MODE_ID:endpoint';


--
-- Name: COLUMN github_issues.recurrence_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.github_issues.recurrence_count IS 'Number of times this incident recurred while issue was open';


--
-- Name: github_issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.github_issues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: github_issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.github_issues_id_seq OWNED BY public.github_issues.id;


--
-- Name: grid_allocations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_allocations (
    id integer NOT NULL,
    snapshot_id integer,
    "values" jsonb DEFAULT '[]'::jsonb NOT NULL
);


--
-- Name: grid_allocations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_allocations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_allocations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_allocations_id_seq OWNED BY public.grid_allocations.id;


--
-- Name: grid_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_clusters (
    id integer NOT NULL,
    snapshot_id integer,
    x integer NOT NULL,
    y integer NOT NULL,
    CONSTRAINT grid_clusters_x_check CHECK (((x >= 0) AND (x < 19))),
    CONSTRAINT grid_clusters_y_check CHECK (((y >= 0) AND (y < 19)))
);


--
-- Name: grid_clusters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_clusters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_clusters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_clusters_id_seq OWNED BY public.grid_clusters.id;


--
-- Name: grid_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_embeddings (
    id integer NOT NULL,
    snapshot_id integer,
    embedding_index integer NOT NULL,
    vector jsonb NOT NULL,
    grid_x integer,
    grid_y integer
);


--
-- Name: grid_embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_embeddings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_embeddings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_embeddings_id_seq OWNED BY public.grid_embeddings.id;


--
-- Name: grid_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_points (
    id integer NOT NULL,
    snapshot_id integer,
    x integer NOT NULL,
    y integer NOT NULL,
    doc_path text NOT NULL,
    doc_title text DEFAULT ''::text,
    embedding_id text DEFAULT ''::text,
    cluster_id integer DEFAULT '-1'::integer,
    CONSTRAINT grid_points_x_check CHECK (((x >= 0) AND (x < 19))),
    CONSTRAINT grid_points_y_check CHECK (((y >= 0) AND (y < 19)))
);


--
-- Name: grid_points_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_points_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_points_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_points_id_seq OWNED BY public.grid_points.id;


--
-- Name: grid_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_snapshots (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    kb_root text NOT NULL,
    embedding_model text NOT NULL,
    embedding_type text DEFAULT 'single'::text,
    projection_method text DEFAULT 'umap'::text,
    n_documents integer DEFAULT 0,
    coverage double precision DEFAULT 0.0,
    h0_count integer DEFAULT 0,
    h1_count integer DEFAULT 0,
    h2_count integer DEFAULT 0,
    entropy double precision DEFAULT 0.0,
    is_current boolean DEFAULT false,
    metadata jsonb DEFAULT '{}'::jsonb,
    generation bigint DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: grid_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_snapshots_id_seq OWNED BY public.grid_snapshots.id;


--
-- Name: grid_tda_features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grid_tda_features (
    id integer NOT NULL,
    snapshot_id integer,
    h1_cycles jsonb DEFAULT '[]'::jsonb,
    h2_voids jsonb DEFAULT '[]'::jsonb,
    components jsonb DEFAULT '[]'::jsonb,
    risk_scores jsonb DEFAULT '[]'::jsonb,
    intervals jsonb DEFAULT '[]'::jsonb
);


--
-- Name: grid_tda_features_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grid_tda_features_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grid_tda_features_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grid_tda_features_id_seq OWNED BY public.grid_tda_features.id;


--
-- Name: sandboxes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sandboxes (
    id integer NOT NULL,
    group_id integer NOT NULL,
    table_id integer NOT NULL,
    card_id integer,
    attribute_remappings text
);


--
-- Name: group_table_access_policy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.sandboxes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.group_table_access_policy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: healing_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.healing_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: healing_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.healing_events_id_seq OWNED BY public.healing_events.id;


--
-- Name: health_loop_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_loop_state (
    id integer NOT NULL,
    updated_at timestamp with time zone DEFAULT now(),
    check_interval_seconds integer DEFAULT 30,
    stuck_starting_timeout_seconds integer DEFAULT 300,
    stuck_stopping_timeout_seconds integer DEFAULT 120,
    endpoint_last_check jsonb DEFAULT '{}'::jsonb,
    stuck_detections jsonb DEFAULT '{}'::jsonb,
    total_auto_remediations integer DEFAULT 0,
    total_pending_approvals integer DEFAULT 0,
    last_remediation_at timestamp with time zone,
    circuit_breaker jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE health_loop_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.health_loop_state IS 'Persistent state for autonomous health loop';


--
-- Name: COLUMN health_loop_state.circuit_breaker; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.health_loop_state.circuit_breaker IS 'Global circuit breaker state: {global_failures, global_cooldown_until}';


--
-- Name: health_loop_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.health_loop_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: health_loop_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.health_loop_state_id_seq OWNED BY public.health_loop_state.id;


--
-- Name: health_observer_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.health_observer_state (
    id integer DEFAULT 1 NOT NULL,
    started_at timestamp with time zone,
    stopped_at timestamp with time zone,
    last_poll_at timestamp with time zone,
    poll_count integer DEFAULT 0,
    active_incidents jsonb DEFAULT '{}'::jsonb,
    acp_connected boolean DEFAULT false,
    acp_session_id text,
    acp_prompts_sent integer DEFAULT 0,
    acp_prompts_succeeded integer DEFAULT 0,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT health_observer_state_id_check CHECK ((id = 1))
);


--
-- Name: TABLE health_observer_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.health_observer_state IS 'Singleton row tracking HealthObserver daemon state';


--
-- Name: held_out_queries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.held_out_queries (
    id integer NOT NULL,
    query_hash text NOT NULL,
    input_prompt text NOT NULL,
    expected_output text,
    context text,
    domain text,
    category text,
    difficulty double precision DEFAULT 0.5,
    source_type text DEFAULT 'manual'::text NOT NULL,
    source_id text,
    excluded_from_training boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    last_used_at timestamp with time zone,
    use_count integer DEFAULT 0
);


--
-- Name: held_out_queries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.held_out_queries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: held_out_queries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.held_out_queries_id_seq OWNED BY public.held_out_queries.id;


--
-- Name: http_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.http_action (
    action_id integer NOT NULL,
    template text NOT NULL,
    response_handle text,
    error_handle text
);


--
-- Name: TABLE http_action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.http_action IS 'An http api call type of action';


--
-- Name: COLUMN http_action.action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.http_action.action_id IS 'The related action';


--
-- Name: COLUMN http_action.template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.http_action.template IS 'A template that defines method,url,body,headers required to make an api call';


--
-- Name: COLUMN http_action.response_handle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.http_action.response_handle IS 'A program to take an api response and transform to an appropriate response for emitters';


--
-- Name: COLUMN http_action.error_handle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.http_action.error_handle IS 'A program to take an api response to determine if an error occurred';


--
-- Name: iceberg_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iceberg_config (
    key text NOT NULL,
    value text NOT NULL,
    description text,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: iceberg_namespace_properties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iceberg_namespace_properties (
    catalog_name character varying(255) NOT NULL,
    namespace character varying(255) NOT NULL,
    property_key character varying(255) NOT NULL,
    property_value character varying(1000) NOT NULL
);


--
-- Name: iceberg_tables; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iceberg_tables (
    catalog_name character varying(255) NOT NULL,
    table_namespace character varying(255) NOT NULL,
    table_name character varying(255) NOT NULL,
    metadata_location character varying(1000),
    previous_metadata_location character varying(1000)
);


--
-- Name: implicit_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.implicit_action (
    action_id integer NOT NULL,
    kind text NOT NULL
);


--
-- Name: TABLE implicit_action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.implicit_action IS 'An action with dynamic parameters based on the underlying model';


--
-- Name: COLUMN implicit_action.action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.implicit_action.action_id IS 'The associated action';


--
-- Name: COLUMN implicit_action.kind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.implicit_action.kind IS 'The kind of implicit action create/update/delete';


--
-- Name: kb_sync_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_sync_runs (
    id integer NOT NULL,
    target_id integer,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    status character varying(32) NOT NULL,
    files_scanned integer DEFAULT 0,
    files_uploaded integer DEFAULT 0,
    files_skipped integer DEFAULT 0,
    files_failed integer DEFAULT 0,
    bytes_uploaded bigint DEFAULT 0,
    orphans_found integer DEFAULT 0,
    resume_token character varying(255),
    error_message text,
    config_snapshot jsonb
);


--
-- Name: TABLE kb_sync_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_sync_runs IS 'Audit trail of sync operations';


--
-- Name: COLUMN kb_sync_runs.resume_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_sync_runs.resume_token IS 'Checkpoint for resuming interrupted syncs';


--
-- Name: kb_sync_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kb_sync_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kb_sync_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kb_sync_runs_id_seq OWNED BY public.kb_sync_runs.id;


--
-- Name: kb_sync_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_sync_state (
    id integer NOT NULL,
    target_id integer,
    file_path character varying(1024) NOT NULL,
    content_hash character varying(64) NOT NULL,
    size_bytes bigint NOT NULL,
    local_mtime timestamp with time zone NOT NULL,
    remote_etag character varying(64),
    synced_at timestamp with time zone,
    sync_status character varying(32) NOT NULL,
    error_message text
);


--
-- Name: TABLE kb_sync_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_sync_state IS 'Per-file sync state for incremental sync';


--
-- Name: COLUMN kb_sync_state.content_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_sync_state.content_hash IS 'SHA-256 hash of file content';


--
-- Name: COLUMN kb_sync_state.remote_etag; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_sync_state.remote_etag IS 'S3/Minio ETag after upload';


--
-- Name: kb_sync_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kb_sync_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kb_sync_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kb_sync_state_id_seq OWNED BY public.kb_sync_state.id;


--
-- Name: kb_sync_targets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_sync_targets (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    target_type character varying(32) NOT NULL,
    endpoint character varying(255) NOT NULL,
    bucket character varying(255) NOT NULL,
    region character varying(64),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    config jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE kb_sync_targets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_sync_targets IS 'S3-compatible sync targets for KB replication';


--
-- Name: COLUMN kb_sync_targets.target_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_sync_targets.target_type IS 'minio for local, s3 for AWS';


--
-- Name: COLUMN kb_sync_targets.config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_sync_targets.config IS 'Extra config: secure, prefix, storage_class';


--
-- Name: kb_sync_targets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kb_sync_targets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kb_sync_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kb_sync_targets_id_seq OWNED BY public.kb_sync_targets.id;


--
-- Name: label; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.label (
    id integer NOT NULL,
    name character varying(254) NOT NULL,
    slug character varying(254) NOT NULL,
    icon character varying(128)
);


--
-- Name: label_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.label ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.label_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: lineage_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lineage_events (
    id integer NOT NULL,
    event_type text DEFAULT 'RunEvent'::text NOT NULL,
    event_time timestamp with time zone DEFAULT now() NOT NULL,
    run_id uuid NOT NULL,
    job_namespace text NOT NULL,
    job_name text NOT NULL,
    run_state text,
    inputs jsonb DEFAULT '[]'::jsonb,
    outputs jsonb DEFAULT '[]'::jsonb,
    facets jsonb DEFAULT '{}'::jsonb,
    parent_run_id uuid,
    processed boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT lineage_events_run_state_check CHECK ((run_state = ANY (ARRAY['START'::text, 'RUNNING'::text, 'COMPLETE'::text, 'FAIL'::text, 'ABORT'::text])))
);


--
-- Name: TABLE lineage_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.lineage_events IS 'OpenLineage standard events for data lineage tracking';


--
-- Name: COLUMN lineage_events.job_namespace; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.lineage_events.job_namespace IS 'Job namespace (e.g., gaius.fetch, gaius.summarize)';


--
-- Name: COLUMN lineage_events.job_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.lineage_events.job_name IS 'Job name (e.g., arxiv, batch)';


--
-- Name: COLUMN lineage_events.inputs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.lineage_events.inputs IS 'Array of input datasets [{namespace, name, facets}]';


--
-- Name: COLUMN lineage_events.outputs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.lineage_events.outputs IS 'Array of output datasets [{namespace, name, facets}]';


--
-- Name: lineage_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.lineage_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: lineage_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.lineage_events_id_seq OWNED BY public.lineage_events.id;


--
-- Name: login_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_history (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    user_id integer NOT NULL,
    session_id character varying(254),
    device_id character(36) NOT NULL,
    device_description text NOT NULL,
    ip_address text NOT NULL
);


--
-- Name: login_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.login_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.login_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabase_cluster_lock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_cluster_lock (
    lock_name character varying(254) NOT NULL
);


--
-- Name: TABLE metabase_cluster_lock; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabase_cluster_lock IS 'A table to allow metabase instances to take locks across a cluster';


--
-- Name: COLUMN metabase_cluster_lock.lock_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_cluster_lock.lock_name IS 'a single column that can be used to a lock across a cluster';


--
-- Name: metabase_database; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_database (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    details text NOT NULL,
    engine character varying(254) NOT NULL,
    is_sample boolean DEFAULT false NOT NULL,
    is_full_sync boolean DEFAULT true NOT NULL,
    points_of_interest text,
    caveats text,
    metadata_sync_schedule character varying(254) DEFAULT '0 50 * * * ? *'::character varying NOT NULL,
    cache_field_values_schedule character varying(254) DEFAULT NULL::character varying,
    timezone character varying(254),
    is_on_demand boolean DEFAULT false NOT NULL,
    auto_run_queries boolean DEFAULT true NOT NULL,
    refingerprint boolean,
    cache_ttl integer,
    initial_sync_status character varying(32) DEFAULT 'complete'::character varying NOT NULL,
    creator_id integer,
    settings text,
    dbms_version text,
    is_audit boolean DEFAULT false NOT NULL,
    uploads_enabled boolean DEFAULT false NOT NULL,
    uploads_schema_name text,
    uploads_table_prefix text,
    is_attached_dwh boolean DEFAULT false NOT NULL,
    router_database_id integer
);


--
-- Name: COLUMN metabase_database.dbms_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.dbms_version IS 'A JSON object describing the flavor and version of the DBMS.';


--
-- Name: COLUMN metabase_database.is_audit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.is_audit IS 'Only the app db, visible to admins via auditing should have this set true.';


--
-- Name: COLUMN metabase_database.uploads_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.uploads_enabled IS 'Whether uploads are enabled for this database';


--
-- Name: COLUMN metabase_database.uploads_schema_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.uploads_schema_name IS 'The schema name for uploads';


--
-- Name: COLUMN metabase_database.uploads_table_prefix; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.uploads_table_prefix IS 'The prefix for upload table names';


--
-- Name: COLUMN metabase_database.is_attached_dwh; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.is_attached_dwh IS 'This is an attached data warehouse, do not serialize it and hide its details from the UI';


--
-- Name: COLUMN metabase_database.router_database_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_database.router_database_id IS 'The ID of the primary database for this mirror database.';


--
-- Name: metabase_database_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabase_database ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabase_database_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabase_field; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_field (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    name character varying(254) NOT NULL,
    base_type character varying(255) NOT NULL,
    semantic_type character varying(255),
    active boolean DEFAULT true NOT NULL,
    description text,
    preview_display boolean DEFAULT true NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    table_id integer NOT NULL,
    parent_id integer,
    display_name character varying(254),
    visibility_type character varying(32) DEFAULT 'normal'::character varying NOT NULL,
    fk_target_field_id integer,
    last_analyzed timestamp with time zone,
    points_of_interest text,
    caveats text,
    fingerprint text,
    fingerprint_version integer DEFAULT 0 NOT NULL,
    database_type text NOT NULL,
    has_field_values text,
    settings text,
    database_position integer DEFAULT 0 NOT NULL,
    custom_position integer DEFAULT 0 NOT NULL,
    effective_type character varying(255),
    coercion_strategy character varying(255),
    nfc_path character varying(254),
    database_required boolean DEFAULT false NOT NULL,
    json_unfolding boolean DEFAULT false NOT NULL,
    database_is_auto_increment boolean DEFAULT false NOT NULL,
    database_indexed boolean,
    database_partitioned boolean,
    is_defective_duplicate boolean DEFAULT false NOT NULL,
    unique_field_helper integer GENERATED ALWAYS AS (
CASE
    WHEN (is_defective_duplicate = true) THEN NULL::integer
    ELSE
    CASE
        WHEN (parent_id IS NULL) THEN 0
        ELSE parent_id
    END
END) STORED
);


--
-- Name: COLUMN metabase_field.json_unfolding; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field.json_unfolding IS 'Enable/disable JSON unfolding for a field';


--
-- Name: COLUMN metabase_field.database_is_auto_increment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field.database_is_auto_increment IS 'Indicates this field is auto incremented';


--
-- Name: COLUMN metabase_field.database_indexed; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field.database_indexed IS 'If the database supports indexing, this column indicate whether or not a field is indexed, or is the 1st column in a composite index';


--
-- Name: COLUMN metabase_field.database_partitioned; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field.database_partitioned IS 'Whether the table is partitioned by this field';


--
-- Name: COLUMN metabase_field.is_defective_duplicate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field.is_defective_duplicate IS 'Indicates whether column is a defective duplicate field that should never have been created.';


--
-- Name: metabase_field_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabase_field ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabase_field_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabase_field_user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_field_user_settings (
    field_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    semantic_type character varying(254),
    description text,
    display_name character varying(254),
    visibility_type character varying(32),
    fk_target_field_id integer,
    has_field_values text,
    effective_type character varying(255),
    coercion_strategy character varying(255),
    caveats text,
    points_of_interest text,
    nfc_path character varying(254),
    json_unfolding boolean,
    settings text
);


--
-- Name: TABLE metabase_field_user_settings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabase_field_user_settings IS 'Mirror table of metabase_field to keep track of user-set values (only settable fields are mirrored)';


--
-- Name: COLUMN metabase_field_user_settings.field_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.field_id IS 'The related Field';


--
-- Name: COLUMN metabase_field_user_settings.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.created_at IS 'The timestamp of when the user setting was created';


--
-- Name: COLUMN metabase_field_user_settings.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.updated_at IS 'The timestamp of when the user setting was updated';


--
-- Name: COLUMN metabase_field_user_settings.semantic_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.semantic_type IS 'User-set semantic_type for the Field';


--
-- Name: COLUMN metabase_field_user_settings.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.description IS 'User-set description for the Field';


--
-- Name: COLUMN metabase_field_user_settings.display_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.display_name IS 'User-set display_name for the Field';


--
-- Name: COLUMN metabase_field_user_settings.visibility_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.visibility_type IS 'User-set visibility_type for the Field';


--
-- Name: COLUMN metabase_field_user_settings.fk_target_field_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.fk_target_field_id IS 'User-set fk_target_field_id for the Field';


--
-- Name: COLUMN metabase_field_user_settings.has_field_values; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.has_field_values IS 'User-set has_field_values for the Field';


--
-- Name: COLUMN metabase_field_user_settings.effective_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.effective_type IS 'User-set effective_type for the Field';


--
-- Name: COLUMN metabase_field_user_settings.coercion_strategy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.coercion_strategy IS 'User-set coercion_strategy for the Field';


--
-- Name: COLUMN metabase_field_user_settings.caveats; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.caveats IS 'User-set caveats for the Field';


--
-- Name: COLUMN metabase_field_user_settings.points_of_interest; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.points_of_interest IS 'User-set points_of_interest for the Field';


--
-- Name: COLUMN metabase_field_user_settings.nfc_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.nfc_path IS 'User-set nfc_path for the Field';


--
-- Name: COLUMN metabase_field_user_settings.json_unfolding; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.json_unfolding IS 'User-set json_unfolding for the Field';


--
-- Name: COLUMN metabase_field_user_settings.settings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_field_user_settings.settings IS 'User-set settings for the Field';


--
-- Name: metabase_fieldvalues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_fieldvalues (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    "values" text,
    human_readable_values text,
    field_id integer NOT NULL,
    has_more_values boolean DEFAULT false,
    type character varying(32) DEFAULT 'full'::character varying NOT NULL,
    hash_key text,
    last_used_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN metabase_fieldvalues.last_used_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_fieldvalues.last_used_at IS 'Timestamp of when these FieldValues were last used.';


--
-- Name: metabase_fieldvalues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabase_fieldvalues ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabase_fieldvalues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabase_table; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabase_table (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    name character varying(256) NOT NULL,
    description text,
    entity_type character varying(254),
    active boolean NOT NULL,
    db_id integer NOT NULL,
    display_name character varying(256),
    visibility_type character varying(254),
    schema character varying(254),
    points_of_interest text,
    caveats text,
    show_in_getting_started boolean DEFAULT false NOT NULL,
    field_order character varying(254) DEFAULT 'database'::character varying NOT NULL,
    initial_sync_status character varying(32) DEFAULT 'complete'::character varying NOT NULL,
    is_upload boolean DEFAULT false NOT NULL,
    database_require_filter boolean,
    estimated_row_count bigint,
    view_count integer DEFAULT 0 NOT NULL,
    is_defective_duplicate boolean DEFAULT false NOT NULL,
    unique_table_helper character varying(254) GENERATED ALWAYS AS (
CASE
    WHEN (is_defective_duplicate = true) THEN NULL::character varying
    ELSE COALESCE(schema, ''::character varying)
END) STORED,
    deactivated_at timestamp with time zone,
    archived_at timestamp with time zone
);


--
-- Name: COLUMN metabase_table.is_upload; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.is_upload IS 'Was the table created from user-uploaded (i.e., from a CSV) data?';


--
-- Name: COLUMN metabase_table.database_require_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.database_require_filter IS 'If true, the table requires a filter to be able to query it';


--
-- Name: COLUMN metabase_table.estimated_row_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.estimated_row_count IS 'The estimated row count';


--
-- Name: COLUMN metabase_table.view_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.view_count IS 'Keeps a running count of card views';


--
-- Name: COLUMN metabase_table.is_defective_duplicate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.is_defective_duplicate IS 'Indicates whether the table is a defective duplicate that should never have been created.';


--
-- Name: COLUMN metabase_table.deactivated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.deactivated_at IS 'The timestamp when the table was deactivated (active changed from true to false)';


--
-- Name: COLUMN metabase_table.archived_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabase_table.archived_at IS 'The timestamp when the table was marked for archiving';


--
-- Name: metabase_table_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabase_table ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabase_table_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabot (
    id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    entity_id character(21),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE metabot; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabot IS 'Metabot configuration';


--
-- Name: COLUMN metabot.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot.name IS 'The name of the metabot';


--
-- Name: COLUMN metabot.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot.description IS 'Description of the metabot';


--
-- Name: COLUMN metabot.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot.entity_id IS 'Random NanoID tag for unique identity';


--
-- Name: COLUMN metabot.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot.created_at IS 'The timestamp of when the metabot was created';


--
-- Name: COLUMN metabot.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot.updated_at IS 'The timestamp of when the metabot was updated';


--
-- Name: metabot_conversation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabot_conversation (
    id character varying(36) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    user_id integer NOT NULL,
    summary text,
    state text
);


--
-- Name: TABLE metabot_conversation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabot_conversation IS 'Table to store metabot conversation messages';


--
-- Name: COLUMN metabot_conversation.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_conversation.id IS 'Conversation UUID';


--
-- Name: COLUMN metabot_conversation.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_conversation.created_at IS 'created_at';


--
-- Name: COLUMN metabot_conversation.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_conversation.user_id IS 'Reference to user having the conversation';


--
-- Name: COLUMN metabot_conversation.summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_conversation.summary IS 'Auto-generated summary for the conversation';


--
-- Name: COLUMN metabot_conversation.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_conversation.state IS 'Metabot conversation state';


--
-- Name: metabot_entity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabot_entity (
    id integer NOT NULL,
    metabot_id integer NOT NULL,
    model character varying(32) NOT NULL,
    model_id integer NOT NULL,
    entity_id character(21),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE metabot_entity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabot_entity IS 'Entities associated with a metabot';


--
-- Name: COLUMN metabot_entity.metabot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_entity.metabot_id IS 'The metabot this entity is associated with';


--
-- Name: COLUMN metabot_entity.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_entity.model IS 'The type of model this entity references';


--
-- Name: COLUMN metabot_entity.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_entity.model_id IS 'The ID of the model this entity references';


--
-- Name: COLUMN metabot_entity.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_entity.entity_id IS 'Random NanoID tag for unique identity';


--
-- Name: COLUMN metabot_entity.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_entity.created_at IS 'The timestamp of when the entity was created';


--
-- Name: metabot_entity_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabot_entity ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabot_entity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabot ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabot_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabot_message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabot_message (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    profile_id text NOT NULL,
    role character varying(20) NOT NULL,
    data text NOT NULL,
    usage text,
    total_tokens integer NOT NULL,
    conversation_id character varying(36) NOT NULL
);


--
-- Name: TABLE metabot_message; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabot_message IS 'Table to store metabot conversation messages';


--
-- Name: COLUMN metabot_message.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.id IS 'Autoincrement PK';


--
-- Name: COLUMN metabot_message.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.created_at IS 'created_at';


--
-- Name: COLUMN metabot_message.profile_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.profile_id IS 'ai-service profile used to perform the conversation';


--
-- Name: COLUMN metabot_message.role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.role IS 'Role of the sender';


--
-- Name: COLUMN metabot_message.data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.data IS 'Full message content';


--
-- Name: COLUMN metabot_message.usage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.usage IS 'Can be null for user messages; {"<model-name>": {"prompt": 1, "completion": 2}}';


--
-- Name: COLUMN metabot_message.total_tokens; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.total_tokens IS 'A sum of all prompt+completion from `usage`';


--
-- Name: COLUMN metabot_message.conversation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_message.conversation_id IS 'Reference to a conversation';


--
-- Name: metabot_message_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabot_message ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabot_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metabot_prompt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metabot_prompt (
    id integer NOT NULL,
    metabot_entity_id integer NOT NULL,
    model character varying(32) NOT NULL,
    card_id integer NOT NULL,
    entity_id character(21),
    prompt text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE metabot_prompt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.metabot_prompt IS 'Prompts of a metabot entity';


--
-- Name: COLUMN metabot_prompt.metabot_entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.metabot_entity_id IS 'The metabot this entity is associated with';


--
-- Name: COLUMN metabot_prompt.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.model IS 'The type of the entity this prompt is about';


--
-- Name: COLUMN metabot_prompt.card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.card_id IS 'The ID of the model or metric this prompt is about';


--
-- Name: COLUMN metabot_prompt.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.entity_id IS 'Random NanoID tag for unique identity';


--
-- Name: COLUMN metabot_prompt.prompt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.prompt IS 'The text of the prompt';


--
-- Name: COLUMN metabot_prompt.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.created_at IS 'The timestamp of when the prompt was created';


--
-- Name: COLUMN metabot_prompt.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.metabot_prompt.updated_at IS 'The timestamp of when the prompt was updated';


--
-- Name: metabot_prompt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metabot_prompt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metabot_prompt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metric; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metric (
    id integer NOT NULL,
    table_id integer NOT NULL,
    creator_id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    archived boolean DEFAULT false NOT NULL,
    definition text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    points_of_interest text,
    caveats text,
    how_is_this_calculated text,
    show_in_getting_started boolean DEFAULT false NOT NULL,
    entity_id character(21)
);


--
-- Name: metric_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metric ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metric_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metric_important_field; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metric_important_field (
    id integer NOT NULL,
    metric_id integer NOT NULL,
    field_id integer NOT NULL
);


--
-- Name: metric_important_field_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metric_important_field ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.metric_important_field_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mlops_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mlops_events (
    id integer NOT NULL,
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    category character varying(64) NOT NULL,
    severity public.aiops_severity NOT NULL,
    status public.aiops_status DEFAULT 'detected'::public.aiops_status NOT NULL,
    agent_id character varying(64),
    model_version character varying(128),
    description text NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb,
    remediation_action character varying(255),
    remediation_result jsonb,
    resolved_at timestamp with time zone,
    failure_mode_id character varying(32),
    runtime_severity integer,
    runtime_occurrence integer,
    runtime_detection integer,
    rpn_score integer,
    CONSTRAINT mlops_events_rpn_score_check CHECK (((rpn_score >= 1) AND (rpn_score <= 1000))),
    CONSTRAINT mlops_events_runtime_detection_check CHECK (((runtime_detection >= 1) AND (runtime_detection <= 10))),
    CONSTRAINT mlops_events_runtime_occurrence_check CHECK (((runtime_occurrence >= 1) AND (runtime_occurrence <= 10))),
    CONSTRAINT mlops_events_runtime_severity_check CHECK (((runtime_severity >= 1) AND (runtime_severity <= 10)))
);


--
-- Name: TABLE mlops_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.mlops_events IS 'Model lifecycle events for evolution and deployment tracking';


--
-- Name: COLUMN mlops_events.agent_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.mlops_events.agent_id IS 'Agent being affected: leader, worker, critic, etc.';


--
-- Name: mlops_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mlops_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mlops_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mlops_events_id_seq OWNED BY public.mlops_events.id;


--
-- Name: model_index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_index (
    id integer NOT NULL,
    model_id integer,
    pk_ref text NOT NULL,
    value_ref text NOT NULL,
    schedule text NOT NULL,
    state text NOT NULL,
    indexed_at timestamp with time zone,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    creator_id integer NOT NULL
);


--
-- Name: TABLE model_index; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.model_index IS 'Used to keep track of which models have indexed columns.';


--
-- Name: COLUMN model_index.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.model_id IS 'The ID of the indexed model.';


--
-- Name: COLUMN model_index.pk_ref; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.pk_ref IS 'Serialized JSON of the primary key field ref.';


--
-- Name: COLUMN model_index.value_ref; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.value_ref IS 'Serialized JSON of the label field ref.';


--
-- Name: COLUMN model_index.schedule; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.schedule IS 'The cron schedule for when value syncing should happen.';


--
-- Name: COLUMN model_index.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.state IS 'The status of the index: initializing, indexed, error, overflow.';


--
-- Name: COLUMN model_index.indexed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.indexed_at IS 'When the status changed';


--
-- Name: COLUMN model_index.error; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.error IS 'The error message if the status is error.';


--
-- Name: COLUMN model_index.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.created_at IS 'The timestamp of when these changes were made.';


--
-- Name: COLUMN model_index.creator_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index.creator_id IS 'ID of the user who created the event';


--
-- Name: model_index_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.model_index ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.model_index_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: model_index_value; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_index_value (
    model_index_id integer,
    model_pk bigint NOT NULL,
    name text NOT NULL
);


--
-- Name: TABLE model_index_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.model_index_value IS 'Used to keep track of the values indexed in a model';


--
-- Name: COLUMN model_index_value.model_index_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index_value.model_index_id IS 'The ID of the indexed model.';


--
-- Name: COLUMN model_index_value.model_pk; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index_value.model_pk IS 'The primary key of the indexed value';


--
-- Name: COLUMN model_index_value.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_index_value.name IS 'The label to display identifying the indexed value.';


--
-- Name: moderation_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.moderation_review (
    id integer NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    status character varying(255),
    text text,
    moderated_item_id integer NOT NULL,
    moderated_item_type character varying(255) NOT NULL,
    moderator_id integer NOT NULL,
    most_recent boolean NOT NULL
);


--
-- Name: moderation_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.moderation_review ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.moderation_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: native_query_snippet; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.native_query_snippet (
    id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    content text NOT NULL,
    creator_id integer NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    collection_id integer,
    entity_id character(21)
);


--
-- Name: native_query_snippet_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.native_query_snippet ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.native_query_snippet_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification (
    id integer NOT NULL,
    payload_type character varying(64) NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    internal_id character varying(254),
    payload_id integer,
    creator_id integer
);


--
-- Name: TABLE notification; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification IS 'join table that connect notification subscriptions and notification handlers';


--
-- Name: COLUMN notification.payload_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.payload_type IS 'the type of the payload';


--
-- Name: COLUMN notification.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.active IS 'whether the notification is active';


--
-- Name: COLUMN notification.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.created_at IS 'The timestamp of when the notification was created';


--
-- Name: COLUMN notification.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.updated_at IS 'The timestamp of when the notification was updated';


--
-- Name: COLUMN notification.internal_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.internal_id IS 'the internal id of the notification';


--
-- Name: COLUMN notification.payload_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.payload_id IS 'the internal id of the notification';


--
-- Name: COLUMN notification.creator_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification.creator_id IS 'the id of the creator';


--
-- Name: notification_card; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_card (
    id integer NOT NULL,
    card_id integer,
    send_once boolean DEFAULT false NOT NULL,
    send_condition character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE notification_card; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_card IS 'Card related notifications';


--
-- Name: COLUMN notification_card.card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_card.card_id IS 'the card that the alert is connected to';


--
-- Name: COLUMN notification_card.send_once; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_card.send_once IS 'whether the alert should only run once';


--
-- Name: COLUMN notification_card.send_condition; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_card.send_condition IS 'the condition of the alert';


--
-- Name: COLUMN notification_card.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_card.created_at IS 'The timestamp of when the recipient was created';


--
-- Name: COLUMN notification_card.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_card.updated_at IS 'The timestamp of when the recipient was updated';


--
-- Name: notification_card_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_card ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_card_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_handler; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_handler (
    id integer NOT NULL,
    channel_type character varying(64) NOT NULL,
    notification_id integer NOT NULL,
    channel_id integer,
    template_id integer,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE notification_handler; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_handler IS 'which channel to send the notification to';


--
-- Name: COLUMN notification_handler.channel_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.channel_type IS 'the type of the channel, like :channel/email, :channel/slack';


--
-- Name: COLUMN notification_handler.notification_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.notification_id IS 'the notification that the handler is connected to';


--
-- Name: COLUMN notification_handler.channel_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.channel_id IS 'the channel that the handler is connected to';


--
-- Name: COLUMN notification_handler.template_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.template_id IS 'the template that the handler is connected to';


--
-- Name: COLUMN notification_handler.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.active IS 'whether the handler is active';


--
-- Name: COLUMN notification_handler.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.created_at IS 'The timestamp of when the handler was created';


--
-- Name: COLUMN notification_handler.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_handler.updated_at IS 'The timestamp of when the handler was updated';


--
-- Name: notification_handler_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_handler ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_handler_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_recipient; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_recipient (
    id integer NOT NULL,
    notification_handler_id integer NOT NULL,
    type character varying(64) NOT NULL,
    user_id integer,
    permissions_group_id integer,
    details text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE notification_recipient; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_recipient IS 'who should receive the notification';


--
-- Name: COLUMN notification_recipient.notification_handler_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.notification_handler_id IS 'the handler that the recipient is connected to';


--
-- Name: COLUMN notification_recipient.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.type IS 'the type of the recipient';


--
-- Name: COLUMN notification_recipient.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.user_id IS 'a user if the recipient has type user';


--
-- Name: COLUMN notification_recipient.permissions_group_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.permissions_group_id IS 'a permissions group if the recipient has type permissions_group';


--
-- Name: COLUMN notification_recipient.details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.details IS 'custom details for the recipient';


--
-- Name: COLUMN notification_recipient.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.created_at IS 'The timestamp of when the recipient was created';


--
-- Name: COLUMN notification_recipient.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_recipient.updated_at IS 'The timestamp of when the recipient was updated';


--
-- Name: notification_recipient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_recipient ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_recipient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_subscription; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_subscription (
    id integer NOT NULL,
    notification_id integer NOT NULL,
    type character varying(64) NOT NULL,
    event_name character varying(64),
    created_at timestamp with time zone NOT NULL,
    cron_schedule character varying(128),
    ui_display_type character varying(32)
);


--
-- Name: TABLE notification_subscription; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_subscription IS 'which type of trigger a notification is subscribed to';


--
-- Name: COLUMN notification_subscription.notification_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.notification_id IS 'the notification that the subscription is connected to';


--
-- Name: COLUMN notification_subscription.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.type IS 'the type of the subscription';


--
-- Name: COLUMN notification_subscription.event_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.event_name IS 'the event name of subscriptions with type :notification-subscription/system-event';


--
-- Name: COLUMN notification_subscription.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.created_at IS 'The timestamp of when the subscription was created';


--
-- Name: COLUMN notification_subscription.cron_schedule; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.cron_schedule IS 'the cron schedule for the subscription';


--
-- Name: COLUMN notification_subscription.ui_display_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notification_subscription.ui_display_type IS 'the display of the subscription, used for the UI only';


--
-- Name: notification_subscription_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_subscription ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_subscription_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: objective_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.objective_verifications (
    id integer NOT NULL,
    run_id text NOT NULL,
    objective_name text NOT NULL,
    objective_path text NOT NULL,
    domain text DEFAULT 'kb'::text NOT NULL,
    document_path text,
    document_hash text,
    verdict text NOT NULL,
    accuracy double precision NOT NULL,
    reward double precision NOT NULL,
    gates_total integer NOT NULL,
    gates_passed integer NOT NULL,
    gate_results jsonb DEFAULT '[]'::jsonb NOT NULL,
    thread_id text NOT NULL,
    evidence_path text,
    iceberg_table text DEFAULT 'hx://rase.evidence'::text,
    eligible_for_training boolean DEFAULT true,
    calibration_id integer,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    duration_ms integer,
    kb_root text,
    kb_document_count integer,
    CONSTRAINT objective_verifications_accuracy_check CHECK (((accuracy >= (0.0)::double precision) AND (accuracy <= (1.0)::double precision))),
    CONSTRAINT objective_verifications_verdict_check CHECK ((verdict = ANY (ARRAY['pass'::text, 'fail'::text, 'inconclusive'::text, 'error'::text])))
);


--
-- Name: objective_verification_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.objective_verification_summary AS
 SELECT objective_name,
    domain,
    count(*) AS total_runs,
    count(*) FILTER (WHERE (verdict = 'pass'::text)) AS pass_count,
    count(*) FILTER (WHERE (verdict = 'fail'::text)) AS fail_count,
    avg(accuracy) AS avg_accuracy,
    avg(reward) AS avg_reward,
    avg(duration_ms) AS avg_duration_ms,
    max(started_at) AS last_run
   FROM public.objective_verifications
  GROUP BY objective_name, domain;


--
-- Name: objective_verifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.objective_verifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: objective_verifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.objective_verifications_id_seq OWNED BY public.objective_verifications.id;


--
-- Name: optimization_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.optimization_runs (
    id integer NOT NULL,
    agent_id text NOT NULL,
    strategy text NOT NULL,
    objectives jsonb NOT NULL,
    config jsonb DEFAULT '{}'::jsonb,
    status text DEFAULT 'running'::text,
    generations_completed integer DEFAULT 0,
    pareto_front jsonb DEFAULT '[]'::jsonb,
    best_version_id text,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    notes text
);


--
-- Name: optimization_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.optimization_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: optimization_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.optimization_runs_id_seq OWNED BY public.optimization_runs.id;


--
-- Name: paper_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.paper_scores (
    id integer NOT NULL,
    arxiv_id character varying(64) NOT NULL,
    rubric_id integer,
    overall_score double precision NOT NULL,
    criteria_scores jsonb NOT NULL,
    model_used character varying(64) NOT NULL,
    reasoning text,
    confidence double precision,
    metaflow_run_id character varying(128),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE paper_scores; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.paper_scores IS 'LLM-scored paper relevance with rubric lineage';


--
-- Name: paper_scores_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.paper_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: paper_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.paper_scores_id_seq OWNED BY public.paper_scores.id;


--
-- Name: parameter_card; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parameter_card (
    id integer NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    card_id integer NOT NULL,
    parameterized_object_type character varying(32) NOT NULL,
    parameterized_object_id integer NOT NULL,
    parameter_id character varying(36) NOT NULL
);


--
-- Name: TABLE parameter_card; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.parameter_card IS 'Join table connecting cards to entities (dashboards, other cards, etc.) that use the values generated by the card for filter values';


--
-- Name: COLUMN parameter_card.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.updated_at IS 'most recent modification time';


--
-- Name: COLUMN parameter_card.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.created_at IS 'creation time';


--
-- Name: COLUMN parameter_card.card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.card_id IS 'ID of the card generating the values';


--
-- Name: COLUMN parameter_card.parameterized_object_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.parameterized_object_type IS 'Type of the entity consuming the values (dashboard, card, etc.)';


--
-- Name: COLUMN parameter_card.parameterized_object_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.parameterized_object_id IS 'ID of the entity consuming the values';


--
-- Name: COLUMN parameter_card.parameter_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.parameter_card.parameter_id IS 'The parameter ID';


--
-- Name: parameter_card_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.parameter_card ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.parameter_card_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions (
    id integer NOT NULL,
    object character varying(254) NOT NULL,
    group_id integer NOT NULL,
    perm_value character varying(64),
    perm_type character varying(64),
    collection_id integer
);


--
-- Name: COLUMN permissions.perm_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions.perm_value IS 'The value of the permission';


--
-- Name: COLUMN permissions.perm_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions.perm_type IS 'The type of the permission';


--
-- Name: COLUMN permissions.collection_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions.collection_id IS 'The linked collection, if applicable';


--
-- Name: permissions_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions_group (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    entity_id character(21),
    magic_group_type character varying(254),
    is_tenant_group boolean DEFAULT false NOT NULL
);


--
-- Name: COLUMN permissions_group.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions_group.entity_id IS 'NanoID tag for each user';


--
-- Name: COLUMN permissions_group.magic_group_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions_group.magic_group_type IS 'The magic_group_type of the permissions_group';


--
-- Name: COLUMN permissions_group.is_tenant_group; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.permissions_group.is_tenant_group IS 'true iff this is a Tenant Group';


--
-- Name: permissions_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.permissions_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.permissions_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: permissions_group_membership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions_group_membership (
    id integer NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL,
    is_group_manager boolean DEFAULT false NOT NULL
);


--
-- Name: permissions_group_membership_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.permissions_group_membership ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.permissions_group_membership_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: permissions_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions_revision (
    id integer NOT NULL,
    before text NOT NULL,
    after text NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    remark text
);


--
-- Name: permissions_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.permissions_revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.permissions_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: persisted_info; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persisted_info (
    id integer NOT NULL,
    database_id integer NOT NULL,
    card_id integer,
    question_slug text NOT NULL,
    table_name text NOT NULL,
    definition text,
    query_hash text,
    active boolean DEFAULT false NOT NULL,
    state text NOT NULL,
    refresh_begin timestamp with time zone NOT NULL,
    refresh_end timestamp with time zone,
    state_change_at timestamp with time zone,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    creator_id integer
);


--
-- Name: persisted_info_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.persisted_info ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.persisted_info_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: profile_content; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profile_content (
    profile_id integer NOT NULL,
    content_id integer NOT NULL,
    relevance_score double precision DEFAULT 0.5,
    manually_curated boolean DEFAULT false,
    added_at timestamp with time zone DEFAULT now()
);


--
-- Name: profile_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profile_domains (
    id integer NOT NULL,
    profile_id integer NOT NULL,
    name text NOT NULL,
    display_name text,
    description text,
    domain_text text,
    kb_path_prefixes text[] DEFAULT '{}'::text[],
    search_boost double precision DEFAULT 1.0,
    is_active boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE profile_domains; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.profile_domains IS 'Domains are profile-scoped focus areas. The same domain name can exist in multiple profiles.';


--
-- Name: COLUMN profile_domains.domain_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profile_domains.domain_text IS 'Unstructured text for agent prompting. Describes domain concepts, terminology, and goals.';


--
-- Name: COLUMN profile_domains.is_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profile_domains.is_active IS 'Only one domain can be active per profile at a time. Used for context switching.';


--
-- Name: profile_domains_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.profile_domains_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: profile_domains_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.profile_domains_id_seq OWNED BY public.profile_domains.id;


--
-- Name: profile_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profile_sources (
    profile_id integer NOT NULL,
    source_id integer NOT NULL,
    weight double precision DEFAULT 1.0
);


--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profiles (
    id integer NOT NULL,
    name text NOT NULL,
    description text,
    feed_config jsonb DEFAULT '{}'::jsonb,
    active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    profile_text text,
    kb_path_prefixes text[] DEFAULT '{}'::text[],
    search_boost double precision DEFAULT 1.0,
    is_default boolean DEFAULT false
);


--
-- Name: COLUMN profiles.profile_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profiles.profile_text IS 'Unstructured text for agent prompting context. Describes profile purpose, conventions, priorities.';


--
-- Name: COLUMN profiles.kb_path_prefixes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profiles.kb_path_prefixes IS 'KB path prefixes associated with this profile. Used for search boosting and organization.';


--
-- Name: COLUMN profiles.search_boost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profiles.search_boost IS 'Default search result boost multiplier for content matching profile paths (1.0 = neutral).';


--
-- Name: COLUMN profiles.is_default; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.profiles.is_default IS 'Only one profile can be the default. Used when no profile is specified on CLI.';


--
-- Name: profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.profiles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.profiles_id_seq OWNED BY public.profiles.id;


--
-- Name: pulse; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pulse (
    id integer NOT NULL,
    creator_id integer NOT NULL,
    name character varying(254),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    skip_if_empty boolean DEFAULT false NOT NULL,
    alert_condition character varying(254),
    alert_first_only boolean,
    alert_above_goal boolean,
    collection_id integer,
    collection_position smallint,
    archived boolean DEFAULT false,
    dashboard_id integer,
    parameters text NOT NULL,
    entity_id character(21)
);


--
-- Name: pulse_card; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pulse_card (
    id integer NOT NULL,
    pulse_id integer NOT NULL,
    card_id integer NOT NULL,
    "position" integer NOT NULL,
    include_csv boolean DEFAULT false NOT NULL,
    include_xls boolean DEFAULT false NOT NULL,
    dashboard_card_id integer,
    entity_id character(21),
    format_rows boolean DEFAULT true,
    pivot_results boolean DEFAULT false
);


--
-- Name: COLUMN pulse_card.format_rows; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pulse_card.format_rows IS 'Whether or not to apply formatting to the rows of the export';


--
-- Name: COLUMN pulse_card.pivot_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pulse_card.pivot_results IS 'Whether or not to apply pivot processing to the rows of the export';


--
-- Name: pulse_card_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.pulse_card ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.pulse_card_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pulse_channel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pulse_channel (
    id integer NOT NULL,
    pulse_id integer NOT NULL,
    channel_type character varying(32) NOT NULL,
    details text NOT NULL,
    schedule_type character varying(32) NOT NULL,
    schedule_hour integer,
    schedule_day character varying(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    schedule_frame character varying(32),
    enabled boolean DEFAULT true NOT NULL,
    entity_id character(21),
    channel_id integer
);


--
-- Name: COLUMN pulse_channel.channel_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pulse_channel.channel_id IS 'The channel ID';


--
-- Name: pulse_channel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.pulse_channel ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.pulse_channel_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pulse_channel_recipient; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pulse_channel_recipient (
    id integer NOT NULL,
    pulse_channel_id integer NOT NULL,
    user_id integer NOT NULL
);


--
-- Name: pulse_channel_recipient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.pulse_channel_recipient ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.pulse_channel_recipient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pulse_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.pulse ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.pulse_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: qrtz_blob_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_blob_triggers (
    sched_name character varying(120) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    blob_data bytea
);


--
-- Name: qrtz_calendars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_calendars (
    sched_name character varying(120) NOT NULL,
    calendar_name character varying(200) NOT NULL,
    calendar bytea NOT NULL
);


--
-- Name: qrtz_cron_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_cron_triggers (
    sched_name character varying(120) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    cron_expression character varying(120) NOT NULL,
    time_zone_id character varying(80)
);


--
-- Name: qrtz_fired_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_fired_triggers (
    sched_name character varying(120) NOT NULL,
    entry_id character varying(95) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    instance_name character varying(200) NOT NULL,
    fired_time bigint NOT NULL,
    sched_time bigint,
    priority integer NOT NULL,
    state character varying(16) NOT NULL,
    job_name character varying(200),
    job_group character varying(200),
    is_nonconcurrent boolean,
    requests_recovery boolean
);


--
-- Name: qrtz_job_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_job_details (
    sched_name character varying(120) NOT NULL,
    job_name character varying(200) NOT NULL,
    job_group character varying(200) NOT NULL,
    description character varying(250),
    job_class_name character varying(250) NOT NULL,
    is_durable boolean NOT NULL,
    is_nonconcurrent boolean NOT NULL,
    is_update_data boolean NOT NULL,
    requests_recovery boolean NOT NULL,
    job_data bytea
);


--
-- Name: qrtz_locks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_locks (
    sched_name character varying(120) NOT NULL,
    lock_name character varying(40) NOT NULL
);


--
-- Name: qrtz_paused_trigger_grps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_paused_trigger_grps (
    sched_name character varying(120) NOT NULL,
    trigger_group character varying(200) NOT NULL
);


--
-- Name: qrtz_scheduler_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_scheduler_state (
    sched_name character varying(120) NOT NULL,
    instance_name character varying(200) NOT NULL,
    last_checkin_time bigint NOT NULL,
    checkin_interval bigint NOT NULL
);


--
-- Name: qrtz_simple_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_simple_triggers (
    sched_name character varying(120) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    repeat_count bigint NOT NULL,
    repeat_interval bigint NOT NULL,
    times_triggered bigint NOT NULL
);


--
-- Name: qrtz_simprop_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_simprop_triggers (
    sched_name character varying(120) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    str_prop_1 character varying(512),
    str_prop_2 character varying(512),
    str_prop_3 character varying(512),
    int_prop_1 integer,
    int_prop_2 integer,
    long_prop_1 bigint,
    long_prop_2 bigint,
    dec_prop_1 numeric(13,4),
    dec_prop_2 numeric(13,4),
    bool_prop_1 boolean,
    bool_prop_2 boolean
);


--
-- Name: qrtz_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qrtz_triggers (
    sched_name character varying(120) NOT NULL,
    trigger_name character varying(200) NOT NULL,
    trigger_group character varying(200) NOT NULL,
    job_name character varying(200) NOT NULL,
    job_group character varying(200) NOT NULL,
    description character varying(250),
    next_fire_time bigint,
    prev_fire_time bigint,
    priority integer,
    trigger_state character varying(16) NOT NULL,
    trigger_type character varying(8) NOT NULL,
    start_time bigint NOT NULL,
    end_time bigint,
    calendar_name character varying(200),
    misfire_instr smallint,
    job_data bytea
);


--
-- Name: query; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query (
    query_hash bytea NOT NULL,
    average_execution_time integer NOT NULL,
    query text
);


--
-- Name: query_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_action (
    action_id integer NOT NULL,
    database_id integer NOT NULL,
    dataset_query text NOT NULL
);


--
-- Name: TABLE query_action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.query_action IS 'A readwrite query type of action';


--
-- Name: COLUMN query_action.action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_action.action_id IS 'The related action';


--
-- Name: COLUMN query_action.database_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_action.database_id IS 'The associated database';


--
-- Name: COLUMN query_action.dataset_query; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_action.dataset_query IS 'The MBQL writeback query';


--
-- Name: query_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_cache (
    query_hash bytea NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    results bytea NOT NULL
);


--
-- Name: query_execution; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_execution (
    id integer NOT NULL,
    hash bytea NOT NULL,
    started_at timestamp with time zone NOT NULL,
    running_time integer NOT NULL,
    result_rows integer NOT NULL,
    native boolean NOT NULL,
    context character varying(32),
    error text,
    executor_id integer,
    card_id integer,
    dashboard_id integer,
    pulse_id integer,
    database_id integer,
    cache_hit boolean,
    action_id integer,
    is_sandboxed boolean,
    cache_hash bytea,
    embedding_client character varying(254),
    embedding_version character varying(254),
    parameterized boolean
);


--
-- Name: COLUMN query_execution.action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.action_id IS 'The ID of the action associated with this query execution, if any.';


--
-- Name: COLUMN query_execution.is_sandboxed; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.is_sandboxed IS 'Is query from a sandboxed user';


--
-- Name: COLUMN query_execution.cache_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.cache_hash IS 'Hash of normalized query, calculated in middleware.cache';


--
-- Name: COLUMN query_execution.embedding_client; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.embedding_client IS 'Used by the embedding team to track SDK usage';


--
-- Name: COLUMN query_execution.embedding_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.embedding_version IS 'Used by the embedding team to track SDK version usage';


--
-- Name: COLUMN query_execution.parameterized; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_execution.parameterized IS 'Whether or not the query has parameters with non-nil values';


--
-- Name: query_execution_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.query_execution ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.query_execution_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: query_field; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_field (
    id integer NOT NULL,
    card_id integer NOT NULL,
    field_id integer,
    explicit_reference boolean DEFAULT true NOT NULL,
    "column" character varying(254) NOT NULL,
    "table" character varying(254),
    table_id integer,
    schema character varying(254)
);


--
-- Name: TABLE query_field; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.query_field IS 'Fields used by a card''s query';


--
-- Name: COLUMN query_field.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.id IS 'PK';


--
-- Name: COLUMN query_field.card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.card_id IS 'referenced card';


--
-- Name: COLUMN query_field.field_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.field_id IS 'referenced field';


--
-- Name: COLUMN query_field.explicit_reference; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.explicit_reference IS 'Is the Field referenced directly or via a wildcard';


--
-- Name: COLUMN query_field."column"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field."column" IS 'name of the table or card being referenced';


--
-- Name: COLUMN query_field."table"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field."table" IS 'name of the table or card being referenced';


--
-- Name: COLUMN query_field.table_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.table_id IS 'track the table directly, in case the field does not exist';


--
-- Name: COLUMN query_field.schema; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_field.schema IS 'name of the schema of the table being referenced';


--
-- Name: query_field_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.query_field ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.query_field_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: query_table; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.query_table (
    id integer NOT NULL,
    card_id integer NOT NULL,
    table_id integer,
    schema character varying(254),
    "table" character varying(254) NOT NULL
);


--
-- Name: TABLE query_table; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.query_table IS 'Tables used by a card''s query';


--
-- Name: COLUMN query_table.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_table.id IS 'PK';


--
-- Name: COLUMN query_table.card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_table.card_id IS 'referenced card';


--
-- Name: COLUMN query_table.table_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_table.table_id IS 'referenced field';


--
-- Name: COLUMN query_table.schema; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_table.schema IS 'name of the schema of the table being referenced';


--
-- Name: COLUMN query_table."table"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_table."table" IS 'name of the table or card being referenced';


--
-- Name: query_table_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.query_table ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.query_table_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: recent_views; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recent_views (
    id integer NOT NULL,
    user_id integer NOT NULL,
    model character varying(16) NOT NULL,
    model_id integer NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    context character varying(256) DEFAULT 'view'::character varying NOT NULL
);


--
-- Name: TABLE recent_views; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.recent_views IS 'Used to store recently viewed objects for each user';


--
-- Name: COLUMN recent_views.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recent_views.user_id IS 'The user associated with this view';


--
-- Name: COLUMN recent_views.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recent_views.model IS 'The name of the model that was viewed';


--
-- Name: COLUMN recent_views.model_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recent_views.model_id IS 'The ID of the model that was viewed';


--
-- Name: COLUMN recent_views."timestamp"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recent_views."timestamp" IS 'The time a view was recorded';


--
-- Name: COLUMN recent_views.context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recent_views.context IS 'The contextual action that netted a recent view.';


--
-- Name: recent_views_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.recent_views ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.recent_views_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: remediation_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.remediation_approvals (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    event_type character varying(16) NOT NULL,
    event_id integer NOT NULL,
    action_command character varying(255) NOT NULL,
    description text NOT NULL,
    severity public.aiops_severity NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying,
    approved_by character varying(64),
    approved_at timestamp with time zone,
    rejection_reason text,
    failure_mode_id character varying(32),
    rpn_score integer,
    rpn_breakdown jsonb
);


--
-- Name: TABLE remediation_approvals; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.remediation_approvals IS 'Queue for high-severity actions requiring user approval';


--
-- Name: COLUMN remediation_approvals.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remediation_approvals.expires_at IS 'Auto-reject if not acted upon by this time';


--
-- Name: remediation_approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.remediation_approvals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: remediation_approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.remediation_approvals_id_seq OWNED BY public.remediation_approvals.id;


--
-- Name: report_card; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_card (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    display character varying(254) NOT NULL,
    dataset_query text NOT NULL,
    visualization_settings text NOT NULL,
    creator_id integer NOT NULL,
    database_id integer NOT NULL,
    table_id integer,
    query_type character varying(16),
    archived boolean DEFAULT false NOT NULL,
    collection_id integer,
    public_uuid character(36),
    made_public_by_id integer,
    enable_embedding boolean DEFAULT false NOT NULL,
    embedding_params text,
    cache_ttl integer,
    result_metadata text,
    collection_position smallint,
    entity_id character(21),
    parameters text,
    parameter_mappings text,
    collection_preview boolean DEFAULT true NOT NULL,
    metabase_version character varying(100),
    type character varying(16) DEFAULT 'question'::character varying NOT NULL,
    initially_published_at timestamp with time zone,
    cache_invalidated_at timestamp with time zone,
    last_used_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    view_count integer DEFAULT 0 NOT NULL,
    archived_directly boolean DEFAULT false NOT NULL,
    dataset_query_metrics_v2_migration_backup text,
    source_card_id integer,
    dashboard_id integer,
    card_schema integer DEFAULT 20 NOT NULL
);


--
-- Name: COLUMN report_card.metabase_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.metabase_version IS 'Metabase version used to create the card.';


--
-- Name: COLUMN report_card.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.type IS 'The type of card, could be ''question'', ''model'', ''metric''';


--
-- Name: COLUMN report_card.initially_published_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.initially_published_at IS 'The timestamp when the card was first published in a static embed';


--
-- Name: COLUMN report_card.cache_invalidated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.cache_invalidated_at IS 'An invalidation time that can supersede cache_config.invalidated_at';


--
-- Name: COLUMN report_card.last_used_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.last_used_at IS 'The timestamp of when the card is last used';


--
-- Name: COLUMN report_card.view_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.view_count IS 'Keeps a running count of card views';


--
-- Name: COLUMN report_card.archived_directly; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.archived_directly IS 'Was this thing trashed directly';


--
-- Name: COLUMN report_card.dataset_query_metrics_v2_migration_backup; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.dataset_query_metrics_v2_migration_backup IS 'The copy of dataset_query before the metrics v2 migration';


--
-- Name: COLUMN report_card.source_card_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.source_card_id IS 'The ID of the model or question this card is based on';


--
-- Name: COLUMN report_card.dashboard_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.dashboard_id IS 'The dashboard that owns the card, if it is a dashboard-internal card.';


--
-- Name: COLUMN report_card.card_schema; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_card.card_schema IS 'Arbitrary revision number for how we store queries in report_card';


--
-- Name: report_card_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.report_card ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.report_card_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: report_cardfavorite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_cardfavorite (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    card_id integer NOT NULL,
    owner_id integer NOT NULL
);


--
-- Name: report_cardfavorite_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.report_cardfavorite ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.report_cardfavorite_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: report_dashboard; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_dashboard (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    creator_id integer NOT NULL,
    parameters text NOT NULL,
    points_of_interest text,
    caveats text,
    show_in_getting_started boolean DEFAULT false NOT NULL,
    public_uuid character(36),
    made_public_by_id integer,
    enable_embedding boolean DEFAULT false NOT NULL,
    embedding_params text,
    archived boolean DEFAULT false NOT NULL,
    "position" integer,
    collection_id integer,
    collection_position smallint,
    cache_ttl integer,
    entity_id character(21),
    auto_apply_filters boolean DEFAULT true NOT NULL,
    width character varying(16) DEFAULT 'fixed'::character varying NOT NULL,
    initially_published_at timestamp with time zone,
    view_count integer DEFAULT 0 NOT NULL,
    archived_directly boolean DEFAULT false NOT NULL,
    last_viewed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN report_dashboard.auto_apply_filters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.auto_apply_filters IS 'Whether or not to auto-apply filters on a dashboard';


--
-- Name: COLUMN report_dashboard.width; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.width IS 'The value of the dashboard''s width setting can be fixed or full. New dashboards will be set to fixed';


--
-- Name: COLUMN report_dashboard.initially_published_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.initially_published_at IS 'The timestamp when the dashboard was first published in a static embed';


--
-- Name: COLUMN report_dashboard.view_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.view_count IS 'Keeps a running count of dashboard views';


--
-- Name: COLUMN report_dashboard.archived_directly; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.archived_directly IS 'Was this thing trashed directly';


--
-- Name: COLUMN report_dashboard.last_viewed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboard.last_viewed_at IS 'Timestamp of when this dashboard was last viewed';


--
-- Name: report_dashboard_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.report_dashboard ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.report_dashboard_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: report_dashboardcard; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_dashboardcard (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    size_x integer NOT NULL,
    size_y integer NOT NULL,
    "row" integer NOT NULL,
    col integer NOT NULL,
    card_id integer,
    dashboard_id integer NOT NULL,
    parameter_mappings text NOT NULL,
    visualization_settings text NOT NULL,
    entity_id character(21),
    action_id integer,
    dashboard_tab_id integer,
    inline_parameters text
);


--
-- Name: COLUMN report_dashboardcard.action_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboardcard.action_id IS 'The related action';


--
-- Name: COLUMN report_dashboardcard.dashboard_tab_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboardcard.dashboard_tab_id IS 'The referenced tab id that dashcard is on, it''s nullable for dashboard with no tab';


--
-- Name: COLUMN report_dashboardcard.inline_parameters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.report_dashboardcard.inline_parameters IS 'JSON array of parameter IDs that should be displayed inline with this card';


--
-- Name: report_dashboardcard_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.report_dashboardcard ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.report_dashboardcard_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: research_threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_threads (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    profile_name text DEFAULT 'default'::text NOT NULL,
    topic text NOT NULL,
    domain text,
    status text DEFAULT 'active'::text NOT NULL,
    priority text DEFAULT 'normal'::text,
    initial_query text,
    goal text,
    current_focus text,
    queries jsonb DEFAULT '[]'::jsonb,
    kb_entries text[] DEFAULT '{}'::text[],
    insights jsonb DEFAULT '[]'::jsonb,
    next_steps text,
    query_count integer DEFAULT 0,
    entry_count integer DEFAULT 0,
    swarm_run_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_activity timestamp with time zone DEFAULT now() NOT NULL,
    created_session_id uuid,
    last_session_id uuid
);


--
-- Name: revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revision (
    id integer NOT NULL,
    model character varying(16) NOT NULL,
    model_id integer NOT NULL,
    user_id integer NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    object text NOT NULL,
    is_reversion boolean DEFAULT false NOT NULL,
    is_creation boolean DEFAULT false NOT NULL,
    message text,
    most_recent boolean DEFAULT false NOT NULL,
    metabase_version character varying(100)
);


--
-- Name: COLUMN revision.most_recent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.revision.most_recent IS 'Whether a revision is the most recent one';


--
-- Name: COLUMN revision.metabase_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.revision.metabase_version IS 'Metabase version used to create the revision.';


--
-- Name: revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: routing_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_role text,
    agent_alias text NOT NULL,
    workflow_phase text,
    requested_capabilities text[] DEFAULT '{}'::text[],
    preferred_model text,
    actual_endpoint text NOT NULL,
    actual_model text NOT NULL,
    fallback_used boolean DEFAULT false,
    fallback_reason text,
    capability_mismatch boolean DEFAULT false,
    mismatched_capabilities text[] DEFAULT '{}'::text[],
    success boolean NOT NULL,
    latency_ms integer NOT NULL
);


--
-- Name: TABLE routing_decisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.routing_decisions IS 'Tracks capability-based inference routing decisions';


--
-- Name: COLUMN routing_decisions.capability_mismatch; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.routing_decisions.capability_mismatch IS 'True when agent got suboptimal model due to capability/availability mismatch';


--
-- Name: COLUMN routing_decisions.mismatched_capabilities; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.routing_decisions.mismatched_capabilities IS 'List of capabilities that could not be satisfied';


--
-- Name: scheduled_jobs_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_jobs_config (
    id integer NOT NULL,
    job_name text NOT NULL,
    schedule text NOT NULL,
    function_call text NOT NULL,
    description text,
    enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE scheduled_jobs_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scheduled_jobs_config IS 'Stores pg_cron job definitions. Apply with: SELECT cron.schedule(job_name, schedule, function_call) for each enabled row.';


--
-- Name: scheduled_jobs_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduled_jobs_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduled_jobs_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduled_jobs_config_id_seq OWNED BY public.scheduled_jobs_config.id;


--
-- Name: scheduled_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduled_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduled_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduled_tasks_id_seq OWNED BY public.scheduled_tasks.id;


--
-- Name: scheduler_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduler_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    model text NOT NULL,
    messages jsonb NOT NULL,
    priority public.job_priority DEFAULT 'normal'::public.job_priority NOT NULL,
    status public.job_status DEFAULT 'pending'::public.job_status NOT NULL,
    preferred_endpoint text,
    assigned_endpoint text,
    estimated_tokens integer DEFAULT 500,
    deadline_ms integer DEFAULT 30000,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scheduled_at timestamp with time zone,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    result text,
    error text,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    latency_ms integer DEFAULT 0,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    role text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE scheduler_jobs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scheduler_jobs IS 'Persistent inference job queue for Gaius scheduler';


--
-- Name: COLUMN scheduler_jobs.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scheduler_jobs.model IS 'Model ID (e.g., Qwen/QwQ-32B)';


--
-- Name: COLUMN scheduler_jobs.messages; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scheduler_jobs.messages IS 'OpenAI-format messages array';


--
-- Name: COLUMN scheduler_jobs.preferred_endpoint; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scheduler_jobs.preferred_endpoint IS 'User-requested endpoint preference';


--
-- Name: COLUMN scheduler_jobs.assigned_endpoint; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scheduler_jobs.assigned_endpoint IS 'Endpoint where job was actually scheduled';


--
-- Name: COLUMN scheduler_jobs.role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scheduler_jobs.role IS 'Swarm agent role if part of swarm execution';


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: scoring_rubrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scoring_rubrics (
    id integer NOT NULL,
    name character varying(128) NOT NULL,
    version character varying(32) NOT NULL,
    config jsonb NOT NULL,
    model_preference character varying(32) DEFAULT 'ensemble'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE scoring_rubrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scoring_rubrics IS 'Versioned scoring rubrics for LLM paper evaluation';


--
-- Name: scoring_rubrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scoring_rubrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scoring_rubrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scoring_rubrics_id_seq OWNED BY public.scoring_rubrics.id;


--
-- Name: search_index__4asdmoroquqdnn2arfyd5; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.search_index__4asdmoroquqdnn2arfyd5 (
    id bigint NOT NULL,
    search_vector tsvector NOT NULL,
    with_native_query_vector tsvector NOT NULL,
    model character varying(32) NOT NULL,
    display_data text NOT NULL,
    legacy_input text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    model_updated_at timestamp with time zone,
    pinned boolean,
    collection_id integer,
    official_collection boolean,
    name text NOT NULL,
    has_temporal_dim boolean,
    last_edited_at timestamp with time zone,
    dashboardcard_count integer,
    non_temporal_dim_ids text,
    dashboard_id integer,
    last_editor_id integer,
    model_id text,
    display_type text,
    last_viewed_at timestamp with time zone,
    database_id integer,
    creator_id integer,
    view_count integer,
    model_created_at timestamp with time zone,
    verified boolean
);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.search_index__4asdmoroquqdnn2arfyd5 ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.search_index__4asdmoroquqdnn2arfyd5_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.search_index__cvo4ibtsyjzvh5x7v49a6 (
    id bigint NOT NULL,
    search_vector tsvector NOT NULL,
    with_native_query_vector tsvector NOT NULL,
    model character varying(32) NOT NULL,
    display_data text NOT NULL,
    legacy_input text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    model_updated_at timestamp with time zone,
    pinned boolean,
    collection_id integer,
    official_collection boolean,
    name text NOT NULL,
    has_temporal_dim boolean,
    last_edited_at timestamp with time zone,
    dashboardcard_count integer,
    non_temporal_dim_ids text,
    dashboard_id integer,
    last_editor_id integer,
    model_id text,
    display_type text,
    last_viewed_at timestamp with time zone,
    database_id integer,
    creator_id integer,
    view_count integer,
    model_created_at timestamp with time zone,
    verified boolean
);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.search_index__cvo4ibtsyjzvh5x7v49a6 ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.search_index__cvo4ibtsyjzvh5x7v49a6_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: search_index_metadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.search_index_metadata (
    id integer NOT NULL,
    engine character varying(64) NOT NULL,
    version character varying(254) NOT NULL,
    index_name character varying(254) NOT NULL,
    status character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lang_code character varying(10) DEFAULT 'en'::character varying NOT NULL
);


--
-- Name: TABLE search_index_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.search_index_metadata IS 'Each entry corresponds to some queryable index, and contains metadata about it.';


--
-- Name: COLUMN search_index_metadata.engine; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.engine IS 'The kind of search engine which this index belongs to.';


--
-- Name: COLUMN search_index_metadata.version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.version IS 'Used to determine metabase compatibility. Format may depend on engine in future.';


--
-- Name: COLUMN search_index_metadata.index_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.index_name IS 'The name by which the given engine refers to this particular index, e.g. table name.';


--
-- Name: COLUMN search_index_metadata.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.status IS 'One of ''pending'', ''active'', or ''retired''';


--
-- Name: COLUMN search_index_metadata.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.created_at IS 'The timestamp of when the index was created';


--
-- Name: COLUMN search_index_metadata.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.updated_at IS 'The timestamp of when the index status was updated';


--
-- Name: COLUMN search_index_metadata.lang_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_index_metadata.lang_code IS 'Language code the data in the index is in';


--
-- Name: search_index_metadata_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.search_index_metadata ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.search_index_metadata_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: secret; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.secret (
    id integer NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    creator_id integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    name character varying(254) NOT NULL,
    kind character varying(254) NOT NULL,
    source character varying(254),
    value bytea NOT NULL
);


--
-- Name: secret_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.secret ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.secret_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: segment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.segment (
    id integer NOT NULL,
    table_id integer NOT NULL,
    creator_id integer NOT NULL,
    name character varying(254) NOT NULL,
    description text,
    archived boolean DEFAULT false NOT NULL,
    definition text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    points_of_interest text,
    caveats text,
    show_in_getting_started boolean DEFAULT false NOT NULL,
    entity_id character(21)
);


--
-- Name: segment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.segment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.segment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    profile_name text DEFAULT 'default'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    duration_seconds integer,
    initial_domain text,
    final_domain text,
    open_threads jsonb DEFAULT '[]'::jsonb,
    key_topics jsonb DEFAULT '[]'::jsonb,
    research_notes text,
    metrics jsonb DEFAULT '{}'::jsonb,
    handoff_generated boolean DEFAULT false,
    handoff_summary text,
    handoff_kb_path text
);


--
-- Name: setting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.setting (
    key character varying(254) NOT NULL,
    value text NOT NULL
);


--
-- Name: state_changes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.state_changes (
    id integer NOT NULL,
    kb_root text NOT NULL,
    client_id text,
    change_type text NOT NULL,
    generation bigint,
    change_data jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE state_changes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.state_changes IS 'Audit log of all state mutations for debugging idempotency issues.';


--
-- Name: COLUMN state_changes.change_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.state_changes.change_type IS 'Type: init, reindex, cursor_move, domain_change, preference_update, prune';


--
-- Name: state_changes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.state_changes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: state_changes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.state_changes_id_seq OWNED BY public.state_changes.id;


--
-- Name: summary_lineage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.summary_lineage (
    id integer NOT NULL,
    kb_path text NOT NULL,
    iceberg_table text DEFAULT 'gaius_hx.raw_content'::text,
    iceberg_record_id text,
    iceberg_snapshot_id bigint,
    content_item_id integer,
    model_used text,
    quality_score double precision,
    tokens_input integer,
    tokens_output integer,
    lineage_run_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT summary_lineage_quality_score_check CHECK (((quality_score >= (0)::double precision) AND (quality_score <= (1)::double precision)))
);


--
-- Name: TABLE summary_lineage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.summary_lineage IS 'Links KB summaries to raw Iceberg content for provenance';


--
-- Name: summary_lineage_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.summary_lineage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: summary_lineage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.summary_lineage_id_seq OWNED BY public.summary_lineage.id;


--
-- Name: table_privileges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.table_privileges (
    table_id integer NOT NULL,
    role character varying(255),
    "select" boolean DEFAULT false NOT NULL,
    update boolean DEFAULT false NOT NULL,
    insert boolean DEFAULT false NOT NULL,
    delete boolean DEFAULT false NOT NULL
);


--
-- Name: TABLE table_privileges; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.table_privileges IS 'Table for user and role privileges by table';


--
-- Name: COLUMN table_privileges.table_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges.table_id IS 'Table ID';


--
-- Name: COLUMN table_privileges.role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges.role IS 'Role name. NULL indicates the privileges are the current user''s';


--
-- Name: COLUMN table_privileges."select"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges."select" IS 'Privilege to select from the table';


--
-- Name: COLUMN table_privileges.update; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges.update IS 'Privilege to update records in the table';


--
-- Name: COLUMN table_privileges.insert; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges.insert IS 'Privilege to insert records into the table';


--
-- Name: COLUMN table_privileges.delete; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.table_privileges.delete IS 'Privilege to delete records from the table';


--
-- Name: task_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_history (
    id integer NOT NULL,
    task character varying(254) NOT NULL,
    db_id integer,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ended_at timestamp with time zone,
    duration integer,
    task_details text,
    status character varying(21) DEFAULT 'started'::character varying NOT NULL
);


--
-- Name: COLUMN task_history.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_history.status IS 'the status of task history, could be started, failed, success, unknown';


--
-- Name: task_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.task_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.task_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: theta_consolidation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.theta_consolidation_runs (
    id integer NOT NULL,
    slice_id text NOT NULL,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    urgency real,
    drift real,
    candidates_evaluated integer DEFAULT 0,
    candidates_selected integer DEFAULT 0,
    documents_augmented integer DEFAULT 0,
    status text DEFAULT 'scheduled'::text,
    error text,
    metadata jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT theta_consolidation_runs_status_check CHECK ((status = ANY (ARRAY['scheduled'::text, 'running'::text, 'completed'::text, 'failed'::text])))
);


--
-- Name: theta_consolidation_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.theta_consolidation_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: theta_consolidation_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.theta_consolidation_runs_id_seq OWNED BY public.theta_consolidation_runs.id;


--
-- Name: timeline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.timeline (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255),
    icon character varying(128) NOT NULL,
    collection_id integer,
    archived boolean DEFAULT false NOT NULL,
    creator_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    "default" boolean DEFAULT false NOT NULL,
    entity_id character(21)
);


--
-- Name: timeline_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.timeline_event (
    id integer NOT NULL,
    timeline_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255),
    "timestamp" timestamp with time zone NOT NULL,
    time_matters boolean NOT NULL,
    timezone character varying(255) NOT NULL,
    icon character varying(128) NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    creator_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: timeline_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.timeline_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.timeline_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: timeline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.timeline ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.timeline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: topic_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic_models (
    id integer NOT NULL,
    model_id character varying(128) NOT NULL,
    model_type character varying(32) NOT NULL,
    corpus_version_id integer,
    num_topics integer,
    discovered_topics integer,
    coherence_cv double precision,
    minio_path text NOT NULL,
    training_params jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE topic_models; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.topic_models IS 'Trained topic models (LDA, LSA, HDP, BERTopic) with lineage';


--
-- Name: topic_models_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.topic_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: topic_models_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.topic_models_id_seq OWNED BY public.topic_models.id;


--
-- Name: triage_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.triage_assessments (
    id integer NOT NULL,
    content_item_id integer,
    assessment_type text NOT NULL,
    score integer NOT NULL,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT triage_assessments_assessment_type_check CHECK ((assessment_type = ANY (ARRAY['heuristic'::text, 'llm'::text]))),
    CONSTRAINT triage_assessments_score_check CHECK (((score >= 0) AND (score <= 100)))
);


--
-- Name: triage_assessments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.triage_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: triage_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.triage_assessments_id_seq OWNED BY public.triage_assessments.id;


--
-- Name: ui_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ui_preferences (
    client_id text NOT NULL,
    cursor_x integer DEFAULT 9,
    cursor_y integer DEFAULT 9,
    view_mode text DEFAULT 'go'::text,
    overlay_mode text DEFAULT 'none'::text,
    iso_mode text DEFAULT 'curvature'::text,
    center_panel_mode text DEFAULT 'graph'::text,
    left_panel_visible boolean DEFAULT true,
    right_panel_visible boolean DEFAULT true,
    domain text,
    preferences_json jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    profile_name text DEFAULT 'default'::text,
    profile_changed_at timestamp with time zone
);


--
-- Name: TABLE ui_preferences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ui_preferences IS 'Per-client UI state. TUI/CLI/MCP each have their own preferences.';


--
-- Name: COLUMN ui_preferences.profile_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ui_preferences.profile_name IS 'Currently active profile name for this UI session.';


--
-- Name: user_interests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_interests (
    id integer NOT NULL,
    profile_name text DEFAULT 'default'::text NOT NULL,
    topic text NOT NULL,
    domain text,
    query_count integer DEFAULT 0,
    kb_entry_count integer DEFAULT 0,
    swarm_run_count integer DEFAULT 0,
    session_count integer DEFAULT 0,
    total_time_seconds integer DEFAULT 0,
    interest_score double precision DEFAULT 0.0,
    first_seen timestamp with time zone DEFAULT now() NOT NULL,
    last_activity timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_interests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_interests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_interests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_interests_id_seq OWNED BY public.user_interests.id;


--
-- Name: user_key_value; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_key_value (
    id integer NOT NULL,
    user_id integer NOT NULL,
    namespace character varying(254) NOT NULL,
    key character varying(254) NOT NULL,
    value text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone
);


--
-- Name: TABLE user_key_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_key_value IS 'A simple key value store for each user.';


--
-- Name: COLUMN user_key_value.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.user_id IS 'The ID of the user this KV-pair is for';


--
-- Name: COLUMN user_key_value.namespace; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.namespace IS 'The namespace for this KV, e.g. "dashboard-filters" or "nobody-knows"';


--
-- Name: COLUMN user_key_value.key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.key IS 'The key';


--
-- Name: COLUMN user_key_value.value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.value IS 'The value, serialized JSON';


--
-- Name: COLUMN user_key_value.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.created_at IS 'When this row was created';


--
-- Name: COLUMN user_key_value.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.updated_at IS 'When this row was last updated';


--
-- Name: COLUMN user_key_value.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_key_value.expires_at IS 'If set, when this row expires';


--
-- Name: user_key_value_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.user_key_value ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_key_value_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_parameter_value; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_parameter_value (
    id integer NOT NULL,
    user_id integer NOT NULL,
    parameter_id character varying(36) NOT NULL,
    value text,
    dashboard_id integer
);


--
-- Name: TABLE user_parameter_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_parameter_value IS 'Table holding last set value of a parameter per user';


--
-- Name: COLUMN user_parameter_value.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_parameter_value.user_id IS 'ID of the User who has set the parameter value';


--
-- Name: COLUMN user_parameter_value.parameter_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_parameter_value.parameter_id IS 'The parameter ID';


--
-- Name: COLUMN user_parameter_value.value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_parameter_value.value IS 'Value of the parameter';


--
-- Name: COLUMN user_parameter_value.dashboard_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_parameter_value.dashboard_id IS 'The ID of the dashboard';


--
-- Name: user_parameter_value_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.user_parameter_value ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.user_parameter_value_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_alerts; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_alerts AS
 WITH parsed_cron AS (
         SELECT n_1.id,
            ns.cron_schedule,
            ns.ui_display_type,
            split_part((ns.cron_schedule)::text, ' '::text, 2) AS minutes,
            split_part((ns.cron_schedule)::text, ' '::text, 3) AS hours,
            split_part((ns.cron_schedule)::text, ' '::text, 4) AS day_of_month,
            split_part((ns.cron_schedule)::text, ' '::text, 6) AS day_of_week
           FROM (public.notification n_1
             JOIN public.notification_subscription ns ON ((n_1.id = ns.notification_id)))
          WHERE (((n_1.payload_type)::text = 'notification/card'::text) AND ((ns.type)::text = 'notification-subscription/cron'::text))
        ), schedule_info AS (
         SELECT parsed_cron.id,
                CASE
                    WHEN ((parsed_cron.ui_display_type)::text = 'cron/raw'::text) THEN 'custom'::text
                    WHEN ((parsed_cron.minutes ~ '^\*$'::text) OR (parsed_cron.minutes ~ '^\d+/\d+$'::text)) THEN 'by the minute'::text
                    WHEN ((parsed_cron.day_of_month <> '*'::text) AND ((parsed_cron.day_of_week = '?'::text) OR (parsed_cron.day_of_week ~ '^\d#1$'::text) OR (parsed_cron.day_of_week ~ '^\dL$'::text))) THEN 'monthly'::text
                    WHEN ((parsed_cron.day_of_week <> '?'::text) AND (parsed_cron.day_of_week <> '*'::text)) THEN 'weekly'::text
                    WHEN (parsed_cron.hours <> '*'::text) THEN 'daily'::text
                    ELSE 'hourly'::text
                END AS schedule_type,
                CASE
                    WHEN (parsed_cron.day_of_week ~ '^1'::text) THEN 'sun'::text
                    WHEN (parsed_cron.day_of_week ~ '^2'::text) THEN 'mon'::text
                    WHEN (parsed_cron.day_of_week ~ '^3'::text) THEN 'tue'::text
                    WHEN (parsed_cron.day_of_week ~ '^4'::text) THEN 'wed'::text
                    WHEN (parsed_cron.day_of_week ~ '^5'::text) THEN 'thu'::text
                    WHEN (parsed_cron.day_of_week ~ '^6'::text) THEN 'fri'::text
                    WHEN (parsed_cron.day_of_week ~ '^7'::text) THEN 'sat'::text
                    ELSE NULL::text
                END AS schedule_day,
                CASE
                    WHEN (parsed_cron.hours = '*'::text) THEN NULL::integer
                    WHEN (parsed_cron.hours ~ '^\d+$'::text) THEN (parsed_cron.hours)::integer
                    WHEN (parsed_cron.hours ~ '^(\d+)/\d+$'::text) THEN ("substring"(parsed_cron.hours, '^(\d+)/\d+$'::text))::integer
                    ELSE NULL::integer
                END AS schedule_hour
           FROM parsed_cron
        ), agg_recipients AS (
         SELECT nr.notification_handler_id,
            string_agg((cu.email)::text, ','::text) AS recipients,
            ( SELECT string_agg(nr2.details, ','::text) AS string_agg
                   FROM public.notification_recipient nr2
                  WHERE ((nr2.notification_handler_id = nr.notification_handler_id) AND ((nr2.type)::text = 'notification-recipient/raw-value'::text))) AS recipient_external
           FROM (public.notification_recipient nr
             LEFT JOIN public.core_user cu ON (((nr.user_id = cu.id) AND ((nr.type)::text = 'notification-recipient/user'::text))))
          GROUP BY nr.notification_handler_id
        )
 SELECT n.id AS entity_id,
    ('notification_'::text || n.id) AS entity_qualified_id,
    n.created_at,
    n.updated_at,
    n.creator_id,
    nc.card_id,
    ('card_'::text || nc.card_id) AS card_qualified_id,
        CASE
            WHEN ((nc.send_condition)::text = 'has_result'::text) THEN 'rows'::text
            WHEN ((nc.send_condition)::text = ANY ((ARRAY['goal_above'::character varying, 'goal_below'::character varying])::text[])) THEN 'goal'::text
            ELSE NULL::text
        END AS alert_condition,
    si.schedule_type,
    si.schedule_day,
    si.schedule_hour,
    (NOT n.active) AS archived,
    nh.channel_type AS recipient_type,
    ar.recipients,
    ar.recipient_external
   FROM ((((public.notification n
     JOIN public.notification_card nc ON ((n.payload_id = nc.id)))
     JOIN schedule_info si ON ((n.id = si.id)))
     LEFT JOIN public.notification_handler nh ON ((n.id = nh.notification_id)))
     LEFT JOIN agg_recipients ar ON ((nh.id = ar.notification_handler_id)))
  WHERE ((n.payload_type)::text = 'notification/card'::text);


--
-- Name: v_audit_log; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_audit_log AS
 SELECT id,
        CASE
            WHEN ((topic)::text = 'card-create'::text) THEN 'card-create'::character varying
            WHEN ((topic)::text = 'card-delete'::text) THEN 'card-delete'::character varying
            WHEN ((topic)::text = 'card-update'::text) THEN 'card-update'::character varying
            WHEN ((topic)::text = 'pulse-create'::text) THEN 'subscription-create'::character varying
            WHEN ((topic)::text = 'pulse-delete'::text) THEN 'subscription-delete'::character varying
            ELSE topic
        END AS topic,
    "timestamp",
    NULL::text AS end_timestamp,
    COALESCE(user_id, 0) AS user_id,
    lower((model)::text) AS entity_type,
    model_id AS entity_id,
        CASE
            WHEN ((model)::text = 'Dataset'::text) THEN ('card_'::text || model_id)
            WHEN (model_id IS NULL) THEN NULL::text
            ELSE ((lower((model)::text) || '_'::text) || model_id)
        END AS entity_qualified_id,
    details
   FROM public.audit_log
  WHERE ((topic)::text <> ALL ((ARRAY['card-read'::character varying, 'card-query'::character varying, 'dashboard-read'::character varying, 'dashboard-query'::character varying, 'table-read'::character varying])::text[]));


--
-- Name: v_content; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_content AS
 SELECT action.id AS entity_id,
    ('action_'::text || action.id) AS entity_qualified_id,
    'action'::text AS entity_type,
    action.created_at,
    action.updated_at,
    action.creator_id,
    action.name,
    action.description,
    NULL::integer AS collection_id,
    action.made_public_by_id AS made_public_by_user,
    NULL::boolean AS is_embedding_enabled,
    NULL::boolean AS is_verified,
    action.archived,
    action.type AS action_type,
    action.model_id AS action_model_id,
    NULL::boolean AS collection_is_official,
    NULL::boolean AS collection_is_personal,
    NULL::text AS question_viz_type,
    NULL::text AS question_database_id,
    NULL::boolean AS question_is_native,
    NULL::timestamp without time zone AS event_timestamp
   FROM public.action
UNION
 SELECT collection.id AS entity_id,
    ('collection_'::text || collection.id) AS entity_qualified_id,
    'collection'::text AS entity_type,
    collection.created_at,
    NULL::timestamp with time zone AS updated_at,
    NULL::integer AS creator_id,
    collection.name,
    collection.description,
    NULL::integer AS collection_id,
    NULL::integer AS made_public_by_user,
    NULL::boolean AS is_embedding_enabled,
    NULL::boolean AS is_verified,
    collection.archived,
    NULL::text AS action_type,
    NULL::integer AS action_model_id,
        CASE
            WHEN ((collection.authority_level)::text = 'official'::text) THEN true
            ELSE false
        END AS collection_is_official,
        CASE
            WHEN (collection.personal_owner_id IS NOT NULL) THEN true
            ELSE false
        END AS collection_is_personal,
    NULL::text AS question_viz_type,
    NULL::text AS question_database_id,
    NULL::boolean AS question_is_native,
    NULL::timestamp without time zone AS event_timestamp
   FROM public.collection
UNION
 SELECT report_card.id AS entity_id,
    ('card_'::text || report_card.id) AS entity_qualified_id,
    report_card.type AS entity_type,
    report_card.created_at,
    report_card.updated_at,
    report_card.creator_id,
    report_card.name,
    report_card.description,
    report_card.collection_id,
    report_card.made_public_by_id AS made_public_by_user,
    report_card.enable_embedding AS is_embedding_enabled,
        CASE
            WHEN moderation.is_verified THEN true
            ELSE false
        END AS is_verified,
    report_card.archived,
    NULL::text AS action_type,
    NULL::integer AS action_model_id,
    NULL::boolean AS collection_is_official,
    NULL::boolean AS collection_is_personal,
    report_card.display AS question_viz_type,
    ('database_'::text || report_card.database_id) AS question_database_id,
        CASE
            WHEN ((report_card.query_type)::text = 'native'::text) THEN true
            ELSE false
        END AS question_is_native,
    NULL::timestamp without time zone AS event_timestamp
   FROM (public.report_card
     LEFT JOIN ( SELECT (((moderation_review.moderated_item_type)::text || '_'::text) || moderation_review.moderated_item_id) AS entity_qualified_id,
                CASE
                    WHEN ((moderation_review.status)::text = 'verified'::text) THEN true
                    ELSE false
                END AS is_verified
           FROM public.moderation_review
          WHERE moderation_review.most_recent) moderation ON ((('card_'::text || report_card.id) = moderation.entity_qualified_id)))
UNION
 SELECT report_dashboard.id AS entity_id,
    ('dashboard_'::text || report_dashboard.id) AS entity_qualified_id,
    'dashboard'::text AS entity_type,
    report_dashboard.created_at,
    report_dashboard.updated_at,
    report_dashboard.creator_id,
    report_dashboard.name,
    report_dashboard.description,
    report_dashboard.collection_id,
    report_dashboard.made_public_by_id AS made_public_by_user,
    report_dashboard.enable_embedding AS is_embedding_enabled,
        CASE
            WHEN moderation.is_verified THEN true
            ELSE false
        END AS is_verified,
    report_dashboard.archived,
    NULL::text AS action_type,
    NULL::integer AS action_model_id,
    NULL::boolean AS collection_is_official,
    NULL::boolean AS collection_is_personal,
    NULL::text AS question_viz_type,
    NULL::text AS question_database_id,
    NULL::boolean AS question_is_native,
    NULL::timestamp without time zone AS event_timestamp
   FROM (public.report_dashboard
     LEFT JOIN ( SELECT (((moderation_review.moderated_item_type)::text || '_'::text) || moderation_review.moderated_item_id) AS entity_qualified_id,
                CASE
                    WHEN ((moderation_review.status)::text = 'verified'::text) THEN true
                    ELSE false
                END AS is_verified
           FROM public.moderation_review
          WHERE moderation_review.most_recent) moderation ON ((('dashboard_'::text || report_dashboard.id) = moderation.entity_qualified_id)))
UNION
 SELECT event.id AS entity_id,
    ('event_'::text || event.id) AS entity_qualified_id,
    'event'::text AS entity_type,
    event.created_at,
    event.updated_at,
    event.creator_id,
    event.name,
    event.description,
    timeline.collection_id,
    NULL::integer AS made_public_by_user,
    NULL::boolean AS is_embedding_enabled,
    NULL::boolean AS is_verified,
    event.archived,
    NULL::text AS action_type,
    NULL::integer AS action_model_id,
    NULL::boolean AS collection_is_official,
    NULL::boolean AS collection_is_personal,
    NULL::text AS question_viz_type,
    NULL::text AS question_database_id,
    NULL::boolean AS question_is_native,
    event."timestamp" AS event_timestamp
   FROM (public.timeline_event event
     LEFT JOIN public.timeline ON ((event.timeline_id = timeline.id)));


--
-- Name: v_dashboardcard; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_dashboardcard AS
 SELECT id AS entity_id,
    concat('dashboardcard_', id) AS entity_qualified_id,
    concat('dashboard_', dashboard_id) AS dashboard_qualified_id,
    concat('dashboardtab_', dashboard_tab_id) AS dashboardtab_id,
    concat('card_', card_id) AS card_qualified_id,
    created_at,
    updated_at,
    size_x,
    size_y,
    visualization_settings,
    parameter_mappings
   FROM public.report_dashboardcard;


--
-- Name: v_databases; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_databases AS
 SELECT id AS entity_id,
    concat('database_', id) AS entity_qualified_id,
    created_at,
    updated_at,
    name,
    description,
    engine AS database_type,
    metadata_sync_schedule,
    cache_field_values_schedule,
    timezone,
    is_on_demand,
    auto_run_queries,
    cache_ttl,
    creator_id,
    dbms_version AS db_version
   FROM public.metabase_database
  WHERE (id <> 13371337);


--
-- Name: v_fields; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_fields AS
 SELECT id AS entity_id,
    ('field_'::text || id) AS entity_qualified_id,
    created_at,
    updated_at,
    name,
    display_name,
    description,
    base_type,
    visibility_type,
    fk_target_field_id,
    has_field_values,
    active,
    table_id
   FROM public.metabase_field;


--
-- Name: v_group_members; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_group_members AS
 SELECT permissions_group_membership.user_id,
    permissions_group.id AS group_id,
    permissions_group.name AS group_name
   FROM (public.permissions_group_membership
     LEFT JOIN public.permissions_group ON ((permissions_group_membership.group_id = permissions_group.id)))
UNION
 SELECT 0 AS user_id,
    0 AS group_id,
    'Anonymous users'::character varying AS group_name;


--
-- Name: v_pipeline_throughput; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_pipeline_throughput AS
 WITH hourly AS (
         SELECT date_trunc('hour'::text, content_items.fetched_at) AS hour,
            count(*) AS fetched,
            count(*) FILTER (WHERE (content_items.heuristic_score IS NOT NULL)) AS heuristic_scored,
            count(*) FILTER (WHERE (content_items.llm_quality_score IS NOT NULL)) AS llm_scored,
            count(*) FILTER (WHERE (content_items.processed_at IS NOT NULL)) AS written_to_kb,
            count(*) FILTER (WHERE (content_items.summary_excluded = true)) AS excluded
           FROM public.content_items
          WHERE (content_items.fetched_at > (now() - '24:00:00'::interval))
          GROUP BY (date_trunc('hour'::text, content_items.fetched_at))
        )
 SELECT hour,
    fetched,
    heuristic_scored,
    llm_scored,
    written_to_kb,
    excluded,
    round(((100.0 * (heuristic_scored)::numeric) / (NULLIF(fetched, 0))::numeric), 1) AS heuristic_rate,
    round(((100.0 * (written_to_kb)::numeric) / (NULLIF(llm_scored, 0))::numeric), 1) AS kb_conversion_rate
   FROM hourly
  ORDER BY hour DESC;


--
-- Name: v_query_log; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_query_log AS
 SELECT query_execution.id AS entity_id,
    query_execution.started_at,
    ((query_execution.running_time)::double precision / (1000)::double precision) AS running_time_seconds,
    query_execution.result_rows,
    query_execution.native AS is_native,
    query_execution.context AS query_source,
    query_execution.error,
    COALESCE(query_execution.executor_id, 0) AS user_id,
    query_execution.card_id,
    ('card_'::text || query_execution.card_id) AS card_qualified_id,
    query_execution.dashboard_id,
    ('dashboard_'::text || query_execution.dashboard_id) AS dashboard_qualified_id,
    query_execution.pulse_id,
    query_execution.database_id,
    ('database_'::text || query_execution.database_id) AS database_qualified_id,
    query_execution.cache_hit,
    query_execution.action_id,
    ('action_'::text || query_execution.action_id) AS action_qualified_id,
    query.query
   FROM (public.query_execution
     LEFT JOIN public.query ON ((query_execution.hash = query.query_hash)));


--
-- Name: v_scheduled_jobs_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_scheduled_jobs_status AS
 SELECT jobid,
    jobname,
    schedule,
    command,
    nodename,
    active
   FROM public.get_scheduled_jobs_status() get_scheduled_jobs_status(jobid, jobname, schedule, command, nodename, active);


--
-- Name: VIEW v_scheduled_jobs_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_scheduled_jobs_status IS 'View of all pg_cron jobs for this database. Use SELECT * FROM v_scheduled_jobs_status;
Backed by get_scheduled_jobs_status() function with SECURITY DEFINER.';


--
-- Name: v_source_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_source_status AS
SELECT
    NULL::text AS name,
    NULL::public.source_type AS source_type,
    NULL::boolean AS active,
    NULL::integer AS fetch_interval_minutes,
    NULL::timestamp with time zone AS last_fetch_at,
    NULL::text AS status,
    NULL::bigint AS total_items,
    NULL::bigint AS kb_items,
    NULL::bigint AS pending_jobs,
    NULL::text[] AS profiles;


--
-- Name: v_subscriptions; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_subscriptions AS
 WITH agg_recipients AS (
         SELECT pulse_channel_recipient.pulse_channel_id,
            string_agg((core_user.email)::text, ','::text) AS recipients
           FROM (public.pulse_channel_recipient
             LEFT JOIN public.core_user ON ((pulse_channel_recipient.user_id = core_user.id)))
          GROUP BY pulse_channel_recipient.pulse_channel_id
        )
 SELECT pulse.id AS entity_id,
    ('pulse_'::text || pulse.id) AS entity_qualified_id,
    pulse.created_at,
    pulse.updated_at,
    pulse.creator_id,
    pulse.archived,
    ('dashboard_'::text || pulse.dashboard_id) AS dashboard_qualified_id,
    pulse_channel.schedule_type,
    pulse_channel.schedule_day,
    pulse_channel.schedule_hour,
    pulse_channel.channel_type AS recipient_type,
    agg_recipients.recipients,
    pulse_channel.details AS recipient_external,
    pulse.parameters
   FROM ((public.pulse
     LEFT JOIN public.pulse_channel ON ((pulse.id = pulse_channel.pulse_id)))
     LEFT JOIN agg_recipients ON ((pulse_channel.id = agg_recipients.pulse_channel_id)))
  WHERE (pulse.alert_condition IS NULL);


--
-- Name: v_tables; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_tables AS
 SELECT id AS entity_id,
    ('table_'::text || id) AS entity_qualified_id,
    created_at,
    updated_at,
    name,
    display_name,
    description,
    active,
    db_id AS database_id,
    schema,
    is_upload
   FROM public.metabase_table;


--
-- Name: v_task_watchdog; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_task_watchdog AS
 SELECT task_type,
    count(*) FILTER (WHERE ((picked_up_at IS NULL) AND (scheduled_for < (now() - '00:30:00'::interval)))) AS stale_pending,
    count(*) FILTER (WHERE ((picked_up_at IS NOT NULL) AND (completed_at IS NULL) AND (picked_up_at < (now() - '00:10:00'::interval)))) AS stuck_running,
    count(*) FILTER (WHERE (completed_at > (now() - '01:00:00'::interval))) AS completed_1h,
    count(*) FILTER (WHERE ((error IS NOT NULL) AND (completed_at > (now() - '24:00:00'::interval)))) AS failed_24h
   FROM public.scheduled_tasks
  GROUP BY task_type;


--
-- Name: v_tasks; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_tasks AS
 SELECT id,
    task,
    status,
    ('database_'::text || db_id) AS database_qualified_id,
    started_at,
    ended_at,
    ((duration)::double precision / (1000)::double precision) AS duration_seconds,
    task_details AS details
   FROM public.task_history;


--
-- Name: v_theta_consolidation_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_theta_consolidation_status AS
 SELECT slice_id,
    status,
    started_at,
    completed_at,
    urgency,
    drift,
    candidates_evaluated,
    candidates_selected,
    documents_augmented,
    error,
    EXTRACT(epoch FROM (COALESCE(completed_at, now()) - started_at)) AS duration_seconds
   FROM public.theta_consolidation_runs
  ORDER BY started_at DESC
 LIMIT 20;


--
-- Name: v_users; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_users AS
 SELECT core_user.id AS user_id,
    ('user_'::text || core_user.id) AS entity_qualified_id,
    core_user.type,
        CASE
            WHEN ((core_user.type)::text = 'api-key'::text) THEN NULL::public.citext
            ELSE core_user.email
        END AS email,
    core_user.first_name,
    core_user.last_name,
    COALESCE((((core_user.first_name)::text || ' '::text) || (core_user.last_name)::text), (core_user.first_name)::text, (core_user.last_name)::text) AS full_name,
    core_user.date_joined,
    core_user.last_login,
    core_user.updated_at,
    core_user.is_superuser AS is_admin,
    core_user.is_active,
    core_user.sso_source,
    core_user.locale
   FROM public.core_user
UNION
 SELECT 0 AS user_id,
    'user_0'::text AS entity_qualified_id,
    'anonymous'::character varying AS type,
    NULL::public.citext AS email,
    'External'::character varying AS first_name,
    'User'::character varying AS last_name,
    'External User'::text AS full_name,
    NULL::timestamp with time zone AS date_joined,
    NULL::timestamp with time zone AS last_login,
    NULL::timestamp with time zone AS updated_at,
    false AS is_admin,
    NULL::boolean AS is_active,
    NULL::character varying AS sso_source,
    NULL::character varying AS locale;


--
-- Name: view_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.view_log (
    id integer NOT NULL,
    user_id integer,
    model character varying(16) NOT NULL,
    model_id integer NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    metadata text,
    has_access boolean,
    context character varying(32),
    embedding_client character varying(254),
    embedding_version character varying(254)
);


--
-- Name: COLUMN view_log.has_access; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.view_log.has_access IS 'Whether the user who initiated the view had read access to the item being viewed.';


--
-- Name: COLUMN view_log.context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.view_log.context IS 'The context of the view, can be collection, question, or dashboard. Only for cards.';


--
-- Name: COLUMN view_log.embedding_client; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.view_log.embedding_client IS 'Used by the embedding team to track SDK usage';


--
-- Name: COLUMN view_log.embedding_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.view_log.embedding_version IS 'Used by the embedding team to track SDK version usage';


--
-- Name: v_view_log; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_view_log AS
 SELECT id,
    "timestamp",
    COALESCE(user_id, 0) AS user_id,
    model AS entity_type,
    model_id AS entity_id,
    (((model)::text || '_'::text) || model_id) AS entity_qualified_id
   FROM public.view_log;


--
-- Name: x_auto_sync_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_auto_sync_schedules (
    user_id character varying(64) NOT NULL,
    is_active boolean DEFAULT true,
    next_run_at timestamp with time zone NOT NULL,
    folders_total integer DEFAULT 0,
    folders_synced integer DEFAULT 0,
    sync_iterations integer DEFAULT 0,
    interval_minutes integer DEFAULT 16,
    max_iterations integer DEFAULT 50,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    last_error text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE x_auto_sync_schedules; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_auto_sync_schedules IS 'Active auto-sync schedules for X bookmarks';


--
-- Name: COLUMN x_auto_sync_schedules.interval_minutes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_auto_sync_schedules.interval_minutes IS 'Minutes between sync iterations (16 = 15min rate limit + 1min buffer)';


--
-- Name: COLUMN x_auto_sync_schedules.max_iterations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_auto_sync_schedules.max_iterations IS 'Maximum iterations before auto-cancel (prevents runaway)';


--
-- Name: x_oauth_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_oauth_tokens (
    user_id character varying(64) NOT NULL,
    username character varying(64) NOT NULL,
    access_token text NOT NULL,
    refresh_token text,
    token_type character varying(32) DEFAULT 'Bearer'::character varying,
    scopes text[],
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE x_oauth_tokens; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_oauth_tokens IS 'OAuth 2.0 tokens for X API access';


--
-- Name: COLUMN x_oauth_tokens.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_oauth_tokens.user_id IS 'X user ID (numeric string)';


--
-- Name: COLUMN x_oauth_tokens.access_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_oauth_tokens.access_token IS 'Encrypted access token';


--
-- Name: COLUMN x_oauth_tokens.refresh_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_oauth_tokens.refresh_token IS 'Encrypted refresh token for token renewal';


--
-- Name: v_x_auto_sync_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_x_auto_sync_status AS
 SELECT s.user_id,
    t.username,
    s.is_active,
    s.folders_total,
    s.folders_synced,
    (s.folders_total - s.folders_synced) AS folders_remaining,
    s.sync_iterations,
    s.max_iterations,
    s.interval_minutes,
    s.next_run_at,
    s.last_error,
    s.created_at,
    s.completed_at,
        CASE
            WHEN (NOT s.is_active) THEN 'stopped'::text
            WHEN (t.expires_at <= now()) THEN 'token_expired'::text
            WHEN (s.next_run_at <= now()) THEN 'due'::text
            ELSE 'scheduled'::text
        END AS status,
    (s.metadata ->> 'stop_reason'::text) AS stop_reason
   FROM (public.x_auto_sync_schedules s
     JOIN public.x_oauth_tokens t ON (((t.user_id)::text = (s.user_id)::text)))
  ORDER BY s.updated_at DESC;


--
-- Name: VIEW v_x_auto_sync_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_x_auto_sync_status IS 'Auto-sync schedule status per user';


--
-- Name: x_api_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_api_requests (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    request_type character varying(64) NOT NULL,
    endpoint character varying(255) NOT NULL,
    status character varying(32) NOT NULL,
    priority integer DEFAULT 0,
    pagination_token character varying(255),
    sync_run_id integer,
    queued_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    response_status integer,
    rate_limit_reset_at timestamp with time zone,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE x_api_requests; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_api_requests IS 'Rate-limited API request queue (1 req/15 min on Free tier)';


--
-- Name: COLUMN x_api_requests.rate_limit_reset_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_api_requests.rate_limit_reset_at IS 'X-Rate-Limit-Reset header value';


--
-- Name: x_bookmark_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_bookmark_folders (
    x_folder_id character varying(64) NOT NULL,
    user_id character varying(64) NOT NULL,
    name character varying(255) NOT NULL,
    kb_path character varying(1024) NOT NULL,
    bookmark_count integer DEFAULT 0,
    last_sync_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE x_bookmark_folders; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_bookmark_folders IS 'X bookmark folder to KB path mapping';


--
-- Name: COLUMN x_bookmark_folders.kb_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_bookmark_folders.kb_path IS 'KB directory for this folder, e.g., current/bookmarks/papers/';


--
-- Name: x_bookmarks_sync; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_bookmarks_sync (
    tweet_id character varying(64) NOT NULL,
    folder_id character varying(64),
    user_id character varying(64) NOT NULL,
    content_hash character varying(64) NOT NULL,
    iceberg_id uuid,
    kb_manifest_path character varying(1024),
    bookmarked_at timestamp with time zone,
    synced_at timestamp with time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE x_bookmarks_sync; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_bookmarks_sync IS 'Individual bookmark sync state';


--
-- Name: COLUMN x_bookmarks_sync.content_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_bookmarks_sync.content_hash IS 'SHA-256 hash for deduplication';


--
-- Name: COLUMN x_bookmarks_sync.iceberg_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_bookmarks_sync.iceberg_id IS 'Reference to raw.x_bookmarks Iceberg table';


--
-- Name: x_rate_limits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_rate_limits (
    user_id character varying(64) NOT NULL,
    endpoint_group character varying(64) NOT NULL,
    requests_remaining integer DEFAULT 0,
    requests_limit integer DEFAULT 1,
    reset_at timestamp with time zone,
    last_request_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE x_rate_limits; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_rate_limits IS 'Cached X API rate limit state';


--
-- Name: COLUMN x_rate_limits.endpoint_group; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_rate_limits.endpoint_group IS 'Rate limit bucket (bookmarks share a limit)';


--
-- Name: x_sync_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_sync_runs (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    bookmarks_fetched integer DEFAULT 0,
    bookmarks_new integer DEFAULT 0,
    folders_synced integer DEFAULT 0,
    pages_fetched integer DEFAULT 0,
    pagination_token character varying(255),
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: TABLE x_sync_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.x_sync_runs IS 'Sync operation history with rate limit resume support';


--
-- Name: COLUMN x_sync_runs.pagination_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.x_sync_runs.pagination_token IS 'Next page token for resuming rate-limited syncs';


--
-- Name: v_x_sync_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_x_sync_status AS
 SELECT t.user_id,
    t.username,
    t.expires_at AS token_expires_at,
        CASE
            WHEN (t.expires_at IS NULL) THEN 'no_expiry'::text
            WHEN (t.expires_at <= now()) THEN 'expired'::text
            WHEN (t.expires_at <= (now() + '1 day'::interval)) THEN 'expiring_soon'::text
            ELSE 'valid'::text
        END AS token_status,
    rl.requests_remaining,
    rl.reset_at AS rate_limit_reset,
    ( SELECT count(*) AS count
           FROM public.x_bookmark_folders f
          WHERE ((f.user_id)::text = (t.user_id)::text)) AS folder_count,
    ( SELECT count(*) AS count
           FROM public.x_bookmarks_sync b
          WHERE ((b.user_id)::text = (t.user_id)::text)) AS bookmark_count,
    ( SELECT count(*) AS count
           FROM public.x_api_requests r
          WHERE (((r.user_id)::text = (t.user_id)::text) AND ((r.status)::text = 'queued'::text))) AS queued_requests,
    ( SELECT max(r.completed_at) AS max
           FROM public.x_sync_runs r
          WHERE (((r.user_id)::text = (t.user_id)::text) AND ((r.status)::text = 'completed'::text))) AS last_sync_at,
    ( SELECT r.status
           FROM public.x_sync_runs r
          WHERE ((r.user_id)::text = (t.user_id)::text)
          ORDER BY r.started_at DESC
         LIMIT 1) AS last_run_status
   FROM (public.x_oauth_tokens t
     LEFT JOIN public.x_rate_limits rl ON (((rl.user_id)::text = (t.user_id)::text)));


--
-- Name: VIEW v_x_sync_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_x_sync_status IS 'X bookmark sync status per user';


--
-- Name: view_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.view_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.view_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: x_api_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.x_api_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: x_api_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.x_api_requests_id_seq OWNED BY public.x_api_requests.id;


--
-- Name: x_oauth_pending; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.x_oauth_pending (
    state character varying(64) NOT NULL,
    verifier character varying(128) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone DEFAULT (now() + '00:10:00'::interval)
);


--
-- Name: x_sync_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.x_sync_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: x_sync_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.x_sync_runs_id_seq OWNED BY public.x_sync_runs.id;


--
-- Name: Dataset id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Dataset" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'Dataset'::name))::integer, nextval('gaius_hx."Dataset_id_seq"'::regclass));


--
-- Name: Dataset properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Dataset" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: EXECUTES id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."EXECUTES" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'EXECUTES'::name))::integer, nextval('gaius_hx."EXECUTES_id_seq"'::regclass));


--
-- Name: EXECUTES properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."EXECUTES" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: INPUT_TO id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."INPUT_TO" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'INPUT_TO'::name))::integer, nextval('gaius_hx."INPUT_TO_id_seq"'::regclass));


--
-- Name: INPUT_TO properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."INPUT_TO" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: Job id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Job" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'Job'::name))::integer, nextval('gaius_hx."Job_id_seq"'::regclass));


--
-- Name: Job properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Job" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: OUTPUTS id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."OUTPUTS" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'OUTPUTS'::name))::integer, nextval('gaius_hx."OUTPUTS_id_seq"'::regclass));


--
-- Name: OUTPUTS properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."OUTPUTS" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: PARENT id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."PARENT" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'PARENT'::name))::integer, nextval('gaius_hx."PARENT_id_seq"'::regclass));


--
-- Name: PARENT properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."PARENT" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: Run id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Run" ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, 'Run'::name))::integer, nextval('gaius_hx."Run_id_seq"'::regclass));


--
-- Name: Run properties; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx."Run" ALTER COLUMN properties SET DEFAULT ag_catalog.agtype_build_map();


--
-- Name: _ag_label_edge id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx._ag_label_edge ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, '_ag_label_edge'::name))::integer, nextval('gaius_hx._ag_label_edge_id_seq'::regclass));


--
-- Name: _ag_label_vertex id; Type: DEFAULT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx._ag_label_vertex ALTER COLUMN id SET DEFAULT ag_catalog._graphid((ag_catalog._label_id('gaius_hx'::name, '_ag_label_vertex'::name))::integer, nextval('gaius_hx._ag_label_vertex_id_seq'::regclass));


--
-- Name: audit_recommendations id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.audit_recommendations ALTER COLUMN id SET DEFAULT nextval('meta.audit_recommendations_id_seq'::regclass);


--
-- Name: data_dependencies id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies ALTER COLUMN id SET DEFAULT nextval('meta.data_dependencies_id_seq'::regclass);


--
-- Name: document_clusters id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.document_clusters ALTER COLUMN id SET DEFAULT nextval('meta.document_clusters_id_seq'::regclass);


--
-- Name: flow_events event_id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.flow_events ALTER COLUMN event_id SET DEFAULT nextval('meta.flow_events_event_id_seq'::regclass);


--
-- Name: fmp_sync_runs id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.fmp_sync_runs ALTER COLUMN id SET DEFAULT nextval('meta.fmp_sync_runs_id_seq'::regclass);


--
-- Name: institutional_holders_cache id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.institutional_holders_cache ALTER COLUMN id SET DEFAULT nextval('meta.institutional_holders_cache_id_seq'::regclass);


--
-- Name: metaagent_audits id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metaagent_audits ALTER COLUMN id SET DEFAULT nextval('meta.metaagent_audits_id_seq'::regclass);


--
-- Name: metabase_models id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metabase_models ALTER COLUMN id SET DEFAULT nextval('meta.metabase_models_id_seq'::regclass);


--
-- Name: metabase_sync_runs id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metabase_sync_runs ALTER COLUMN id SET DEFAULT nextval('meta.metabase_sync_runs_id_seq'::regclass);


--
-- Name: ngrc_models id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.ngrc_models ALTER COLUMN id SET DEFAULT nextval('meta.ngrc_models_id_seq'::regclass);


--
-- Name: nifi_flows id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.nifi_flows ALTER COLUMN id SET DEFAULT nextval('meta.nifi_flows_id_seq'::regclass);


--
-- Name: prospect_candidates id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_candidates ALTER COLUMN id SET DEFAULT nextval('meta.prospect_candidates_id_seq'::regclass);


--
-- Name: prospect_strategies id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_strategies ALTER COLUMN id SET DEFAULT nextval('meta.prospect_strategies_id_seq'::regclass);


--
-- Name: quality_assessments id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.quality_assessments ALTER COLUMN id SET DEFAULT nextval('meta.quality_assessments_id_seq'::regclass);


--
-- Name: research_progress event_id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.research_progress ALTER COLUMN event_id SET DEFAULT nextval('meta.research_progress_event_id_seq'::regclass);


--
-- Name: sec_filings_cache id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.sec_filings_cache ALTER COLUMN id SET DEFAULT nextval('meta.sec_filings_cache_id_seq'::regclass);


--
-- Name: semantic_attractors id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_attractors ALTER COLUMN id SET DEFAULT nextval('meta.semantic_attractors_id_seq'::regclass);


--
-- Name: semantic_regions region_id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_regions ALTER COLUMN region_id SET DEFAULT nextval('meta.semantic_regions_region_id_seq'::regclass);


--
-- Name: swarm_agent_positions id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.swarm_agent_positions ALTER COLUMN id SET DEFAULT nextval('meta.swarm_agent_positions_id_seq'::regclass);


--
-- Name: swarm_snapshots snapshot_id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.swarm_snapshots ALTER COLUMN snapshot_id SET DEFAULT nextval('meta.swarm_snapshots_snapshot_id_seq'::regclass);


--
-- Name: topology_drift id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.topology_drift ALTER COLUMN id SET DEFAULT nextval('meta.topology_drift_id_seq'::regclass);


--
-- Name: activity_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_events ALTER COLUMN id SET DEFAULT nextval('public.activity_events_id_seq'::regclass);


--
-- Name: agenda_incidents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_incidents ALTER COLUMN id SET DEFAULT nextval('public.agenda_incidents_id_seq'::regclass);


--
-- Name: agenda_operations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_operations ALTER COLUMN id SET DEFAULT nextval('public.agenda_operations_id_seq'::regclass);


--
-- Name: agenda_phase_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_phase_events ALTER COLUMN id SET DEFAULT nextval('public.agenda_phase_events_id_seq'::regclass);


--
-- Name: agent_evaluations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_evaluations ALTER COLUMN id SET DEFAULT nextval('public.agent_evaluations_id_seq'::regclass);


--
-- Name: aiops_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aiops_events ALTER COLUMN id SET DEFAULT nextval('public.aiops_events_id_seq'::regclass);


--
-- Name: archive_rotations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archive_rotations ALTER COLUMN id SET DEFAULT nextval('public.archive_rotations_id_seq'::regclass);


--
-- Name: calibration_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calibration_summaries ALTER COLUMN id SET DEFAULT nextval('public.calibration_summaries_id_seq'::regclass);


--
-- Name: cognition_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cognition_cycles ALTER COLUMN id SET DEFAULT nextval('public.cognition_cycles_id_seq'::regclass);


--
-- Name: command_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history ALTER COLUMN id SET DEFAULT nextval('public.command_history_id_seq'::regclass);


--
-- Name: content_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items ALTER COLUMN id SET DEFAULT nextval('public.content_items_id_seq'::regclass);


--
-- Name: corpus_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corpus_versions ALTER COLUMN id SET DEFAULT nextval('public.corpus_versions_id_seq'::regclass);


--
-- Name: daily_eval_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_eval_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_eval_summaries_id_seq'::regclass);


--
-- Name: daily_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_summaries_id_seq'::regclass);


--
-- Name: doc_archives id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_archives ALTER COLUMN id SET DEFAULT nextval('public.doc_archives_id_seq'::regclass);


--
-- Name: document_topics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_topics ALTER COLUMN id SET DEFAULT nextval('public.document_topics_id_seq'::regclass);


--
-- Name: engine_observations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations ALTER COLUMN id SET DEFAULT nextval('public.engine_observations_id_seq'::regclass);


--
-- Name: evolution_calibrations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_calibrations ALTER COLUMN id SET DEFAULT nextval('public.evolution_calibrations_id_seq'::regclass);


--
-- Name: evolution_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_cycles ALTER COLUMN id SET DEFAULT nextval('public.evolution_cycles_id_seq'::regclass);


--
-- Name: external_routing_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_routing_metrics ALTER COLUMN id SET DEFAULT nextval('public.external_routing_metrics_id_seq'::regclass);


--
-- Name: feed_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feed_sources ALTER COLUMN id SET DEFAULT nextval('public.feed_sources_id_seq'::regclass);


--
-- Name: fetch_jobs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs ALTER COLUMN id SET DEFAULT nextval('public.fetch_jobs_id_seq'::regclass);


--
-- Name: fmea_adjustments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_adjustments ALTER COLUMN id SET DEFAULT nextval('public.fmea_adjustments_id_seq'::regclass);


--
-- Name: fmea_occurrences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_occurrences ALTER COLUMN id SET DEFAULT nextval('public.fmea_occurrences_id_seq'::regclass);


--
-- Name: fmea_outcomes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_outcomes ALTER COLUMN id SET DEFAULT nextval('public.fmea_outcomes_id_seq'::regclass);


--
-- Name: github_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_issues ALTER COLUMN id SET DEFAULT nextval('public.github_issues_id_seq'::regclass);


--
-- Name: grid_allocations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_allocations ALTER COLUMN id SET DEFAULT nextval('public.grid_allocations_id_seq'::regclass);


--
-- Name: grid_clusters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_clusters ALTER COLUMN id SET DEFAULT nextval('public.grid_clusters_id_seq'::regclass);


--
-- Name: grid_embeddings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_embeddings ALTER COLUMN id SET DEFAULT nextval('public.grid_embeddings_id_seq'::regclass);


--
-- Name: grid_points id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_points ALTER COLUMN id SET DEFAULT nextval('public.grid_points_id_seq'::regclass);


--
-- Name: grid_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_snapshots ALTER COLUMN id SET DEFAULT nextval('public.grid_snapshots_id_seq'::regclass);


--
-- Name: grid_tda_features id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_tda_features ALTER COLUMN id SET DEFAULT nextval('public.grid_tda_features_id_seq'::regclass);


--
-- Name: healing_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events ALTER COLUMN id SET DEFAULT nextval('public.healing_events_id_seq'::regclass);


--
-- Name: health_loop_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_loop_state ALTER COLUMN id SET DEFAULT nextval('public.health_loop_state_id_seq'::regclass);


--
-- Name: held_out_queries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_out_queries ALTER COLUMN id SET DEFAULT nextval('public.held_out_queries_id_seq'::regclass);


--
-- Name: kb_sync_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_runs ALTER COLUMN id SET DEFAULT nextval('public.kb_sync_runs_id_seq'::regclass);


--
-- Name: kb_sync_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_state ALTER COLUMN id SET DEFAULT nextval('public.kb_sync_state_id_seq'::regclass);


--
-- Name: kb_sync_targets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_targets ALTER COLUMN id SET DEFAULT nextval('public.kb_sync_targets_id_seq'::regclass);


--
-- Name: lineage_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lineage_events ALTER COLUMN id SET DEFAULT nextval('public.lineage_events_id_seq'::regclass);


--
-- Name: mlops_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mlops_events ALTER COLUMN id SET DEFAULT nextval('public.mlops_events_id_seq'::regclass);


--
-- Name: objective_verifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objective_verifications ALTER COLUMN id SET DEFAULT nextval('public.objective_verifications_id_seq'::regclass);


--
-- Name: optimization_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs ALTER COLUMN id SET DEFAULT nextval('public.optimization_runs_id_seq'::regclass);


--
-- Name: paper_scores id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_scores ALTER COLUMN id SET DEFAULT nextval('public.paper_scores_id_seq'::regclass);


--
-- Name: profile_domains id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_domains ALTER COLUMN id SET DEFAULT nextval('public.profile_domains_id_seq'::regclass);


--
-- Name: profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles ALTER COLUMN id SET DEFAULT nextval('public.profiles_id_seq'::regclass);


--
-- Name: remediation_approvals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remediation_approvals ALTER COLUMN id SET DEFAULT nextval('public.remediation_approvals_id_seq'::regclass);


--
-- Name: scheduled_jobs_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_jobs_config ALTER COLUMN id SET DEFAULT nextval('public.scheduled_jobs_config_id_seq'::regclass);


--
-- Name: scheduled_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks ALTER COLUMN id SET DEFAULT nextval('public.scheduled_tasks_id_seq'::regclass);


--
-- Name: scoring_rubrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rubrics ALTER COLUMN id SET DEFAULT nextval('public.scoring_rubrics_id_seq'::regclass);


--
-- Name: state_changes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_changes ALTER COLUMN id SET DEFAULT nextval('public.state_changes_id_seq'::regclass);


--
-- Name: summary_lineage id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage ALTER COLUMN id SET DEFAULT nextval('public.summary_lineage_id_seq'::regclass);


--
-- Name: theta_consolidation_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.theta_consolidation_runs ALTER COLUMN id SET DEFAULT nextval('public.theta_consolidation_runs_id_seq'::regclass);


--
-- Name: topic_models id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_models ALTER COLUMN id SET DEFAULT nextval('public.topic_models_id_seq'::regclass);


--
-- Name: triage_assessments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.triage_assessments ALTER COLUMN id SET DEFAULT nextval('public.triage_assessments_id_seq'::regclass);


--
-- Name: user_interests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_interests ALTER COLUMN id SET DEFAULT nextval('public.user_interests_id_seq'::regclass);


--
-- Name: x_api_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_api_requests ALTER COLUMN id SET DEFAULT nextval('public.x_api_requests_id_seq'::regclass);


--
-- Name: x_sync_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_sync_runs ALTER COLUMN id SET DEFAULT nextval('public.x_sync_runs_id_seq'::regclass);


--
-- Name: _ag_label_edge _ag_label_edge_pkey; Type: CONSTRAINT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx._ag_label_edge
    ADD CONSTRAINT _ag_label_edge_pkey PRIMARY KEY (id);


--
-- Name: _ag_label_vertex _ag_label_vertex_pkey; Type: CONSTRAINT; Schema: gaius_hx; Owner: -
--

ALTER TABLE ONLY gaius_hx._ag_label_vertex
    ADD CONSTRAINT _ag_label_vertex_pkey PRIMARY KEY (id);


--
-- Name: agent_performance agent_performance_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.agent_performance
    ADD CONSTRAINT agent_performance_pkey PRIMARY KEY (agent_id, date);


--
-- Name: alert_thresholds alert_thresholds_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.alert_thresholds
    ADD CONSTRAINT alert_thresholds_pkey PRIMARY KEY (metric_name);


--
-- Name: audit_budget_pool audit_budget_pool_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.audit_budget_pool
    ADD CONSTRAINT audit_budget_pool_pkey PRIMARY KEY (pool_id);


--
-- Name: audit_recommendations audit_recommendations_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.audit_recommendations
    ADD CONSTRAINT audit_recommendations_pkey PRIMARY KEY (id);


--
-- Name: data_dependencies data_dependencies_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies
    ADD CONSTRAINT data_dependencies_pkey PRIMARY KEY (id);


--
-- Name: data_dependencies data_dependencies_source_dataset_id_target_dataset_id_via_j_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies
    ADD CONSTRAINT data_dependencies_source_dataset_id_target_dataset_id_via_j_key UNIQUE (source_dataset_id, target_dataset_id, via_job_id);


--
-- Name: dataset_catalog dataset_catalog_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.dataset_catalog
    ADD CONSTRAINT dataset_catalog_pkey PRIMARY KEY (dataset_id);


--
-- Name: document_clusters document_clusters_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.document_clusters
    ADD CONSTRAINT document_clusters_pkey PRIMARY KEY (id);


--
-- Name: flow_events flow_events_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.flow_events
    ADD CONSTRAINT flow_events_pkey PRIMARY KEY (event_id);


--
-- Name: flow_runs flow_runs_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.flow_runs
    ADD CONSTRAINT flow_runs_pkey PRIMARY KEY (run_id);


--
-- Name: fmea_rpn_timeseries fmea_rpn_timeseries_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.fmea_rpn_timeseries
    ADD CONSTRAINT fmea_rpn_timeseries_pkey PRIMARY KEY (failure_mode_id, hour);


--
-- Name: fmp_sync_runs fmp_sync_runs_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.fmp_sync_runs
    ADD CONSTRAINT fmp_sync_runs_pkey PRIMARY KEY (id);


--
-- Name: gpu_hourly_stats gpu_hourly_stats_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.gpu_hourly_stats
    ADD CONSTRAINT gpu_hourly_stats_pkey PRIMARY KEY (hour, gpu_index);


--
-- Name: gpu_minute_stats gpu_minute_stats_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.gpu_minute_stats
    ADD CONSTRAINT gpu_minute_stats_pkey PRIMARY KEY (minute, gpu_index);


--
-- Name: gpu_utilization gpu_utilization_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.gpu_utilization
    ADD CONSTRAINT gpu_utilization_pkey PRIMARY KEY ("timestamp", gpu_index);


--
-- Name: inference_hourly inference_hourly_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.inference_hourly
    ADD CONSTRAINT inference_hourly_pkey PRIMARY KEY (hour, model, endpoint);


--
-- Name: inference_throughput inference_throughput_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.inference_throughput
    ADD CONSTRAINT inference_throughput_pkey PRIMARY KEY (hour, model);


--
-- Name: institutional_holders_cache institutional_holders_cache_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.institutional_holders_cache
    ADD CONSTRAINT institutional_holders_cache_pkey PRIMARY KEY (id);


--
-- Name: institutional_holders_cache institutional_holders_cache_symbol_holder_name_filing_date_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.institutional_holders_cache
    ADD CONSTRAINT institutional_holders_cache_symbol_holder_name_filing_date_key UNIQUE (symbol, holder_name, filing_date);


--
-- Name: job_catalog job_catalog_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.job_catalog
    ADD CONSTRAINT job_catalog_pkey PRIMARY KEY (job_id);


--
-- Name: kb_topology kb_topology_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.kb_topology
    ADD CONSTRAINT kb_topology_pkey PRIMARY KEY (snapshot_id);


--
-- Name: lineage_sankey_agg lineage_sankey_agg_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.lineage_sankey_agg
    ADD CONSTRAINT lineage_sankey_agg_pkey PRIMARY KEY (time_window, window_start, source_namespace, source_name, target_namespace, target_name, via_job);


--
-- Name: metaagent_audits metaagent_audits_audit_id_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metaagent_audits
    ADD CONSTRAINT metaagent_audits_audit_id_key UNIQUE (audit_id);


--
-- Name: metaagent_audits metaagent_audits_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metaagent_audits
    ADD CONSTRAINT metaagent_audits_pkey PRIMARY KEY (id);


--
-- Name: metaagent_queries metaagent_queries_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metaagent_queries
    ADD CONSTRAINT metaagent_queries_pkey PRIMARY KEY (query_hash);


--
-- Name: metabase_models metabase_models_card_id_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metabase_models
    ADD CONSTRAINT metabase_models_card_id_key UNIQUE (card_id);


--
-- Name: metabase_models metabase_models_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metabase_models
    ADD CONSTRAINT metabase_models_pkey PRIMARY KEY (id);


--
-- Name: metabase_sync_runs metabase_sync_runs_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.metabase_sync_runs
    ADD CONSTRAINT metabase_sync_runs_pkey PRIMARY KEY (id);


--
-- Name: ngrc_models ngrc_models_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.ngrc_models
    ADD CONSTRAINT ngrc_models_pkey PRIMARY KEY (id);


--
-- Name: nifi_flows nifi_flows_flow_id_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.nifi_flows
    ADD CONSTRAINT nifi_flows_flow_id_key UNIQUE (flow_id);


--
-- Name: nifi_flows nifi_flows_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.nifi_flows
    ADD CONSTRAINT nifi_flows_pkey PRIMARY KEY (id);


--
-- Name: phase_change_profiles phase_change_profiles_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.phase_change_profiles
    ADD CONSTRAINT phase_change_profiles_pkey PRIMARY KEY (change_type);


--
-- Name: prospect_candidates prospect_candidates_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_candidates
    ADD CONSTRAINT prospect_candidates_pkey PRIMARY KEY (id);


--
-- Name: prospect_candidates prospect_candidates_symbol_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_candidates
    ADD CONSTRAINT prospect_candidates_symbol_key UNIQUE (symbol);


--
-- Name: prospect_strategies prospect_strategies_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_strategies
    ADD CONSTRAINT prospect_strategies_pkey PRIMARY KEY (id);


--
-- Name: prospect_strategies prospect_strategies_symbol_profile_domain_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_strategies
    ADD CONSTRAINT prospect_strategies_symbol_profile_domain_key UNIQUE (symbol, profile, domain);


--
-- Name: quality_assessments quality_assessments_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.quality_assessments
    ADD CONSTRAINT quality_assessments_pkey PRIMARY KEY (id);


--
-- Name: research_progress research_progress_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.research_progress
    ADD CONSTRAINT research_progress_pkey PRIMARY KEY (event_id);


--
-- Name: research_state research_state_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.research_state
    ADD CONSTRAINT research_state_pkey PRIMARY KEY (session_id);


--
-- Name: sec_filings_cache sec_filings_cache_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.sec_filings_cache
    ADD CONSTRAINT sec_filings_cache_pkey PRIMARY KEY (id);


--
-- Name: sec_filings_cache sec_filings_cache_symbol_filing_type_filing_date_key; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.sec_filings_cache
    ADD CONSTRAINT sec_filings_cache_symbol_filing_type_filing_date_key UNIQUE (symbol, filing_type, filing_date);


--
-- Name: semantic_attractors semantic_attractors_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_attractors
    ADD CONSTRAINT semantic_attractors_pkey PRIMARY KEY (id);


--
-- Name: semantic_regions semantic_regions_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_regions
    ADD CONSTRAINT semantic_regions_pkey PRIMARY KEY (region_id);


--
-- Name: swarm_agent_positions swarm_agent_positions_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.swarm_agent_positions
    ADD CONSTRAINT swarm_agent_positions_pkey PRIMARY KEY (id);


--
-- Name: swarm_snapshots swarm_snapshots_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.swarm_snapshots
    ADD CONSTRAINT swarm_snapshots_pkey PRIMARY KEY (snapshot_id);


--
-- Name: sync_watermarks sync_watermarks_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.sync_watermarks
    ADD CONSTRAINT sync_watermarks_pkey PRIMARY KEY (sync_type);


--
-- Name: topology_drift topology_drift_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.topology_drift
    ADD CONSTRAINT topology_drift_pkey PRIMARY KEY (id);


--
-- Name: action action_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT action_entity_id_key UNIQUE (entity_id);


--
-- Name: action action_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT action_pkey PRIMARY KEY (id);


--
-- Name: action action_public_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT action_public_uuid_key UNIQUE (public_uuid);


--
-- Name: activity_events activity_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_events
    ADD CONSTRAINT activity_events_pkey PRIMARY KEY (id);


--
-- Name: agenda_incidents agenda_incidents_incident_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_incidents
    ADD CONSTRAINT agenda_incidents_incident_id_key UNIQUE (incident_id);


--
-- Name: agenda_incidents agenda_incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_incidents
    ADD CONSTRAINT agenda_incidents_pkey PRIMARY KEY (id);


--
-- Name: agenda_operations agenda_operations_operation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_operations
    ADD CONSTRAINT agenda_operations_operation_id_key UNIQUE (operation_id);


--
-- Name: agenda_operations agenda_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_operations
    ADD CONSTRAINT agenda_operations_pkey PRIMARY KEY (id);


--
-- Name: agenda_phase_events agenda_phase_events_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_phase_events
    ADD CONSTRAINT agenda_phase_events_event_id_key UNIQUE (event_id);


--
-- Name: agenda_phase_events agenda_phase_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_phase_events
    ADD CONSTRAINT agenda_phase_events_pkey PRIMARY KEY (id);


--
-- Name: agent_evaluations agent_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_evaluations
    ADD CONSTRAINT agent_evaluations_pkey PRIMARY KEY (id);


--
-- Name: agent_versions agent_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (version_id);


--
-- Name: aiops_events aiops_events_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aiops_events
    ADD CONSTRAINT aiops_events_event_id_key UNIQUE (event_id);


--
-- Name: aiops_events aiops_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aiops_events
    ADD CONSTRAINT aiops_events_pkey PRIMARY KEY (id);


--
-- Name: ambient_daemon_state ambient_daemon_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ambient_daemon_state
    ADD CONSTRAINT ambient_daemon_state_pkey PRIMARY KEY (id);


--
-- Name: api_key api_key_key_prefix_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT api_key_key_prefix_key UNIQUE (key_prefix);


--
-- Name: api_key api_key_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT api_key_name_key UNIQUE (name);


--
-- Name: api_key api_key_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT api_key_pkey PRIMARY KEY (id);


--
-- Name: archive_rotations archive_rotations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archive_rotations
    ADD CONSTRAINT archive_rotations_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: bookmark_ordering bookmark_ordering_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bookmark_ordering
    ADD CONSTRAINT bookmark_ordering_pkey PRIMARY KEY (id);


--
-- Name: cache_config cache_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_config
    ADD CONSTRAINT cache_config_pkey PRIMARY KEY (id);


--
-- Name: calibration_summaries calibration_summaries_agent_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calibration_summaries
    ADD CONSTRAINT calibration_summaries_agent_id_key UNIQUE (agent_id);


--
-- Name: calibration_summaries calibration_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calibration_summaries
    ADD CONSTRAINT calibration_summaries_pkey PRIMARY KEY (id);


--
-- Name: card_bookmark card_bookmark_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_bookmark
    ADD CONSTRAINT card_bookmark_pkey PRIMARY KEY (id);


--
-- Name: card_label card_label_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_label
    ADD CONSTRAINT card_label_pkey PRIMARY KEY (id);


--
-- Name: channel channel_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel
    ADD CONSTRAINT channel_name_key UNIQUE (name);


--
-- Name: channel channel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel
    ADD CONSTRAINT channel_pkey PRIMARY KEY (id);


--
-- Name: channel_template channel_template_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_template
    ADD CONSTRAINT channel_template_pkey PRIMARY KEY (id);


--
-- Name: cloud_migration cloud_migration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cloud_migration
    ADD CONSTRAINT cloud_migration_pkey PRIMARY KEY (id);


--
-- Name: cognition_cycles cognition_cycles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cognition_cycles
    ADD CONSTRAINT cognition_cycles_pkey PRIMARY KEY (id);


--
-- Name: cognition_thoughts cognition_thoughts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cognition_thoughts
    ADD CONSTRAINT cognition_thoughts_pkey PRIMARY KEY (id);


--
-- Name: collection_bookmark collection_bookmark_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_bookmark
    ADD CONSTRAINT collection_bookmark_pkey PRIMARY KEY (id);


--
-- Name: collection collection_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection
    ADD CONSTRAINT collection_entity_id_key UNIQUE (entity_id);


--
-- Name: collection collection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection
    ADD CONSTRAINT collection_pkey PRIMARY KEY (id);


--
-- Name: collection_permission_graph_revision collection_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_permission_graph_revision
    ADD CONSTRAINT collection_revision_pkey PRIMARY KEY (id);


--
-- Name: command_history command_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_pkey PRIMARY KEY (id);


--
-- Name: connection_impersonations conn_impersonation_unique_group_id_db_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.connection_impersonations
    ADD CONSTRAINT conn_impersonation_unique_group_id_db_id UNIQUE (group_id, db_id);


--
-- Name: connection_impersonations connection_impersonations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.connection_impersonations
    ADD CONSTRAINT connection_impersonations_pkey PRIMARY KEY (id);


--
-- Name: content_items content_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_pkey PRIMARY KEY (id);


--
-- Name: content_items content_items_source_id_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_source_id_external_id_key UNIQUE (source_id, external_id);


--
-- Name: content_translation content_translation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_translation
    ADD CONSTRAINT content_translation_pkey PRIMARY KEY (id);


--
-- Name: core_session core_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_session
    ADD CONSTRAINT core_session_pkey PRIMARY KEY (id);


--
-- Name: core_user core_user_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_user
    ADD CONSTRAINT core_user_email_key UNIQUE (email);


--
-- Name: core_user core_user_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_user
    ADD CONSTRAINT core_user_entity_id_key UNIQUE (entity_id);


--
-- Name: core_user core_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_user
    ADD CONSTRAINT core_user_pkey PRIMARY KEY (id);


--
-- Name: corpus_versions corpus_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corpus_versions
    ADD CONSTRAINT corpus_versions_pkey PRIMARY KEY (id);


--
-- Name: corpus_versions corpus_versions_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corpus_versions
    ADD CONSTRAINT corpus_versions_version_id_key UNIQUE (version_id);


--
-- Name: current_state current_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.current_state
    ADD CONSTRAINT current_state_pkey PRIMARY KEY (kb_root);


--
-- Name: daily_eval_summaries daily_eval_summaries_eval_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_eval_summaries
    ADD CONSTRAINT daily_eval_summaries_eval_date_key UNIQUE (eval_date);


--
-- Name: daily_eval_summaries daily_eval_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_eval_summaries
    ADD CONSTRAINT daily_eval_summaries_pkey PRIMARY KEY (id);


--
-- Name: daily_summaries daily_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries
    ADD CONSTRAINT daily_summaries_pkey PRIMARY KEY (id);


--
-- Name: daily_summaries daily_summaries_summary_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries
    ADD CONSTRAINT daily_summaries_summary_date_key UNIQUE (summary_date);


--
-- Name: dashboard_bookmark dashboard_bookmark_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_bookmark
    ADD CONSTRAINT dashboard_bookmark_pkey PRIMARY KEY (id);


--
-- Name: dashboard_favorite dashboard_favorite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_favorite
    ADD CONSTRAINT dashboard_favorite_pkey PRIMARY KEY (id);


--
-- Name: dashboard_tab dashboard_tab_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_tab
    ADD CONSTRAINT dashboard_tab_entity_id_key UNIQUE (entity_id);


--
-- Name: dashboard_tab dashboard_tab_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_tab
    ADD CONSTRAINT dashboard_tab_pkey PRIMARY KEY (id);


--
-- Name: dashboardcard_series dashboardcard_series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboardcard_series
    ADD CONSTRAINT dashboardcard_series_pkey PRIMARY KEY (id);


--
-- Name: data_permissions data_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_permissions
    ADD CONSTRAINT data_permissions_pkey PRIMARY KEY (id);


--
-- Name: db_router db_router_database_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.db_router
    ADD CONSTRAINT db_router_database_id_key UNIQUE (database_id);


--
-- Name: db_router db_router_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.db_router
    ADD CONSTRAINT db_router_pkey PRIMARY KEY (id);


--
-- Name: dependency dependency_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dependency
    ADD CONSTRAINT dependency_pkey PRIMARY KEY (id);


--
-- Name: dimension dimension_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dimension
    ADD CONSTRAINT dimension_entity_id_key UNIQUE (entity_id);


--
-- Name: dimension dimension_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dimension
    ADD CONSTRAINT dimension_pkey PRIMARY KEY (id);


--
-- Name: doc_archives doc_archives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_archives
    ADD CONSTRAINT doc_archives_pkey PRIMARY KEY (id);


--
-- Name: doc_archives doc_archives_source_id_archive_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_archives
    ADD CONSTRAINT doc_archives_source_id_archive_url_key UNIQUE (source_id, archive_url);


--
-- Name: document_topics document_topics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_topics
    ADD CONSTRAINT document_topics_pkey PRIMARY KEY (id);


--
-- Name: engine_observations engine_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations
    ADD CONSTRAINT engine_observations_pkey PRIMARY KEY (id);


--
-- Name: evolution_calibrations evolution_calibrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_calibrations
    ADD CONSTRAINT evolution_calibrations_pkey PRIMARY KEY (id);


--
-- Name: evolution_cycles evolution_cycles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_cycles
    ADD CONSTRAINT evolution_cycles_pkey PRIMARY KEY (id);


--
-- Name: external_routing_metrics external_routing_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_routing_metrics
    ADD CONSTRAINT external_routing_metrics_pkey PRIMARY KEY (id);


--
-- Name: feed_sources feed_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feed_sources
    ADD CONSTRAINT feed_sources_pkey PRIMARY KEY (id);


--
-- Name: fetch_jobs fetch_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs
    ADD CONSTRAINT fetch_jobs_pkey PRIMARY KEY (id);


--
-- Name: field_usage field_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_usage
    ADD CONSTRAINT field_usage_pkey PRIMARY KEY (id);


--
-- Name: fmea_adjustments fmea_adjustments_failure_mode_id_endpoint_hour_of_day_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_adjustments
    ADD CONSTRAINT fmea_adjustments_failure_mode_id_endpoint_hour_of_day_key UNIQUE (failure_mode_id, endpoint, hour_of_day);


--
-- Name: fmea_adjustments fmea_adjustments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_adjustments
    ADD CONSTRAINT fmea_adjustments_pkey PRIMARY KEY (id);


--
-- Name: fmea_catalog fmea_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_catalog
    ADD CONSTRAINT fmea_catalog_pkey PRIMARY KEY (failure_mode_id);


--
-- Name: fmea_occurrences fmea_occurrences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_occurrences
    ADD CONSTRAINT fmea_occurrences_pkey PRIMARY KEY (id);


--
-- Name: fmea_outcomes fmea_outcomes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_outcomes
    ADD CONSTRAINT fmea_outcomes_pkey PRIMARY KEY (id);


--
-- Name: application_permissions_revision general_permissions_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_permissions_revision
    ADD CONSTRAINT general_permissions_revision_pkey PRIMARY KEY (id);


--
-- Name: github_issues github_issues_fingerprint_repo_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_issues
    ADD CONSTRAINT github_issues_fingerprint_repo_key UNIQUE (fingerprint, repo);


--
-- Name: github_issues github_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_issues
    ADD CONSTRAINT github_issues_pkey PRIMARY KEY (id);


--
-- Name: grid_allocations grid_allocations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_allocations
    ADD CONSTRAINT grid_allocations_pkey PRIMARY KEY (id);


--
-- Name: grid_allocations grid_allocations_snapshot_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_allocations
    ADD CONSTRAINT grid_allocations_snapshot_id_key UNIQUE (snapshot_id);


--
-- Name: grid_clusters grid_clusters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_clusters
    ADD CONSTRAINT grid_clusters_pkey PRIMARY KEY (id);


--
-- Name: grid_clusters grid_clusters_snapshot_id_x_y_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_clusters
    ADD CONSTRAINT grid_clusters_snapshot_id_x_y_key UNIQUE (snapshot_id, x, y);


--
-- Name: grid_embeddings grid_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_embeddings
    ADD CONSTRAINT grid_embeddings_pkey PRIMARY KEY (id);


--
-- Name: grid_embeddings grid_embeddings_snapshot_id_embedding_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_embeddings
    ADD CONSTRAINT grid_embeddings_snapshot_id_embedding_index_key UNIQUE (snapshot_id, embedding_index);


--
-- Name: grid_points grid_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_points
    ADD CONSTRAINT grid_points_pkey PRIMARY KEY (id);


--
-- Name: grid_points grid_points_snapshot_id_embedding_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_points
    ADD CONSTRAINT grid_points_snapshot_id_embedding_id_key UNIQUE (snapshot_id, embedding_id);


--
-- Name: grid_snapshots grid_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_snapshots
    ADD CONSTRAINT grid_snapshots_pkey PRIMARY KEY (id);


--
-- Name: grid_tda_features grid_tda_features_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_tda_features
    ADD CONSTRAINT grid_tda_features_pkey PRIMARY KEY (id);


--
-- Name: grid_tda_features grid_tda_features_snapshot_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_tda_features
    ADD CONSTRAINT grid_tda_features_snapshot_id_key UNIQUE (snapshot_id);


--
-- Name: sandboxes group_table_access_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandboxes
    ADD CONSTRAINT group_table_access_policy_pkey PRIMARY KEY (id);


--
-- Name: healing_events healing_events_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events
    ADD CONSTRAINT healing_events_event_id_key UNIQUE (event_id);


--
-- Name: healing_events healing_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events
    ADD CONSTRAINT healing_events_pkey PRIMARY KEY (id);


--
-- Name: healing_events healing_events_sequence_id_sequence_num_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events
    ADD CONSTRAINT healing_events_sequence_id_sequence_num_key UNIQUE (sequence_id, sequence_num);


--
-- Name: health_loop_state health_loop_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_loop_state
    ADD CONSTRAINT health_loop_state_pkey PRIMARY KEY (id);


--
-- Name: health_observer_state health_observer_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.health_observer_state
    ADD CONSTRAINT health_observer_state_pkey PRIMARY KEY (id);


--
-- Name: held_out_queries held_out_queries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_out_queries
    ADD CONSTRAINT held_out_queries_pkey PRIMARY KEY (id);


--
-- Name: held_out_queries held_out_queries_query_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_out_queries
    ADD CONSTRAINT held_out_queries_query_hash_key UNIQUE (query_hash);


--
-- Name: iceberg_config iceberg_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iceberg_config
    ADD CONSTRAINT iceberg_config_pkey PRIMARY KEY (key);


--
-- Name: iceberg_namespace_properties iceberg_namespace_properties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iceberg_namespace_properties
    ADD CONSTRAINT iceberg_namespace_properties_pkey PRIMARY KEY (catalog_name, namespace, property_key);


--
-- Name: iceberg_tables iceberg_tables_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iceberg_tables
    ADD CONSTRAINT iceberg_tables_pkey PRIMARY KEY (catalog_name, table_namespace, table_name);


--
-- Name: cache_config idx_cache_config_unique_model; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_config
    ADD CONSTRAINT idx_cache_config_unique_model UNIQUE (model, model_id);


--
-- Name: databasechangelog idx_databasechangelog_id_author_filename; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.databasechangelog
    ADD CONSTRAINT idx_databasechangelog_id_author_filename UNIQUE (id, author, filename);


--
-- Name: search_index_metadata idx_search_index_metadata_unique_status; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index_metadata
    ADD CONSTRAINT idx_search_index_metadata_unique_status UNIQUE (engine, version, lang_code, status);


--
-- Name: metabase_table idx_uniq_table_db_id_schema_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_table
    ADD CONSTRAINT idx_uniq_table_db_id_schema_name UNIQUE (db_id, schema, name);


--
-- Name: report_cardfavorite idx_unique_cardfavorite_card_id_owner_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_cardfavorite
    ADD CONSTRAINT idx_unique_cardfavorite_card_id_owner_id UNIQUE (card_id, owner_id);


--
-- Name: metabase_field idx_unique_field; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field
    ADD CONSTRAINT idx_unique_field UNIQUE (name, table_id, unique_field_helper);


--
-- Name: metabase_database idx_unique_metabase_database_router_database_id_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_database
    ADD CONSTRAINT idx_unique_metabase_database_router_database_id_name UNIQUE (router_database_id, name);


--
-- Name: metabase_table idx_unique_table; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_table
    ADD CONSTRAINT idx_unique_table UNIQUE (db_id, name, unique_table_helper);


--
-- Name: kb_sync_runs kb_sync_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_runs
    ADD CONSTRAINT kb_sync_runs_pkey PRIMARY KEY (id);


--
-- Name: kb_sync_state kb_sync_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_state
    ADD CONSTRAINT kb_sync_state_pkey PRIMARY KEY (id);


--
-- Name: kb_sync_state kb_sync_state_target_id_file_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_state
    ADD CONSTRAINT kb_sync_state_target_id_file_path_key UNIQUE (target_id, file_path);


--
-- Name: kb_sync_targets kb_sync_targets_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_targets
    ADD CONSTRAINT kb_sync_targets_name_key UNIQUE (name);


--
-- Name: kb_sync_targets kb_sync_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_targets
    ADD CONSTRAINT kb_sync_targets_pkey PRIMARY KEY (id);


--
-- Name: label label_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.label
    ADD CONSTRAINT label_pkey PRIMARY KEY (id);


--
-- Name: label label_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.label
    ADD CONSTRAINT label_slug_key UNIQUE (slug);


--
-- Name: lineage_events lineage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lineage_events
    ADD CONSTRAINT lineage_events_pkey PRIMARY KEY (id);


--
-- Name: login_history login_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_history
    ADD CONSTRAINT login_history_pkey PRIMARY KEY (id);


--
-- Name: metabase_cluster_lock metabase_cluster_lock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_cluster_lock
    ADD CONSTRAINT metabase_cluster_lock_pkey PRIMARY KEY (lock_name);


--
-- Name: metabase_database metabase_database_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_database
    ADD CONSTRAINT metabase_database_pkey PRIMARY KEY (id);


--
-- Name: metabase_field metabase_field_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field
    ADD CONSTRAINT metabase_field_pkey PRIMARY KEY (id);


--
-- Name: metabase_field_user_settings metabase_field_user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field_user_settings
    ADD CONSTRAINT metabase_field_user_settings_pkey PRIMARY KEY (field_id);


--
-- Name: metabase_fieldvalues metabase_fieldvalues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_fieldvalues
    ADD CONSTRAINT metabase_fieldvalues_pkey PRIMARY KEY (id);


--
-- Name: metabase_table metabase_table_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_table
    ADD CONSTRAINT metabase_table_pkey PRIMARY KEY (id);


--
-- Name: metabot_conversation metabot_conversation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_conversation
    ADD CONSTRAINT metabot_conversation_pkey PRIMARY KEY (id);


--
-- Name: metabot_entity metabot_entity_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_entity
    ADD CONSTRAINT metabot_entity_entity_id_key UNIQUE (entity_id);


--
-- Name: metabot metabot_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot
    ADD CONSTRAINT metabot_entity_id_key UNIQUE (entity_id);


--
-- Name: metabot_entity metabot_entity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_entity
    ADD CONSTRAINT metabot_entity_pkey PRIMARY KEY (id);


--
-- Name: metabot_message metabot_message_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_message
    ADD CONSTRAINT metabot_message_pkey PRIMARY KEY (id);


--
-- Name: metabot metabot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot
    ADD CONSTRAINT metabot_pkey PRIMARY KEY (id);


--
-- Name: metabot_prompt metabot_prompt_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_prompt
    ADD CONSTRAINT metabot_prompt_entity_id_key UNIQUE (entity_id);


--
-- Name: metabot_prompt metabot_prompt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_prompt
    ADD CONSTRAINT metabot_prompt_pkey PRIMARY KEY (id);


--
-- Name: metric metric_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric
    ADD CONSTRAINT metric_entity_id_key UNIQUE (entity_id);


--
-- Name: metric_important_field metric_important_field_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_important_field
    ADD CONSTRAINT metric_important_field_pkey PRIMARY KEY (id);


--
-- Name: metric metric_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric
    ADD CONSTRAINT metric_pkey PRIMARY KEY (id);


--
-- Name: mlops_events mlops_events_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mlops_events
    ADD CONSTRAINT mlops_events_event_id_key UNIQUE (event_id);


--
-- Name: mlops_events mlops_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mlops_events
    ADD CONSTRAINT mlops_events_pkey PRIMARY KEY (id);


--
-- Name: model_index model_index_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_index
    ADD CONSTRAINT model_index_pkey PRIMARY KEY (id);


--
-- Name: moderation_review moderation_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moderation_review
    ADD CONSTRAINT moderation_review_pkey PRIMARY KEY (id);


--
-- Name: native_query_snippet native_query_snippet_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_query_snippet
    ADD CONSTRAINT native_query_snippet_entity_id_key UNIQUE (entity_id);


--
-- Name: native_query_snippet native_query_snippet_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_query_snippet
    ADD CONSTRAINT native_query_snippet_name_key UNIQUE (name);


--
-- Name: native_query_snippet native_query_snippet_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_query_snippet
    ADD CONSTRAINT native_query_snippet_pkey PRIMARY KEY (id);


--
-- Name: notification_card notification_card_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_card
    ADD CONSTRAINT notification_card_pkey PRIMARY KEY (id);


--
-- Name: notification_handler notification_handler_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_handler
    ADD CONSTRAINT notification_handler_pkey PRIMARY KEY (id);


--
-- Name: notification notification_internal_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_internal_id_key UNIQUE (internal_id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (id);


--
-- Name: notification_recipient notification_recipient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_recipient
    ADD CONSTRAINT notification_recipient_pkey PRIMARY KEY (id);


--
-- Name: notification_subscription notification_subscription_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_subscription
    ADD CONSTRAINT notification_subscription_pkey PRIMARY KEY (id);


--
-- Name: objective_verifications objective_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objective_verifications
    ADD CONSTRAINT objective_verifications_pkey PRIMARY KEY (id);


--
-- Name: objective_verifications objective_verifications_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objective_verifications
    ADD CONSTRAINT objective_verifications_run_id_key UNIQUE (run_id);


--
-- Name: optimization_runs optimization_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs
    ADD CONSTRAINT optimization_runs_pkey PRIMARY KEY (id);


--
-- Name: paper_scores paper_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_scores
    ADD CONSTRAINT paper_scores_pkey PRIMARY KEY (id);


--
-- Name: parameter_card parameter_card_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parameter_card
    ADD CONSTRAINT parameter_card_pkey PRIMARY KEY (id);


--
-- Name: permissions_group permissions_group_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group
    ADD CONSTRAINT permissions_group_entity_id_key UNIQUE (entity_id);


--
-- Name: permissions permissions_group_id_object_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_group_id_object_key UNIQUE (group_id, object);


--
-- Name: permissions_group permissions_group_magic_group_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group
    ADD CONSTRAINT permissions_group_magic_group_type_key UNIQUE (magic_group_type);


--
-- Name: permissions_group_membership permissions_group_membership_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group_membership
    ADD CONSTRAINT permissions_group_membership_pkey PRIMARY KEY (id);


--
-- Name: permissions_group permissions_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group
    ADD CONSTRAINT permissions_group_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: permissions_revision permissions_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_revision
    ADD CONSTRAINT permissions_revision_pkey PRIMARY KEY (id);


--
-- Name: persisted_info persisted_info_card_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persisted_info
    ADD CONSTRAINT persisted_info_card_id_key UNIQUE (card_id);


--
-- Name: persisted_info persisted_info_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persisted_info
    ADD CONSTRAINT persisted_info_pkey PRIMARY KEY (id);


--
-- Name: http_action pk_http_action; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.http_action
    ADD CONSTRAINT pk_http_action PRIMARY KEY (action_id);


--
-- Name: implicit_action pk_implicit_action; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.implicit_action
    ADD CONSTRAINT pk_implicit_action PRIMARY KEY (action_id);


--
-- Name: qrtz_blob_triggers pk_qrtz_blob_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_blob_triggers
    ADD CONSTRAINT pk_qrtz_blob_triggers PRIMARY KEY (sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_calendars pk_qrtz_calendars; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_calendars
    ADD CONSTRAINT pk_qrtz_calendars PRIMARY KEY (sched_name, calendar_name);


--
-- Name: qrtz_cron_triggers pk_qrtz_cron_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_cron_triggers
    ADD CONSTRAINT pk_qrtz_cron_triggers PRIMARY KEY (sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_fired_triggers pk_qrtz_fired_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_fired_triggers
    ADD CONSTRAINT pk_qrtz_fired_triggers PRIMARY KEY (sched_name, entry_id);


--
-- Name: qrtz_job_details pk_qrtz_job_details; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_job_details
    ADD CONSTRAINT pk_qrtz_job_details PRIMARY KEY (sched_name, job_name, job_group);


--
-- Name: qrtz_locks pk_qrtz_locks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_locks
    ADD CONSTRAINT pk_qrtz_locks PRIMARY KEY (sched_name, lock_name);


--
-- Name: qrtz_scheduler_state pk_qrtz_scheduler_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_scheduler_state
    ADD CONSTRAINT pk_qrtz_scheduler_state PRIMARY KEY (sched_name, instance_name);


--
-- Name: qrtz_simple_triggers pk_qrtz_simple_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_simple_triggers
    ADD CONSTRAINT pk_qrtz_simple_triggers PRIMARY KEY (sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_simprop_triggers pk_qrtz_simprop_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_simprop_triggers
    ADD CONSTRAINT pk_qrtz_simprop_triggers PRIMARY KEY (sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_triggers pk_qrtz_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_triggers
    ADD CONSTRAINT pk_qrtz_triggers PRIMARY KEY (sched_name, trigger_name, trigger_group);


--
-- Name: query_action pk_query_action; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_action
    ADD CONSTRAINT pk_query_action PRIMARY KEY (action_id);


--
-- Name: qrtz_paused_trigger_grps pk_sched_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_paused_trigger_grps
    ADD CONSTRAINT pk_sched_name PRIMARY KEY (sched_name, trigger_group);


--
-- Name: profile_content profile_content_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_content
    ADD CONSTRAINT profile_content_pkey PRIMARY KEY (profile_id, content_id);


--
-- Name: profile_domains profile_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_domains
    ADD CONSTRAINT profile_domains_pkey PRIMARY KEY (id);


--
-- Name: profile_domains profile_domains_profile_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_domains
    ADD CONSTRAINT profile_domains_profile_id_name_key UNIQUE (profile_id, name);


--
-- Name: profile_sources profile_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_sources
    ADD CONSTRAINT profile_sources_pkey PRIMARY KEY (profile_id, source_id);


--
-- Name: profiles profiles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_name_key UNIQUE (name);


--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);


--
-- Name: pulse_card pulse_card_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_card
    ADD CONSTRAINT pulse_card_entity_id_key UNIQUE (entity_id);


--
-- Name: pulse_card pulse_card_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_card
    ADD CONSTRAINT pulse_card_pkey PRIMARY KEY (id);


--
-- Name: pulse_channel pulse_channel_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel
    ADD CONSTRAINT pulse_channel_entity_id_key UNIQUE (entity_id);


--
-- Name: pulse_channel pulse_channel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel
    ADD CONSTRAINT pulse_channel_pkey PRIMARY KEY (id);


--
-- Name: pulse_channel_recipient pulse_channel_recipient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel_recipient
    ADD CONSTRAINT pulse_channel_recipient_pkey PRIMARY KEY (id);


--
-- Name: pulse pulse_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT pulse_entity_id_key UNIQUE (entity_id);


--
-- Name: pulse pulse_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT pulse_pkey PRIMARY KEY (id);


--
-- Name: query_cache query_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_cache
    ADD CONSTRAINT query_cache_pkey PRIMARY KEY (query_hash);


--
-- Name: query_execution query_execution_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_execution
    ADD CONSTRAINT query_execution_pkey PRIMARY KEY (id);


--
-- Name: query_field query_field_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_field
    ADD CONSTRAINT query_field_pkey PRIMARY KEY (id);


--
-- Name: query query_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query
    ADD CONSTRAINT query_pkey PRIMARY KEY (query_hash);


--
-- Name: query_table query_table_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_table
    ADD CONSTRAINT query_table_pkey PRIMARY KEY (id);


--
-- Name: recent_views recent_views_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recent_views
    ADD CONSTRAINT recent_views_pkey PRIMARY KEY (id);


--
-- Name: remediation_approvals remediation_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remediation_approvals
    ADD CONSTRAINT remediation_approvals_pkey PRIMARY KEY (id);


--
-- Name: report_card report_card_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT report_card_entity_id_key UNIQUE (entity_id);


--
-- Name: report_card report_card_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT report_card_pkey PRIMARY KEY (id);


--
-- Name: report_card report_card_public_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT report_card_public_uuid_key UNIQUE (public_uuid);


--
-- Name: report_cardfavorite report_cardfavorite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_cardfavorite
    ADD CONSTRAINT report_cardfavorite_pkey PRIMARY KEY (id);


--
-- Name: report_dashboard report_dashboard_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT report_dashboard_entity_id_key UNIQUE (entity_id);


--
-- Name: report_dashboard report_dashboard_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT report_dashboard_pkey PRIMARY KEY (id);


--
-- Name: report_dashboard report_dashboard_public_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT report_dashboard_public_uuid_key UNIQUE (public_uuid);


--
-- Name: report_dashboardcard report_dashboardcard_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT report_dashboardcard_entity_id_key UNIQUE (entity_id);


--
-- Name: report_dashboardcard report_dashboardcard_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT report_dashboardcard_pkey PRIMARY KEY (id);


--
-- Name: research_threads research_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_threads
    ADD CONSTRAINT research_threads_pkey PRIMARY KEY (id);


--
-- Name: revision revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revision
    ADD CONSTRAINT revision_pkey PRIMARY KEY (id);


--
-- Name: routing_decisions routing_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_decisions
    ADD CONSTRAINT routing_decisions_pkey PRIMARY KEY (id);


--
-- Name: scheduled_jobs_config scheduled_jobs_config_job_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_jobs_config
    ADD CONSTRAINT scheduled_jobs_config_job_name_key UNIQUE (job_name);


--
-- Name: scheduled_jobs_config scheduled_jobs_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_jobs_config
    ADD CONSTRAINT scheduled_jobs_config_pkey PRIMARY KEY (id);


--
-- Name: scheduled_tasks scheduled_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT scheduled_tasks_pkey PRIMARY KEY (id);


--
-- Name: scheduler_jobs scheduler_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_jobs
    ADD CONSTRAINT scheduler_jobs_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: scoring_rubrics scoring_rubrics_name_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rubrics
    ADD CONSTRAINT scoring_rubrics_name_version_key UNIQUE (name, version);


--
-- Name: scoring_rubrics scoring_rubrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rubrics
    ADD CONSTRAINT scoring_rubrics_pkey PRIMARY KEY (id);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5 search_index__4asdmoroquqdnn2arfyd5_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index__4asdmoroquqdnn2arfyd5
    ADD CONSTRAINT search_index__4asdmoroquqdnn2arfyd5_pkey PRIMARY KEY (id);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6 search_index__cvo4ibtsyjzvh5x7v49a6_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index__cvo4ibtsyjzvh5x7v49a6
    ADD CONSTRAINT search_index__cvo4ibtsyjzvh5x7v49a6_pkey PRIMARY KEY (id);


--
-- Name: search_index_metadata search_index_metadata_index_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index_metadata
    ADD CONSTRAINT search_index_metadata_index_name_key UNIQUE (index_name);


--
-- Name: search_index_metadata search_index_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index_metadata
    ADD CONSTRAINT search_index_metadata_pkey PRIMARY KEY (id);


--
-- Name: secret secret_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret
    ADD CONSTRAINT secret_pkey PRIMARY KEY (id, version);


--
-- Name: segment segment_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segment
    ADD CONSTRAINT segment_entity_id_key UNIQUE (entity_id);


--
-- Name: segment segment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segment
    ADD CONSTRAINT segment_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: setting setting_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.setting
    ADD CONSTRAINT setting_pkey PRIMARY KEY (key);


--
-- Name: state_changes state_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_changes
    ADD CONSTRAINT state_changes_pkey PRIMARY KEY (id);


--
-- Name: summary_lineage summary_lineage_kb_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage
    ADD CONSTRAINT summary_lineage_kb_path_key UNIQUE (kb_path);


--
-- Name: summary_lineage summary_lineage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage
    ADD CONSTRAINT summary_lineage_pkey PRIMARY KEY (id);


--
-- Name: task_history task_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_history
    ADD CONSTRAINT task_history_pkey PRIMARY KEY (id);


--
-- Name: theta_consolidation_runs theta_consolidation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.theta_consolidation_runs
    ADD CONSTRAINT theta_consolidation_runs_pkey PRIMARY KEY (id);


--
-- Name: timeline timeline_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline
    ADD CONSTRAINT timeline_entity_id_key UNIQUE (entity_id);


--
-- Name: timeline_event timeline_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline_event
    ADD CONSTRAINT timeline_event_pkey PRIMARY KEY (id);


--
-- Name: timeline timeline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline
    ADD CONSTRAINT timeline_pkey PRIMARY KEY (id);


--
-- Name: topic_models topic_models_model_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_models
    ADD CONSTRAINT topic_models_model_id_key UNIQUE (model_id);


--
-- Name: topic_models topic_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_models
    ADD CONSTRAINT topic_models_pkey PRIMARY KEY (id);


--
-- Name: triage_assessments triage_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.triage_assessments
    ADD CONSTRAINT triage_assessments_pkey PRIMARY KEY (id);


--
-- Name: ui_preferences ui_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ui_preferences
    ADD CONSTRAINT ui_preferences_pkey PRIMARY KEY (client_id);


--
-- Name: bookmark_ordering unique_bookmark_user_id_ordering; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bookmark_ordering
    ADD CONSTRAINT unique_bookmark_user_id_ordering UNIQUE (user_id, ordering);


--
-- Name: bookmark_ordering unique_bookmark_user_id_type_item_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bookmark_ordering
    ADD CONSTRAINT unique_bookmark_user_id_type_item_id UNIQUE (user_id, type, item_id);


--
-- Name: card_bookmark unique_card_bookmark_user_id_card_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_bookmark
    ADD CONSTRAINT unique_card_bookmark_user_id_card_id UNIQUE (user_id, card_id);


--
-- Name: card_label unique_card_label_card_id_label_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_label
    ADD CONSTRAINT unique_card_label_card_id_label_id UNIQUE (card_id, label_id);


--
-- Name: collection_bookmark unique_collection_bookmark_user_id_collection_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_bookmark
    ADD CONSTRAINT unique_collection_bookmark_user_id_collection_id UNIQUE (user_id, collection_id);


--
-- Name: collection unique_collection_personal_owner_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection
    ADD CONSTRAINT unique_collection_personal_owner_id UNIQUE (personal_owner_id);


--
-- Name: dashboard_bookmark unique_dashboard_bookmark_user_id_dashboard_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_bookmark
    ADD CONSTRAINT unique_dashboard_bookmark_user_id_dashboard_id UNIQUE (user_id, dashboard_id);


--
-- Name: dashboard_favorite unique_dashboard_favorite_user_id_dashboard_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_favorite
    ADD CONSTRAINT unique_dashboard_favorite_user_id_dashboard_id UNIQUE (user_id, dashboard_id);


--
-- Name: dimension unique_dimension_field_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dimension
    ADD CONSTRAINT unique_dimension_field_id UNIQUE (field_id);


--
-- Name: sandboxes unique_gtap_table_id_group_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandboxes
    ADD CONSTRAINT unique_gtap_table_id_group_id UNIQUE (table_id, group_id);


--
-- Name: metric_important_field unique_metric_important_field_metric_id_field_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_important_field
    ADD CONSTRAINT unique_metric_important_field_metric_id_field_id UNIQUE (metric_id, field_id);


--
-- Name: model_index_value unique_model_index_value_model_index_id_model_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_index_value
    ADD CONSTRAINT unique_model_index_value_model_index_id_model_pk UNIQUE (model_index_id, model_pk);


--
-- Name: parameter_card unique_parameterized_object_card_parameter; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parameter_card
    ADD CONSTRAINT unique_parameterized_object_card_parameter UNIQUE (parameterized_object_id, parameterized_object_type, parameter_id);


--
-- Name: permissions_group_membership unique_permissions_group_membership_user_id_group_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group_membership
    ADD CONSTRAINT unique_permissions_group_membership_user_id_group_id UNIQUE (user_id, group_id);


--
-- Name: permissions_group unique_permissions_group_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group
    ADD CONSTRAINT unique_permissions_group_name UNIQUE (name);


--
-- Name: user_key_value unique_user_key_value_user_id_namespace_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_key_value
    ADD CONSTRAINT unique_user_key_value_user_id_namespace_key UNIQUE (user_id, namespace, key);


--
-- Name: user_interests user_interests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_interests
    ADD CONSTRAINT user_interests_pkey PRIMARY KEY (id);


--
-- Name: user_interests user_interests_profile_name_topic_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_interests
    ADD CONSTRAINT user_interests_profile_name_topic_key UNIQUE (profile_name, topic);


--
-- Name: user_key_value user_key_value_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_key_value
    ADD CONSTRAINT user_key_value_pkey PRIMARY KEY (id);


--
-- Name: user_parameter_value user_parameter_value_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_parameter_value
    ADD CONSTRAINT user_parameter_value_pkey PRIMARY KEY (id);


--
-- Name: view_log view_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_log
    ADD CONSTRAINT view_log_pkey PRIMARY KEY (id);


--
-- Name: x_api_requests x_api_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_api_requests
    ADD CONSTRAINT x_api_requests_pkey PRIMARY KEY (id);


--
-- Name: x_auto_sync_schedules x_auto_sync_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_auto_sync_schedules
    ADD CONSTRAINT x_auto_sync_schedules_pkey PRIMARY KEY (user_id);


--
-- Name: x_bookmark_folders x_bookmark_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_bookmark_folders
    ADD CONSTRAINT x_bookmark_folders_pkey PRIMARY KEY (x_folder_id);


--
-- Name: x_bookmarks_sync x_bookmarks_sync_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_bookmarks_sync
    ADD CONSTRAINT x_bookmarks_sync_pkey PRIMARY KEY (tweet_id);


--
-- Name: x_oauth_pending x_oauth_pending_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_oauth_pending
    ADD CONSTRAINT x_oauth_pending_pkey PRIMARY KEY (state);


--
-- Name: x_oauth_tokens x_oauth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_oauth_tokens
    ADD CONSTRAINT x_oauth_tokens_pkey PRIMARY KEY (user_id);


--
-- Name: x_rate_limits x_rate_limits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_rate_limits
    ADD CONSTRAINT x_rate_limits_pkey PRIMARY KEY (user_id);


--
-- Name: x_sync_runs x_sync_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_sync_runs
    ADD CONSTRAINT x_sync_runs_pkey PRIMARY KEY (id);


--
-- Name: idx_agent_positions_role; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_agent_positions_role ON meta.swarm_agent_positions USING btree (agent_role);


--
-- Name: idx_agent_positions_snapshot; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_agent_positions_snapshot ON meta.swarm_agent_positions USING btree (snapshot_id);


--
-- Name: idx_attractors_domain; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_attractors_domain ON meta.semantic_attractors USING btree (domain);


--
-- Name: idx_attractors_name; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_attractors_name ON meta.semantic_attractors USING btree (name);


--
-- Name: idx_fmea_rpn_ts_hour; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_fmea_rpn_ts_hour ON meta.fmea_rpn_timeseries USING btree (hour DESC);


--
-- Name: idx_fmp_sync_runs_profile; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_fmp_sync_runs_profile ON meta.fmp_sync_runs USING btree (profile, domain, started_at DESC);


--
-- Name: idx_fmp_sync_runs_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_fmp_sync_runs_status ON meta.fmp_sync_runs USING btree (status) WHERE ((status)::text = 'running'::text);


--
-- Name: idx_gpu_hourly_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_gpu_hourly_time ON meta.gpu_hourly_stats USING btree (hour DESC);


--
-- Name: idx_gpu_minute_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_gpu_minute_time ON meta.gpu_minute_stats USING btree (minute DESC);


--
-- Name: idx_holders_filing_date; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_holders_filing_date ON meta.institutional_holders_cache USING btree (filing_date DESC);


--
-- Name: idx_holders_symbol; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_holders_symbol ON meta.institutional_holders_cache USING btree (symbol);


--
-- Name: idx_inference_hourly_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_inference_hourly_time ON meta.inference_hourly USING btree (hour DESC);


--
-- Name: idx_meta_agent_perf_date; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_agent_perf_date ON meta.agent_performance USING btree (date DESC);


--
-- Name: idx_meta_audits_scope; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_audits_scope ON meta.metaagent_audits USING btree (scope);


--
-- Name: idx_meta_audits_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_audits_time ON meta.metaagent_audits USING btree (started_at DESC);


--
-- Name: idx_meta_clusters_snapshot; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_clusters_snapshot ON meta.document_clusters USING btree (snapshot_id);


--
-- Name: idx_meta_dataset_namespace; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_dataset_namespace ON meta.dataset_catalog USING btree (namespace);


--
-- Name: idx_meta_deps_source; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_deps_source ON meta.data_dependencies USING btree (source_dataset_id);


--
-- Name: idx_meta_deps_target; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_deps_target ON meta.data_dependencies USING btree (target_dataset_id);


--
-- Name: idx_meta_flow_events_created_at; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_events_created_at ON meta.flow_events USING btree (created_at DESC);


--
-- Name: idx_meta_flow_events_flow_type; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_events_flow_type ON meta.flow_events USING btree (flow_type, created_at DESC);


--
-- Name: idx_meta_flow_events_run_id; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_events_run_id ON meta.flow_events USING btree (run_id);


--
-- Name: idx_meta_flow_events_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_events_status ON meta.flow_events USING btree (status);


--
-- Name: idx_meta_flow_runs_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_runs_status ON meta.flow_runs USING btree (status);


--
-- Name: idx_meta_flow_runs_type; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_runs_type ON meta.flow_runs USING btree (flow_type, started_at DESC);


--
-- Name: idx_meta_flow_runs_updated_at; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_runs_updated_at ON meta.flow_runs USING btree (updated_at DESC);


--
-- Name: idx_meta_gpu_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_gpu_time ON meta.gpu_utilization USING btree ("timestamp" DESC);


--
-- Name: idx_meta_job_namespace; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_job_namespace ON meta.job_catalog USING btree (namespace);


--
-- Name: idx_meta_kb_topology_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_kb_topology_time ON meta.kb_topology USING btree (computed_at DESC);


--
-- Name: idx_meta_metabase_models_name; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_metabase_models_name ON meta.metabase_models USING btree (name);


--
-- Name: idx_meta_metabase_sync_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_metabase_sync_status ON meta.metabase_sync_runs USING btree (status);


--
-- Name: idx_meta_metabase_sync_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_metabase_sync_time ON meta.metabase_sync_runs USING btree (started_at DESC);


--
-- Name: idx_meta_nifi_flows_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_nifi_flows_status ON meta.nifi_flows USING btree (status);


--
-- Name: idx_meta_quality_reward; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_quality_reward ON meta.quality_assessments USING btree (weighted_reward DESC);


--
-- Name: idx_meta_quality_source; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_quality_source ON meta.quality_assessments USING btree (source_type, source_id);


--
-- Name: idx_meta_quality_textbook; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_quality_textbook ON meta.quality_assessments USING btree (is_textbook_quality) WHERE (is_textbook_quality = true);


--
-- Name: idx_meta_recommendations_audit; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_recommendations_audit ON meta.audit_recommendations USING btree (audit_id);


--
-- Name: idx_meta_recommendations_severity; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_recommendations_severity ON meta.audit_recommendations USING btree (severity);


--
-- Name: idx_meta_recommendations_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_recommendations_status ON meta.audit_recommendations USING btree (status);


--
-- Name: idx_meta_research_state_converged; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_research_state_converged ON meta.research_state USING btree (converged, updated_at DESC);


--
-- Name: idx_meta_research_state_updated; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_research_state_updated ON meta.research_state USING btree (updated_at DESC);


--
-- Name: idx_metaagent_queries_expires; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_metaagent_queries_expires ON meta.metaagent_queries USING btree (expires_at);


--
-- Name: idx_ngrc_models_active_domain; Type: INDEX; Schema: meta; Owner: -
--

CREATE UNIQUE INDEX idx_ngrc_models_active_domain ON meta.ngrc_models USING btree (domain) WHERE (is_active = true);


--
-- Name: idx_ngrc_models_domain; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_ngrc_models_domain ON meta.ngrc_models USING btree (domain);


--
-- Name: idx_prospect_candidates_active; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_candidates_active ON meta.prospect_candidates USING btree (active) WHERE (active = true);


--
-- Name: idx_prospect_candidates_pending; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_candidates_pending ON meta.prospect_candidates USING btree (pending_filings) WHERE (pending_filings > 0);


--
-- Name: idx_prospect_candidates_priority; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_candidates_priority ON meta.prospect_candidates USING btree (priority);


--
-- Name: idx_prospect_candidates_symbol; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_candidates_symbol ON meta.prospect_candidates USING btree (symbol);


--
-- Name: idx_prospect_strategies_needs_update; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_strategies_needs_update ON meta.prospect_strategies USING btree (needs_update) WHERE (needs_update = true);


--
-- Name: idx_prospect_strategies_profile; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_strategies_profile ON meta.prospect_strategies USING btree (profile, domain);


--
-- Name: idx_prospect_strategies_symbol; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_prospect_strategies_symbol ON meta.prospect_strategies USING btree (symbol);


--
-- Name: idx_research_progress_created; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_research_progress_created ON meta.research_progress USING btree (created_at DESC);


--
-- Name: idx_research_progress_session; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_research_progress_session ON meta.research_progress USING btree (session_id, event_id);


--
-- Name: idx_research_progress_session_created; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_research_progress_session_created ON meta.research_progress USING btree (session_id, created_at DESC);


--
-- Name: idx_sankey_window; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_sankey_window ON meta.lineage_sankey_agg USING btree (time_window, window_start DESC);


--
-- Name: idx_sec_filings_pending; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_sec_filings_pending ON meta.sec_filings_cache USING btree (analyzed_at) WHERE (analyzed_at IS NULL);


--
-- Name: idx_sec_filings_symbol; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_sec_filings_symbol ON meta.sec_filings_cache USING btree (symbol, filing_date DESC);


--
-- Name: idx_swarm_snapshots_captured; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_swarm_snapshots_captured ON meta.swarm_snapshots USING btree (captured_at DESC);


--
-- Name: idx_swarm_snapshots_domain; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_swarm_snapshots_domain ON meta.swarm_snapshots USING btree (domain);


--
-- Name: idx_swarm_snapshots_domain_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_swarm_snapshots_domain_time ON meta.swarm_snapshots USING btree (domain, captured_at DESC);


--
-- Name: idx_topology_drift_domain; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_topology_drift_domain ON meta.topology_drift USING btree (domain);


--
-- Name: idx_topology_drift_time; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_topology_drift_time ON meta.topology_drift USING btree (computed_at DESC);


--
-- Name: idx_action_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_creator_id ON public.action USING btree (creator_id);


--
-- Name: idx_action_made_public_by_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_made_public_by_id ON public.action USING btree (made_public_by_id);


--
-- Name: idx_action_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_model_id ON public.action USING btree (model_id);


--
-- Name: idx_action_public_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_action_public_uuid ON public.action USING btree (public_uuid);


--
-- Name: idx_activity_events_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_events_created ON public.activity_events USING btree (created_at DESC);


--
-- Name: idx_activity_events_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_events_domain ON public.activity_events USING btree (domain) WHERE (domain IS NOT NULL);


--
-- Name: idx_activity_events_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_events_profile ON public.activity_events USING btree (profile_name);


--
-- Name: idx_activity_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_events_type ON public.activity_events USING btree (event_type);


--
-- Name: idx_agenda_incidents_agenda; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_incidents_agenda ON public.agenda_incidents USING btree (agenda_id);


--
-- Name: idx_agenda_incidents_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_incidents_recent ON public.agenda_incidents USING btree (created_at DESC);


--
-- Name: idx_agenda_incidents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_incidents_status ON public.agenda_incidents USING btree (status) WHERE (status <> ALL (ARRAY['fulfilled'::public.agenda_status, 'failed'::public.agenda_status, 'degraded'::public.agenda_status]));


--
-- Name: idx_agenda_incidents_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_incidents_type ON public.agenda_incidents USING btree (agenda_type, created_at DESC);


--
-- Name: idx_agenda_ops_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_ops_recent ON public.agenda_operations USING btree (created_at DESC);


--
-- Name: idx_agenda_ops_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_ops_status ON public.agenda_operations USING btree (status) WHERE (status <> ALL (ARRAY['fulfilled'::public.agenda_status, 'failed'::public.agenda_status, 'degraded'::public.agenda_status]));


--
-- Name: idx_agenda_ops_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_ops_type ON public.agenda_operations USING btree (workload_type, created_at DESC);


--
-- Name: idx_agenda_ops_workload; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_ops_workload ON public.agenda_operations USING btree (workload_id);


--
-- Name: idx_agenda_phase_events_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_phase_events_endpoint ON public.agenda_phase_events USING btree (endpoint, created_at DESC) WHERE (endpoint IS NOT NULL);


--
-- Name: idx_agenda_phase_events_incident; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_phase_events_incident ON public.agenda_phase_events USING btree (agenda_incident_id, phase_index);


--
-- Name: idx_agenda_phase_events_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_phase_events_recent ON public.agenda_phase_events USING btree (created_at DESC);


--
-- Name: idx_agenda_phase_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agenda_phase_events_type ON public.agenda_phase_events USING btree (event_type, created_at DESC);


--
-- Name: idx_agent_evaluations_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_evaluations_category ON public.agent_evaluations USING btree (task_category);


--
-- Name: idx_agent_evaluations_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_evaluations_created ON public.agent_evaluations USING btree (created_at DESC);


--
-- Name: idx_agent_evaluations_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_evaluations_score ON public.agent_evaluations USING btree (overall_score DESC);


--
-- Name: idx_agent_evaluations_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_evaluations_type ON public.agent_evaluations USING btree (eval_type);


--
-- Name: idx_agent_evaluations_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_evaluations_version ON public.agent_evaluations USING btree (version_id);


--
-- Name: idx_agent_versions_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_versions_active ON public.agent_versions USING btree (agent_id, is_active) WHERE (is_active = true);


--
-- Name: idx_agent_versions_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_versions_agent ON public.agent_versions USING btree (agent_id);


--
-- Name: idx_agent_versions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_versions_created ON public.agent_versions USING btree (created_at DESC);


--
-- Name: idx_agent_versions_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_versions_parent ON public.agent_versions USING btree (parent_version) WHERE (parent_version IS NOT NULL);


--
-- Name: idx_agent_versions_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_versions_score ON public.agent_versions USING btree (avg_overall_score DESC);


--
-- Name: idx_agent_versions_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_agent_versions_single_active ON public.agent_versions USING btree (agent_id) WHERE (is_active = true);


--
-- Name: idx_aiops_events_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_category ON public.aiops_events USING btree (category, created_at DESC);


--
-- Name: idx_aiops_events_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_endpoint ON public.aiops_events USING btree (endpoint, created_at DESC);


--
-- Name: idx_aiops_events_failure_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_failure_mode ON public.aiops_events USING btree (failure_mode_id);


--
-- Name: idx_aiops_events_rpn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_rpn ON public.aiops_events USING btree (rpn_score DESC) WHERE (rpn_score IS NOT NULL);


--
-- Name: idx_aiops_events_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_severity ON public.aiops_events USING btree (severity, status);


--
-- Name: idx_aiops_events_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aiops_events_status ON public.aiops_events USING btree (status, created_at DESC);


--
-- Name: idx_api_key_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_key_created_by ON public.api_key USING btree (creator_id);


--
-- Name: idx_api_key_updated_by_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_key_updated_by_id ON public.api_key USING btree (updated_by_id);


--
-- Name: idx_api_key_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_key_user_id ON public.api_key USING btree (user_id);


--
-- Name: idx_application_permissions_revision_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_application_permissions_revision_user_id ON public.application_permissions_revision USING btree (user_id);


--
-- Name: idx_approvals_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_event ON public.remediation_approvals USING btree (event_type, event_id);


--
-- Name: idx_approvals_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_pending ON public.remediation_approvals USING btree (status, expires_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_archive_rotations_quarter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archive_rotations_quarter ON public.archive_rotations USING btree (quarter);


--
-- Name: idx_archive_rotations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archive_rotations_status ON public.archive_rotations USING btree (status);


--
-- Name: idx_audit_log_entity_qualified_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_entity_qualified_id ON public.audit_log USING btree ((
CASE
    WHEN ((model)::text = 'Dataset'::text) THEN ('card_'::text || model_id)
    WHEN (model_id IS NULL) THEN NULL::text
    ELSE ((lower((model)::text) || '_'::text) || model_id)
END));


--
-- Name: idx_bookmark_ordering_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bookmark_ordering_user_id ON public.bookmark_ordering USING btree (user_id);


--
-- Name: idx_calibration_summaries_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibration_summaries_agent ON public.calibration_summaries USING btree (agent_id);


--
-- Name: idx_calibrations_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibrations_agent ON public.evolution_calibrations USING btree (agent_id);


--
-- Name: idx_calibrations_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibrations_created ON public.evolution_calibrations USING btree (created_at DESC);


--
-- Name: idx_calibrations_drift; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibrations_drift ON public.evolution_calibrations USING btree (drift_detected) WHERE drift_detected;


--
-- Name: idx_calibrations_objective; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibrations_objective ON public.evolution_calibrations USING btree (objective_name);


--
-- Name: idx_calibrations_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calibrations_provider ON public.evolution_calibrations USING btree (provider);


--
-- Name: idx_card_bookmark_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_bookmark_card_id ON public.card_bookmark USING btree (card_id);


--
-- Name: idx_card_bookmark_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_bookmark_user_id ON public.card_bookmark USING btree (user_id);


--
-- Name: idx_card_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_collection_id ON public.report_card USING btree (collection_id);


--
-- Name: idx_card_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_creator_id ON public.report_card USING btree (creator_id);


--
-- Name: idx_card_label_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_label_card_id ON public.card_label USING btree (card_id);


--
-- Name: idx_card_label_label_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_label_label_id ON public.card_label USING btree (label_id);


--
-- Name: idx_card_public_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_card_public_uuid ON public.report_card USING btree (public_uuid);


--
-- Name: idx_cardfavorite_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cardfavorite_card_id ON public.report_cardfavorite USING btree (card_id);


--
-- Name: idx_cardfavorite_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cardfavorite_owner_id ON public.report_cardfavorite USING btree (owner_id);


--
-- Name: idx_collection_bookmark_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_bookmark_collection_id ON public.collection_bookmark USING btree (collection_id);


--
-- Name: idx_collection_bookmark_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_bookmark_user_id ON public.collection_bookmark USING btree (user_id);


--
-- Name: idx_collection_location; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_location ON public.collection USING btree (location);


--
-- Name: idx_collection_permission_graph_revision_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_permission_graph_revision_user_id ON public.collection_permission_graph_revision USING btree (user_id);


--
-- Name: idx_collection_personal_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_personal_owner_id ON public.collection USING btree (personal_owner_id);


--
-- Name: idx_collection_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_collection_type ON public.collection USING btree (type);


--
-- Name: idx_command_history_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_command_history_client ON public.command_history USING btree (client_id, executed_at DESC);


--
-- Name: idx_command_history_kb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_command_history_kb ON public.command_history USING btree (kb_root, executed_at DESC);


--
-- Name: idx_conn_impersonations_db_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conn_impersonations_db_id ON public.connection_impersonations USING btree (db_id);


--
-- Name: idx_conn_impersonations_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conn_impersonations_group_id ON public.connection_impersonations USING btree (group_id);


--
-- Name: idx_content_excluded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_excluded ON public.content_items USING btree (source_id, fetched_at DESC) WHERE (summary_excluded = true);


--
-- Name: idx_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_hash ON public.content_items USING btree (content_hash) WHERE (content_hash IS NOT NULL);


--
-- Name: idx_content_heuristic_null; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_heuristic_null ON public.content_items USING btree (fetched_at DESC) WHERE (heuristic_score IS NULL);


--
-- Name: idx_content_items_fetched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_fetched ON public.content_items USING btree (fetched_at DESC);


--
-- Name: idx_content_items_iceberg_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_iceberg_id ON public.content_items USING btree (iceberg_id) WHERE (iceberg_id IS NOT NULL);


--
-- Name: idx_content_items_kb_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_kb_path ON public.content_items USING btree (kb_path) WHERE (kb_path IS NOT NULL);


--
-- Name: idx_content_items_published; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_published ON public.content_items USING btree (published_at DESC);


--
-- Name: idx_content_items_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_source ON public.content_items USING btree (source_id);


--
-- Name: idx_content_kb_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_kb_pending ON public.content_items USING btree (llm_quality_score DESC) WHERE ((llm_quality_score >= 50) AND (processed_at IS NULL) AND (NOT COALESCE(summary_excluded, false)));


--
-- Name: idx_content_llm_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_llm_pending ON public.content_items USING btree (heuristic_score DESC) WHERE ((llm_quality_score IS NULL) AND (NOT COALESCE(summary_excluded, false)));


--
-- Name: idx_content_unsummarized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_unsummarized ON public.content_items USING btree (fetched_at DESC) WHERE ((summarized_at IS NULL) AND (processed_at IS NOT NULL) AND (NOT COALESCE(summary_excluded, false)));


--
-- Name: idx_core_session_key_hashed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_core_session_key_hashed ON public.core_session USING btree (key_hashed);


--
-- Name: idx_core_session_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_core_session_user_id ON public.core_session USING btree (user_id);


--
-- Name: idx_corpus_versions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corpus_versions_created ON public.corpus_versions USING btree (created_at DESC);


--
-- Name: idx_cycles_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cycles_recent ON public.cognition_cycles USING btree (profile_name, started_at DESC);


--
-- Name: idx_daily_summaries_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_summaries_date ON public.daily_summaries USING btree (summary_date DESC);


--
-- Name: idx_dashboard_bookmark_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_bookmark_dashboard_id ON public.dashboard_bookmark USING btree (dashboard_id);


--
-- Name: idx_dashboard_bookmark_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_bookmark_user_id ON public.dashboard_bookmark USING btree (user_id);


--
-- Name: idx_dashboard_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_collection_id ON public.report_dashboard USING btree (collection_id);


--
-- Name: idx_dashboard_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_creator_id ON public.report_dashboard USING btree (creator_id);


--
-- Name: idx_dashboard_favorite_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_favorite_dashboard_id ON public.dashboard_favorite USING btree (dashboard_id);


--
-- Name: idx_dashboard_favorite_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_favorite_user_id ON public.dashboard_favorite USING btree (user_id);


--
-- Name: idx_dashboard_public_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_public_uuid ON public.report_dashboard USING btree (public_uuid);


--
-- Name: idx_dashboard_tab_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_tab_dashboard_id ON public.dashboard_tab USING btree (dashboard_id);


--
-- Name: idx_dashboardcard_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboardcard_card_id ON public.report_dashboardcard USING btree (card_id);


--
-- Name: idx_dashboardcard_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboardcard_dashboard_id ON public.report_dashboardcard USING btree (dashboard_id);


--
-- Name: idx_dashboardcard_series_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboardcard_series_card_id ON public.dashboardcard_series USING btree (card_id);


--
-- Name: idx_dashboardcard_series_dashboardcard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboardcard_series_dashboardcard_id ON public.dashboardcard_series USING btree (dashboardcard_id);


--
-- Name: idx_data_permissions_db_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_permissions_db_id ON public.data_permissions USING btree (db_id);


--
-- Name: idx_data_permissions_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_permissions_group_id ON public.data_permissions USING btree (group_id);


--
-- Name: idx_data_permissions_group_id_db_id_perm_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_permissions_group_id_db_id_perm_value ON public.data_permissions USING btree (group_id, db_id, perm_value);


--
-- Name: idx_data_permissions_group_id_db_id_table_id_perm_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_permissions_group_id_db_id_table_id_perm_value ON public.data_permissions USING btree (group_id, db_id, table_id, perm_value);


--
-- Name: idx_data_permissions_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_permissions_table_id ON public.data_permissions USING btree (table_id);


--
-- Name: idx_dependency_dependent_on_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dependency_dependent_on_id ON public.dependency USING btree (dependent_on_id);


--
-- Name: idx_dependency_dependent_on_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dependency_dependent_on_model ON public.dependency USING btree (dependent_on_model);


--
-- Name: idx_dependency_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dependency_model ON public.dependency USING btree (model);


--
-- Name: idx_dependency_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dependency_model_id ON public.dependency USING btree (model_id);


--
-- Name: idx_dimension_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dimension_field_id ON public.dimension USING btree (field_id);


--
-- Name: idx_dimension_human_readable_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dimension_human_readable_field_id ON public.dimension USING btree (human_readable_field_id);


--
-- Name: idx_doc_archives_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_archives_source ON public.doc_archives USING btree (source_id);


--
-- Name: idx_doc_archives_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_archives_status ON public.doc_archives USING btree (status);


--
-- Name: idx_document_topics_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_topics_doc ON public.document_topics USING btree (document_id);


--
-- Name: idx_document_topics_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_topics_model ON public.document_topics USING btree (model_id);


--
-- Name: idx_engine_obs_anomalies; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_obs_anomalies ON public.engine_observations USING btree (observed_at DESC) WHERE (cardinality(anomalies) > 0);


--
-- Name: idx_engine_obs_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_obs_recent ON public.engine_observations USING btree (observed_at DESC);


--
-- Name: idx_engine_obs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_obs_source ON public.engine_observations USING btree (source, observed_at DESC);


--
-- Name: idx_engine_obs_thought; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_engine_obs_thought ON public.engine_observations USING btree (related_thought_id) WHERE (related_thought_id IS NOT NULL);


--
-- Name: idx_eval_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_eval_type ON public.agent_evaluations USING btree (eval_type);


--
-- Name: idx_evo_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evo_agent ON public.evolution_cycles USING btree (agent_id);


--
-- Name: idx_evo_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evo_started ON public.evolution_cycles USING btree (started_at);


--
-- Name: idx_evo_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evo_success ON public.evolution_cycles USING btree (success);


--
-- Name: idx_evo_trigger; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evo_trigger ON public.evolution_cycles USING btree (trigger_type);


--
-- Name: idx_evolution_cycles_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evolution_cycles_agent ON public.evolution_cycles USING btree (agent_id);


--
-- Name: idx_evolution_cycles_improvement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evolution_cycles_improvement ON public.evolution_cycles USING btree (improvement_percent DESC);


--
-- Name: idx_evolution_cycles_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evolution_cycles_started ON public.evolution_cycles USING btree (started_at DESC);


--
-- Name: idx_evolution_cycles_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evolution_cycles_success ON public.evolution_cycles USING btree (success);


--
-- Name: idx_feed_sources_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_sources_active ON public.feed_sources USING btree (active);


--
-- Name: idx_feed_sources_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_sources_type ON public.feed_sources USING btree (source_type);


--
-- Name: idx_fetch_jobs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fetch_jobs_source ON public.fetch_jobs USING btree (source_id, started_at DESC);


--
-- Name: idx_field_entity_qualified_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_entity_qualified_id ON public.metabase_field USING btree ((('field_'::text || id)));


--
-- Name: idx_field_name_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_name_lower ON public.metabase_field USING btree (lower((name)::text));


--
-- Name: idx_field_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_parent_id ON public.metabase_field USING btree (parent_id);


--
-- Name: idx_field_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_table_id ON public.metabase_field USING btree (table_id);


--
-- Name: idx_field_usage_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_usage_field_id ON public.field_usage USING btree (field_id);


--
-- Name: idx_field_usage_query_execution_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_field_usage_query_execution_id ON public.field_usage USING btree (query_execution_id);


--
-- Name: idx_fieldvalues_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fieldvalues_field_id ON public.metabase_fieldvalues USING btree (field_id);


--
-- Name: idx_fmea_adjustments_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fmea_adjustments_lookup ON public.fmea_adjustments USING btree (failure_mode_id, endpoint, hour_of_day);


--
-- Name: idx_fmea_occurrences_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fmea_occurrences_mode ON public.fmea_occurrences USING btree (failure_mode_id, occurred_at DESC);


--
-- Name: idx_fmea_occurrences_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fmea_occurrences_recent ON public.fmea_occurrences USING btree (occurred_at DESC);


--
-- Name: idx_fmea_outcomes_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fmea_outcomes_mode ON public.fmea_outcomes USING btree (failure_mode_id, created_at DESC);


--
-- Name: idx_fmea_outcomes_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fmea_outcomes_success ON public.fmea_outcomes USING btree (success, created_at DESC);


--
-- Name: idx_github_issues_fingerprint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_github_issues_fingerprint ON public.github_issues USING btree (fingerprint);


--
-- Name: idx_github_issues_repo; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_github_issues_repo ON public.github_issues USING btree (repo);


--
-- Name: idx_github_issues_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_github_issues_sequence ON public.github_issues USING btree (sequence_id) WHERE (sequence_id IS NOT NULL);


--
-- Name: idx_github_issues_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_github_issues_status ON public.github_issues USING btree (status, created_at DESC);


--
-- Name: idx_grid_points_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grid_points_position ON public.grid_points USING btree (snapshot_id, x, y);


--
-- Name: idx_grid_snapshots_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grid_snapshots_current ON public.grid_snapshots USING btree (kb_root, is_current) WHERE (is_current = true);


--
-- Name: idx_grid_snapshots_generation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grid_snapshots_generation ON public.grid_snapshots USING btree (kb_root, generation DESC);


--
-- Name: idx_gtap_table_id_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gtap_table_id_group_id ON public.sandboxes USING btree (table_id, group_id);


--
-- Name: idx_healing_events_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_active ON public.healing_events USING btree (endpoint, sequence_id, created_at) WHERE ((event_type)::text = 'sequence_started'::text);


--
-- Name: idx_healing_events_aiops; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_aiops ON public.healing_events USING btree (aiops_event_id) WHERE (aiops_event_id IS NOT NULL);


--
-- Name: idx_healing_events_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_endpoint ON public.healing_events USING btree (endpoint, created_at DESC);


--
-- Name: idx_healing_events_fmea; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_fmea ON public.healing_events USING btree (failure_mode_id) WHERE (failure_mode_id IS NOT NULL);


--
-- Name: idx_healing_events_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_recent ON public.healing_events USING btree (created_at DESC);


--
-- Name: idx_healing_events_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_sequence ON public.healing_events USING btree (sequence_id, sequence_num);


--
-- Name: idx_healing_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_healing_events_type ON public.healing_events USING btree (event_type, created_at DESC);


--
-- Name: idx_held_out_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_category ON public.held_out_queries USING btree (category);


--
-- Name: idx_held_out_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_created ON public.held_out_queries USING btree (created_at DESC);


--
-- Name: idx_held_out_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_domain ON public.held_out_queries USING btree (domain);


--
-- Name: idx_held_out_excluded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_excluded ON public.held_out_queries USING btree (excluded_from_training);


--
-- Name: idx_held_out_last_used; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_last_used ON public.held_out_queries USING btree (last_used_at);


--
-- Name: idx_held_out_unused; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_held_out_unused ON public.held_out_queries USING btree (last_used_at NULLS FIRST);


--
-- Name: idx_interests_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_interests_score ON public.user_interests USING btree (profile_name, interest_score DESC);


--
-- Name: idx_label_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_label_slug ON public.label USING btree (slug);


--
-- Name: idx_lineage_inputs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_inputs ON public.lineage_events USING gin (inputs);


--
-- Name: idx_lineage_job; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_job ON public.lineage_events USING btree (job_namespace, job_name);


--
-- Name: idx_lineage_outputs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_outputs ON public.lineage_events USING gin (outputs);


--
-- Name: idx_lineage_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_parent ON public.lineage_events USING btree (parent_run_id) WHERE (parent_run_id IS NOT NULL);


--
-- Name: idx_lineage_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_run ON public.lineage_events USING btree (run_id);


--
-- Name: idx_lineage_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_time ON public.lineage_events USING btree (event_time DESC);


--
-- Name: idx_lineage_unprocessed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_unprocessed ON public.lineage_events USING btree (created_at) WHERE (NOT processed);


--
-- Name: idx_lower_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lower_email ON public.core_user USING btree (lower((email)::text));


--
-- Name: idx_metabase_database_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabase_database_creator_id ON public.metabase_database USING btree (creator_id);


--
-- Name: idx_metabase_table_db_deactivated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabase_table_db_deactivated ON public.metabase_table USING btree (db_id, deactivated_at) WHERE ((active = false) AND (archived_at IS NULL) AND (deactivated_at IS NOT NULL));


--
-- Name: idx_metabase_table_db_id_schema; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabase_table_db_id_schema ON public.metabase_table USING btree (db_id, schema);


--
-- Name: idx_metabase_table_show_in_getting_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabase_table_show_in_getting_started ON public.metabase_table USING btree (show_in_getting_started);


--
-- Name: idx_metabot_conversation_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabot_conversation_user_id ON public.metabot_conversation USING btree (user_id);


--
-- Name: idx_metabot_entity_metabot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabot_entity_metabot_id ON public.metabot_entity USING btree (metabot_id);


--
-- Name: idx_metabot_message_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabot_message_conversation_id ON public.metabot_message USING btree (conversation_id);


--
-- Name: idx_metabot_prompt_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabot_prompt_card_id ON public.metabot_prompt USING btree (card_id);


--
-- Name: idx_metabot_prompt_metabot_entity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metabot_prompt_metabot_entity_id ON public.metabot_prompt USING btree (metabot_entity_id);


--
-- Name: idx_metric_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metric_creator_id ON public.metric USING btree (creator_id);


--
-- Name: idx_metric_important_field_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metric_important_field_field_id ON public.metric_important_field USING btree (field_id);


--
-- Name: idx_metric_important_field_metric_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metric_important_field_metric_id ON public.metric_important_field USING btree (metric_id);


--
-- Name: idx_metric_show_in_getting_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metric_show_in_getting_started ON public.metric USING btree (show_in_getting_started);


--
-- Name: idx_metric_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metric_table_id ON public.metric USING btree (table_id);


--
-- Name: idx_mlops_events_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mlops_events_agent ON public.mlops_events USING btree (agent_id, created_at DESC);


--
-- Name: idx_mlops_events_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mlops_events_category ON public.mlops_events USING btree (category, created_at DESC);


--
-- Name: idx_mlops_events_failure_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mlops_events_failure_mode ON public.mlops_events USING btree (failure_mode_id);


--
-- Name: idx_mlops_events_rpn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mlops_events_rpn ON public.mlops_events USING btree (rpn_score DESC) WHERE (rpn_score IS NOT NULL);


--
-- Name: idx_mlops_events_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mlops_events_status ON public.mlops_events USING btree (status, created_at DESC);


--
-- Name: idx_model_index_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_index_creator_id ON public.model_index USING btree (creator_id);


--
-- Name: idx_model_index_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_index_model_id ON public.model_index USING btree (model_id);


--
-- Name: idx_moderation_review_item_type_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_moderation_review_item_type_item_id ON public.moderation_review USING btree (moderated_item_type, moderated_item_id);


--
-- Name: idx_native_query_snippet_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_native_query_snippet_creator_id ON public.native_query_snippet USING btree (creator_id);


--
-- Name: idx_notification_card_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_card_card_id ON public.notification_card USING btree (card_id);


--
-- Name: idx_notification_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_creator_id ON public.notification USING btree (creator_id);


--
-- Name: idx_notification_handler_channel_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_handler_channel_id ON public.notification_handler USING btree (channel_id);


--
-- Name: idx_notification_handler_notification_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_handler_notification_id ON public.notification_handler USING btree (notification_id);


--
-- Name: idx_notification_handler_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_handler_template_id ON public.notification_handler USING btree (template_id);


--
-- Name: idx_notification_recipient_notification_handler_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_recipient_notification_handler_id ON public.notification_recipient USING btree (notification_handler_id);


--
-- Name: idx_notification_recipient_permissions_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_recipient_permissions_group_id ON public.notification_recipient USING btree (permissions_group_id);


--
-- Name: idx_notification_recipient_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_recipient_user_id ON public.notification_recipient USING btree (user_id);


--
-- Name: idx_notification_subscription_notification_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_subscription_notification_id ON public.notification_subscription USING btree (notification_id);


--
-- Name: idx_optimization_runs_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_optimization_runs_agent ON public.optimization_runs USING btree (agent_id);


--
-- Name: idx_optimization_runs_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_optimization_runs_started ON public.optimization_runs USING btree (started_at DESC);


--
-- Name: idx_optimization_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_optimization_runs_status ON public.optimization_runs USING btree (status);


--
-- Name: idx_paper_scores_arxiv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_scores_arxiv ON public.paper_scores USING btree (arxiv_id);


--
-- Name: idx_paper_scores_overall; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_scores_overall ON public.paper_scores USING btree (overall_score DESC);


--
-- Name: idx_paper_scores_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_scores_run ON public.paper_scores USING btree (metaflow_run_id);


--
-- Name: idx_parameter_card_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parameter_card_card_id ON public.parameter_card USING btree (card_id);


--
-- Name: idx_parameter_card_parameterized_object_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parameter_card_parameterized_object_id ON public.parameter_card USING btree (parameterized_object_id);


--
-- Name: idx_permissions_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_collection_id ON public.permissions USING btree (collection_id);


--
-- Name: idx_permissions_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_id ON public.permissions USING btree (group_id);


--
-- Name: idx_permissions_group_id_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_id_object ON public.permissions USING btree (group_id, object);


--
-- Name: idx_permissions_group_membership_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_membership_group_id ON public.permissions_group_membership USING btree (group_id);


--
-- Name: idx_permissions_group_membership_group_id_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_membership_group_id_user_id ON public.permissions_group_membership USING btree (group_id, user_id);


--
-- Name: idx_permissions_group_membership_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_membership_user_id ON public.permissions_group_membership USING btree (user_id);


--
-- Name: idx_permissions_group_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_group_name ON public.permissions_group USING btree (name);


--
-- Name: idx_permissions_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_object ON public.permissions USING btree (object);


--
-- Name: idx_permissions_perm_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_perm_type ON public.permissions USING btree (perm_type);


--
-- Name: idx_permissions_perm_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_perm_value ON public.permissions USING btree (perm_value);


--
-- Name: idx_permissions_revision_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_permissions_revision_user_id ON public.permissions_revision USING btree (user_id);


--
-- Name: idx_persisted_info_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_persisted_info_creator_id ON public.persisted_info USING btree (creator_id);


--
-- Name: idx_persisted_info_database_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_persisted_info_database_id ON public.persisted_info USING btree (database_id);


--
-- Name: idx_profile_content_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_content_score ON public.profile_content USING btree (profile_id, relevance_score DESC);


--
-- Name: idx_profile_domains_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_domains_active ON public.profile_domains USING btree (profile_id) WHERE is_active;


--
-- Name: idx_profile_domains_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_domains_profile ON public.profile_domains USING btree (profile_id);


--
-- Name: idx_profiles_default; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_profiles_default ON public.profiles USING btree ((1)) WHERE (is_default = true);


--
-- Name: idx_profiles_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_name ON public.profiles USING btree (name);


--
-- Name: idx_pulse_card_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_card_card_id ON public.pulse_card USING btree (card_id);


--
-- Name: idx_pulse_card_dashboard_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_card_dashboard_card_id ON public.pulse_card USING btree (dashboard_card_id);


--
-- Name: idx_pulse_card_pulse_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_card_pulse_id ON public.pulse_card USING btree (pulse_id);


--
-- Name: idx_pulse_channel_pulse_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_channel_pulse_id ON public.pulse_channel USING btree (pulse_id);


--
-- Name: idx_pulse_channel_recipient_pulse_channel_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_channel_recipient_pulse_channel_id ON public.pulse_channel_recipient USING btree (pulse_channel_id);


--
-- Name: idx_pulse_channel_recipient_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_channel_recipient_user_id ON public.pulse_channel_recipient USING btree (user_id);


--
-- Name: idx_pulse_channel_schedule_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_channel_schedule_type ON public.pulse_channel USING btree (schedule_type);


--
-- Name: idx_pulse_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_collection_id ON public.pulse USING btree (collection_id);


--
-- Name: idx_pulse_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_creator_id ON public.pulse USING btree (creator_id);


--
-- Name: idx_pulse_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pulse_dashboard_id ON public.pulse USING btree (dashboard_id);


--
-- Name: idx_qrtz_ft_inst_job_req_rcvry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_inst_job_req_rcvry ON public.qrtz_fired_triggers USING btree (sched_name, instance_name, requests_recovery);


--
-- Name: idx_qrtz_ft_j_g; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_j_g ON public.qrtz_fired_triggers USING btree (sched_name, job_name, job_group);


--
-- Name: idx_qrtz_ft_jg; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_jg ON public.qrtz_fired_triggers USING btree (sched_name, job_group);


--
-- Name: idx_qrtz_ft_t_g; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_t_g ON public.qrtz_fired_triggers USING btree (sched_name, trigger_name, trigger_group);


--
-- Name: idx_qrtz_ft_tg; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_tg ON public.qrtz_fired_triggers USING btree (sched_name, trigger_group);


--
-- Name: idx_qrtz_ft_trig_inst_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_ft_trig_inst_name ON public.qrtz_fired_triggers USING btree (sched_name, instance_name);


--
-- Name: idx_qrtz_j_grp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_j_grp ON public.qrtz_job_details USING btree (sched_name, job_group);


--
-- Name: idx_qrtz_j_req_recovery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_j_req_recovery ON public.qrtz_job_details USING btree (sched_name, requests_recovery);


--
-- Name: idx_qrtz_t_c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_c ON public.qrtz_triggers USING btree (sched_name, calendar_name);


--
-- Name: idx_qrtz_t_g; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_g ON public.qrtz_triggers USING btree (sched_name, trigger_group);


--
-- Name: idx_qrtz_t_j; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_j ON public.qrtz_triggers USING btree (sched_name, job_name, job_group);


--
-- Name: idx_qrtz_t_jg; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_jg ON public.qrtz_triggers USING btree (sched_name, job_group);


--
-- Name: idx_qrtz_t_n_g_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_n_g_state ON public.qrtz_triggers USING btree (sched_name, trigger_group, trigger_state);


--
-- Name: idx_qrtz_t_n_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_n_state ON public.qrtz_triggers USING btree (sched_name, trigger_name, trigger_group, trigger_state);


--
-- Name: idx_qrtz_t_next_fire_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_next_fire_time ON public.qrtz_triggers USING btree (sched_name, next_fire_time);


--
-- Name: idx_qrtz_t_nft_misfire; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_nft_misfire ON public.qrtz_triggers USING btree (sched_name, misfire_instr, next_fire_time);


--
-- Name: idx_qrtz_t_nft_st; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_nft_st ON public.qrtz_triggers USING btree (sched_name, trigger_state, next_fire_time);


--
-- Name: idx_qrtz_t_nft_st_misfire; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_nft_st_misfire ON public.qrtz_triggers USING btree (sched_name, misfire_instr, next_fire_time, trigger_state);


--
-- Name: idx_qrtz_t_nft_st_misfire_grp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_nft_st_misfire_grp ON public.qrtz_triggers USING btree (sched_name, misfire_instr, next_fire_time, trigger_group, trigger_state);


--
-- Name: idx_qrtz_t_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qrtz_t_state ON public.qrtz_triggers USING btree (sched_name, trigger_state);


--
-- Name: idx_query_action_database_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_action_database_id ON public.query_action USING btree (database_id);


--
-- Name: idx_query_cache_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_cache_updated_at ON public.query_cache USING btree (updated_at);


--
-- Name: idx_query_execution_action_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_action_id ON public.query_execution USING btree (action_id);


--
-- Name: idx_query_execution_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_card_id ON public.query_execution USING btree (card_id);


--
-- Name: idx_query_execution_card_id_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_card_id_started_at ON public.query_execution USING btree (card_id, started_at);


--
-- Name: idx_query_execution_card_qualified_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_card_qualified_id ON public.query_execution USING btree ((('card_'::text || card_id)));


--
-- Name: idx_query_execution_context; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_context ON public.query_execution USING btree (context);


--
-- Name: idx_query_execution_executor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_executor_id ON public.query_execution USING btree (executor_id);


--
-- Name: idx_query_execution_query_hash_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_query_hash_started_at ON public.query_execution USING btree (hash, started_at);


--
-- Name: idx_query_execution_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_execution_started_at ON public.query_execution USING btree (started_at);


--
-- Name: idx_query_field_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_field_card_id ON public.query_field USING btree (card_id);


--
-- Name: idx_query_field_field_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_field_field_id ON public.query_field USING btree (field_id);


--
-- Name: idx_query_table_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_table_card_id ON public.query_table USING btree (card_id);


--
-- Name: idx_query_table_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_query_table_table_id ON public.query_table USING btree (table_id);


--
-- Name: idx_recent_views_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recent_views_user_id ON public.recent_views USING btree (user_id);


--
-- Name: idx_report_card_card_schema; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_card_schema ON public.report_card USING btree (card_schema);


--
-- Name: idx_report_card_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_dashboard_id ON public.report_card USING btree (dashboard_id);


--
-- Name: idx_report_card_database_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_database_id ON public.report_card USING btree (database_id);


--
-- Name: idx_report_card_made_public_by_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_made_public_by_id ON public.report_card USING btree (made_public_by_id);


--
-- Name: idx_report_card_source_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_source_card_id ON public.report_card USING btree (source_card_id);


--
-- Name: idx_report_card_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_card_table_id ON public.report_card USING btree (table_id);


--
-- Name: idx_report_dashboard_made_public_by_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_dashboard_made_public_by_id ON public.report_dashboard USING btree (made_public_by_id);


--
-- Name: idx_report_dashboard_show_in_getting_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_dashboard_show_in_getting_started ON public.report_dashboard USING btree (show_in_getting_started);


--
-- Name: idx_report_dashboardcard_action_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_dashboardcard_action_id ON public.report_dashboardcard USING btree (action_id);


--
-- Name: idx_report_dashboardcard_dashboard_tab_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_dashboardcard_dashboard_tab_id ON public.report_dashboardcard USING btree (dashboard_tab_id);


--
-- Name: idx_revision_model_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_revision_model_model_id ON public.revision USING btree (model, model_id);


--
-- Name: idx_revision_most_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_revision_most_recent ON public.revision USING btree (most_recent);


--
-- Name: idx_revision_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_revision_user_id ON public.revision USING btree (user_id);


--
-- Name: idx_routing_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_agent ON public.routing_decisions USING btree (agent_alias, created_at);


--
-- Name: idx_routing_capabilities; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_capabilities ON public.routing_decisions USING gin (mismatched_capabilities) WHERE capability_mismatch;


--
-- Name: idx_routing_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_created ON public.routing_decisions USING btree (created_at);


--
-- Name: idx_routing_incident; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_incident ON public.external_routing_metrics USING btree (incident_fingerprint) WHERE (incident_fingerprint IS NOT NULL);


--
-- Name: idx_routing_mismatch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_mismatch ON public.routing_decisions USING btree (capability_mismatch) WHERE capability_mismatch;


--
-- Name: idx_routing_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_provider ON public.external_routing_metrics USING btree (provider, created_at DESC);


--
-- Name: idx_routing_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_recent ON public.external_routing_metrics USING btree (created_at DESC);


--
-- Name: idx_routing_task_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_task_type ON public.external_routing_metrics USING btree (task_type, created_at DESC);


--
-- Name: idx_sandboxes_card_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sandboxes_card_id ON public.sandboxes USING btree (card_id);


--
-- Name: idx_scheduled_tasks_completed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_tasks_completed ON public.scheduled_tasks USING btree (completed_at DESC) WHERE (completed_at IS NOT NULL);


--
-- Name: idx_scheduled_tasks_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_tasks_pending ON public.scheduled_tasks USING btree (priority, scheduled_for) WHERE (picked_up_at IS NULL);


--
-- Name: idx_scheduler_jobs_completed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_jobs_completed ON public.scheduler_jobs USING btree (completed_at DESC) WHERE (status = ANY (ARRAY['completed'::public.job_status, 'failed'::public.job_status]));


--
-- Name: idx_scheduler_jobs_endpoint; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_jobs_endpoint ON public.scheduler_jobs USING btree (assigned_endpoint) WHERE (assigned_endpoint IS NOT NULL);


--
-- Name: idx_scheduler_jobs_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_jobs_pending ON public.scheduler_jobs USING btree (priority, created_at) WHERE (status = 'pending'::public.job_status);


--
-- Name: idx_scheduler_jobs_retry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_jobs_retry ON public.scheduler_jobs USING btree (created_at) WHERE ((status = 'failed'::public.job_status) AND (retry_count < max_retries));


--
-- Name: idx_scheduler_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_jobs_status ON public.scheduler_jobs USING btree (status);


--
-- Name: idx_scoring_rubrics_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scoring_rubrics_name ON public.scoring_rubrics USING btree (name);


--
-- Name: idx_secret_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_secret_creator_id ON public.secret USING btree (creator_id);


--
-- Name: idx_segment_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_segment_creator_id ON public.segment USING btree (creator_id);


--
-- Name: idx_segment_show_in_getting_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_segment_show_in_getting_started ON public.segment USING btree (show_in_getting_started);


--
-- Name: idx_segment_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_segment_table_id ON public.segment USING btree (table_id);


--
-- Name: idx_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_session_id ON public.login_history USING btree (session_id);


--
-- Name: idx_sessions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_profile ON public.sessions USING btree (profile_name, started_at DESC);


--
-- Name: idx_sessions_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_recent ON public.sessions USING btree (started_at DESC) WHERE (ended_at IS NOT NULL);


--
-- Name: idx_snippet_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_snippet_collection_id ON public.native_query_snippet USING btree (collection_id);


--
-- Name: idx_snippet_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_snippet_name ON public.native_query_snippet USING btree (name);


--
-- Name: idx_state_changes_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_state_changes_client ON public.state_changes USING btree (client_id, created_at DESC);


--
-- Name: idx_state_changes_kb_root; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_state_changes_kb_root ON public.state_changes USING btree (kb_root, created_at DESC);


--
-- Name: idx_summary_content; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_summary_content ON public.summary_lineage USING btree (content_item_id);


--
-- Name: idx_summary_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_summary_model ON public.summary_lineage USING btree (model_used);


--
-- Name: idx_summary_quality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_summary_quality ON public.summary_lineage USING btree (quality_score DESC);


--
-- Name: idx_summary_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_summary_run ON public.summary_lineage USING btree (lineage_run_id);


--
-- Name: idx_sync_runs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sync_runs_target ON public.kb_sync_runs USING btree (target_id, started_at DESC);


--
-- Name: idx_sync_state_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sync_state_path ON public.kb_sync_state USING btree (file_path);


--
-- Name: idx_sync_state_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sync_state_target ON public.kb_sync_state USING btree (target_id, sync_status);


--
-- Name: idx_table_db_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_table_db_id ON public.metabase_table USING btree (db_id);


--
-- Name: idx_table_privileges_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_table_privileges_role ON public.table_privileges USING btree (role);


--
-- Name: idx_table_privileges_table_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_table_privileges_table_id ON public.table_privileges USING btree (table_id);


--
-- Name: idx_task_history_db_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_history_db_id ON public.task_history USING btree (db_id);


--
-- Name: idx_task_history_end_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_history_end_time ON public.task_history USING btree (ended_at);


--
-- Name: idx_task_history_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_history_started_at ON public.task_history USING btree (started_at);


--
-- Name: idx_theta_consolidation_slice; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_theta_consolidation_slice ON public.theta_consolidation_runs USING btree (slice_id);


--
-- Name: idx_theta_consolidation_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_theta_consolidation_started ON public.theta_consolidation_runs USING btree (started_at);


--
-- Name: idx_theta_consolidation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_theta_consolidation_status ON public.theta_consolidation_runs USING btree (status);


--
-- Name: idx_theta_unique_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_theta_unique_pending ON public.theta_consolidation_runs USING btree (slice_id) WHERE (status = ANY (ARRAY['scheduled'::text, 'running'::text]));


--
-- Name: idx_thoughts_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_active ON public.cognition_thoughts USING btree (salience DESC, created_at DESC) WHERE (status = 'active'::text);


--
-- Name: idx_thoughts_chain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_chain ON public.cognition_thoughts USING btree (thought_chain_id) WHERE (thought_chain_id IS NOT NULL);


--
-- Name: idx_thoughts_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_content_hash ON public.cognition_thoughts USING btree (content_hash) WHERE (content_hash IS NOT NULL);


--
-- Name: idx_thoughts_domains; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_domains ON public.cognition_thoughts USING gin (domains);


--
-- Name: idx_thoughts_generation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_generation ON public.cognition_thoughts USING btree (generation DESC, created_at DESC) WHERE (generation > 0);


--
-- Name: idx_thoughts_note_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_note_path ON public.cognition_thoughts USING btree (note_path) WHERE (note_path IS NOT NULL);


--
-- Name: idx_thoughts_predecessor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_predecessor ON public.cognition_thoughts USING btree (predecessor_id) WHERE (predecessor_id IS NOT NULL);


--
-- Name: idx_thoughts_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_profile ON public.cognition_thoughts USING btree (profile_name, created_at DESC);


--
-- Name: idx_thoughts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thoughts_type ON public.cognition_thoughts USING btree (thought_type);


--
-- Name: idx_threads_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_threads_active ON public.research_threads USING btree (profile_name, last_activity DESC) WHERE (status = 'active'::text);


--
-- Name: idx_threads_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_threads_domain ON public.research_threads USING btree (domain) WHERE (status = 'active'::text);


--
-- Name: idx_timeline_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timeline_collection_id ON public.timeline USING btree (collection_id);


--
-- Name: idx_timeline_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timeline_creator_id ON public.timeline USING btree (creator_id);


--
-- Name: idx_timeline_event_creator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timeline_event_creator_id ON public.timeline_event USING btree (creator_id);


--
-- Name: idx_timeline_event_timeline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timeline_event_timeline_id ON public.timeline_event USING btree (timeline_id);


--
-- Name: idx_timeline_event_timeline_id_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timeline_event_timeline_id_timestamp ON public.timeline_event USING btree (timeline_id, "timestamp");


--
-- Name: idx_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_timestamp ON public.login_history USING btree ("timestamp");


--
-- Name: idx_topic_models_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_topic_models_created ON public.topic_models USING btree (created_at DESC);


--
-- Name: idx_topic_models_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_topic_models_type ON public.topic_models USING btree (model_type);


--
-- Name: idx_triage_assessments_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_triage_assessments_item ON public.triage_assessments USING btree (content_item_id);


--
-- Name: idx_triage_assessments_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_triage_assessments_type ON public.triage_assessments USING btree (assessment_type);


--
-- Name: idx_uniq_table_db_id_schema_name_2col; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_uniq_table_db_id_schema_name_2col ON public.metabase_table USING btree (db_id, name) WHERE (schema IS NULL);


--
-- Name: idx_user_full_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_full_name ON public.core_user USING btree (((((first_name)::text || ' '::text) || (last_name)::text)));


--
-- Name: idx_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_id ON public.login_history USING btree (user_id);


--
-- Name: idx_user_id_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_id_device_id ON public.login_history USING btree (user_id, device_id);


--
-- Name: idx_user_id_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_id_timestamp ON public.login_history USING btree (user_id, "timestamp");


--
-- Name: idx_user_parameter_value_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_parameter_value_dashboard_id ON public.user_parameter_value USING btree (dashboard_id);


--
-- Name: idx_user_parameter_value_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_parameter_value_user_id ON public.user_parameter_value USING btree (user_id);


--
-- Name: idx_user_parameter_value_user_id_dashboard_id_parameter_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_parameter_value_user_id_dashboard_id_parameter_id ON public.user_parameter_value USING btree (user_id, dashboard_id, parameter_id);


--
-- Name: idx_user_qualified_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_qualified_id ON public.core_user USING btree ((('user_'::text || id)));


--
-- Name: idx_verifications_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_created ON public.objective_verifications USING btree (started_at DESC);


--
-- Name: idx_verifications_eligible; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_eligible ON public.objective_verifications USING btree (eligible_for_training) WHERE eligible_for_training;


--
-- Name: idx_verifications_objective; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_objective ON public.objective_verifications USING btree (objective_name);


--
-- Name: idx_verifications_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_run ON public.objective_verifications USING btree (run_id);


--
-- Name: idx_verifications_verdict; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verifications_verdict ON public.objective_verifications USING btree (verdict);


--
-- Name: idx_view_log_entity_qualified_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_view_log_entity_qualified_id ON public.view_log USING btree (((((model)::text || '_'::text) || model_id)));


--
-- Name: idx_view_log_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_view_log_model_id ON public.view_log USING btree (model_id);


--
-- Name: idx_view_log_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_view_log_timestamp ON public.view_log USING btree ("timestamp");


--
-- Name: idx_view_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_view_log_user_id ON public.view_log USING btree (user_id);


--
-- Name: idx_x_api_queued; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_api_queued ON public.x_api_requests USING btree (status, priority DESC, queued_at) WHERE ((status)::text = 'queued'::text);


--
-- Name: idx_x_api_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_api_user ON public.x_api_requests USING btree (user_id, completed_at DESC);


--
-- Name: idx_x_auto_sync_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_auto_sync_active ON public.x_auto_sync_schedules USING btree (is_active, next_run_at) WHERE (is_active = true);


--
-- Name: idx_x_bookmarks_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_bookmarks_folder ON public.x_bookmarks_sync USING btree (folder_id);


--
-- Name: idx_x_bookmarks_synced; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_bookmarks_synced ON public.x_bookmarks_sync USING btree (synced_at DESC);


--
-- Name: idx_x_bookmarks_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_bookmarks_user ON public.x_bookmarks_sync USING btree (user_id);


--
-- Name: idx_x_folders_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_folders_user ON public.x_bookmark_folders USING btree (user_id);


--
-- Name: idx_x_oauth_pending_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_oauth_pending_expires ON public.x_oauth_pending USING btree (expires_at);


--
-- Name: idx_x_sync_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_sync_runs_status ON public.x_sync_runs USING btree (status) WHERE ((status)::text = ANY ((ARRAY['running'::character varying, 'rate_limited'::character varying])::text[]));


--
-- Name: idx_x_sync_runs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_x_sync_runs_user ON public.x_sync_runs USING btree (user_id, started_at DESC);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__4asdmoroquqdnn2arfyd5_archived_idx ON public.search_index__4asdmoroquqdnn2arfyd5 USING btree (archived);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_identity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX search_index__4asdmoroquqdnn2arfyd5_identity_idx ON public.search_index__4asdmoroquqdnn2arfyd5 USING btree (model, model_id);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_model_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__4asdmoroquqdnn2arfyd5_model_archived_idx ON public.search_index__4asdmoroquqdnn2arfyd5 USING btree (model, archived);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_native_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__4asdmoroquqdnn2arfyd5_native_tsvector_idx ON public.search_index__4asdmoroquqdnn2arfyd5 USING gin (with_native_query_vector);


--
-- Name: search_index__4asdmoroquqdnn2arfyd5_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__4asdmoroquqdnn2arfyd5_tsvector_idx ON public.search_index__4asdmoroquqdnn2arfyd5 USING gin (search_vector);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__cvo4ibtsyjzvh5x7v49a6_archived_idx ON public.search_index__cvo4ibtsyjzvh5x7v49a6 USING btree (archived);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_identity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX search_index__cvo4ibtsyjzvh5x7v49a6_identity_idx ON public.search_index__cvo4ibtsyjzvh5x7v49a6 USING btree (model, model_id);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_model_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__cvo4ibtsyjzvh5x7v49a6_model_archived_idx ON public.search_index__cvo4ibtsyjzvh5x7v49a6 USING btree (model, archived);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_native_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__cvo4ibtsyjzvh5x7v49a6_native_tsvector_idx ON public.search_index__cvo4ibtsyjzvh5x7v49a6 USING gin (with_native_query_vector);


--
-- Name: search_index__cvo4ibtsyjzvh5x7v49a6_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__cvo4ibtsyjzvh5x7v49a6_tsvector_idx ON public.search_index__cvo4ibtsyjzvh5x7v49a6 USING gin (search_vector);


--
-- Name: v_source_status _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.v_source_status AS
 SELECT fs.name,
    fs.source_type,
    fs.active,
    fs.fetch_interval_minutes,
    fs.last_fetch_at,
        CASE
            WHEN (fs.last_fetch_at IS NULL) THEN 'never'::text
            WHEN (fs.last_fetch_at < (now() - ((fs.fetch_interval_minutes || ' minutes'::text))::interval)) THEN 'overdue'::text
            ELSE 'ok'::text
        END AS status,
    ( SELECT count(*) AS count
           FROM public.content_items ci
          WHERE (ci.source_id = fs.id)) AS total_items,
    ( SELECT count(*) AS count
           FROM public.content_items ci
          WHERE ((ci.source_id = fs.id) AND (ci.kb_path IS NOT NULL))) AS kb_items,
    ( SELECT count(*) AS count
           FROM public.fetch_jobs fj
          WHERE ((fj.source_id = fs.id) AND (fj.status = 'scheduled'::text))) AS pending_jobs,
    array_agg(DISTINCT p.name) AS profiles
   FROM ((public.feed_sources fs
     LEFT JOIN public.profile_sources ps ON ((ps.source_id = fs.id)))
     LEFT JOIN public.profiles p ON ((p.id = ps.profile_id)))
  GROUP BY fs.id
  ORDER BY fs.name;


--
-- Name: flow_runs meta_flow_runs_notify; Type: TRIGGER; Schema: meta; Owner: -
--

CREATE TRIGGER meta_flow_runs_notify AFTER UPDATE ON meta.flow_runs FOR EACH ROW EXECUTE FUNCTION meta.notify_flow_event();


--
-- Name: TRIGGER meta_flow_runs_notify ON flow_runs; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TRIGGER meta_flow_runs_notify ON meta.flow_runs IS 'Fires pg_notify when flow status changes to completed/failed';


--
-- Name: flow_runs meta_flow_runs_update_timestamp; Type: TRIGGER; Schema: meta; Owner: -
--

CREATE TRIGGER meta_flow_runs_update_timestamp BEFORE UPDATE ON meta.flow_runs FOR EACH ROW EXECUTE FUNCTION meta.update_flow_runs_timestamp();


--
-- Name: research_progress research_progress_notify; Type: TRIGGER; Schema: meta; Owner: -
--

CREATE TRIGGER research_progress_notify AFTER INSERT ON meta.research_progress FOR EACH ROW EXECUTE FUNCTION meta.notify_research_progress();


--
-- Name: TRIGGER research_progress_notify ON research_progress; Type: COMMENT; Schema: meta; Owner: -
--

COMMENT ON TRIGGER research_progress_notify ON meta.research_progress IS 'Real-time progress streaming to TUI via LISTEN/NOTIFY';


--
-- Name: audit_budget_pool trg_reset_weekly_budget; Type: TRIGGER; Schema: meta; Owner: -
--

CREATE TRIGGER trg_reset_weekly_budget BEFORE UPDATE ON meta.audit_budget_pool FOR EACH ROW EXECUTE FUNCTION meta.check_reset_weekly_budget();


--
-- Name: health_observer_state health_observer_state_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER health_observer_state_updated BEFORE UPDATE ON public.health_observer_state FOR EACH ROW EXECUTE FUNCTION public.update_health_observer_timestamp();


--
-- Name: profiles profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER profiles_updated_at BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: evolution_calibrations trg_update_calibration_summary; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_update_calibration_summary AFTER INSERT ON public.evolution_calibrations FOR EACH ROW EXECUTE FUNCTION public.update_calibration_summary();


--
-- Name: audit_recommendations audit_recommendations_audit_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.audit_recommendations
    ADD CONSTRAINT audit_recommendations_audit_id_fkey FOREIGN KEY (audit_id) REFERENCES meta.metaagent_audits(audit_id) ON DELETE CASCADE;


--
-- Name: data_dependencies data_dependencies_source_dataset_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies
    ADD CONSTRAINT data_dependencies_source_dataset_id_fkey FOREIGN KEY (source_dataset_id) REFERENCES meta.dataset_catalog(dataset_id);


--
-- Name: data_dependencies data_dependencies_target_dataset_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies
    ADD CONSTRAINT data_dependencies_target_dataset_id_fkey FOREIGN KEY (target_dataset_id) REFERENCES meta.dataset_catalog(dataset_id);


--
-- Name: data_dependencies data_dependencies_via_job_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies
    ADD CONSTRAINT data_dependencies_via_job_id_fkey FOREIGN KEY (via_job_id) REFERENCES meta.job_catalog(job_id);


--
-- Name: document_clusters document_clusters_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.document_clusters
    ADD CONSTRAINT document_clusters_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES meta.kb_topology(snapshot_id);


--
-- Name: flow_events fk_flow_events_run_id; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.flow_events
    ADD CONSTRAINT fk_flow_events_run_id FOREIGN KEY (run_id) REFERENCES meta.flow_runs(run_id) ON DELETE CASCADE;


--
-- Name: fmea_rpn_timeseries fmea_rpn_timeseries_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.fmea_rpn_timeseries
    ADD CONSTRAINT fmea_rpn_timeseries_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: prospect_strategies prospect_strategies_symbol_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.prospect_strategies
    ADD CONSTRAINT prospect_strategies_symbol_fkey FOREIGN KEY (symbol) REFERENCES meta.prospect_candidates(symbol) ON DELETE CASCADE;


--
-- Name: semantic_attractors semantic_attractors_merged_into_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_attractors
    ADD CONSTRAINT semantic_attractors_merged_into_id_fkey FOREIGN KEY (merged_into_id) REFERENCES meta.semantic_attractors(id);


--
-- Name: semantic_attractors semantic_attractors_split_from_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_attractors
    ADD CONSTRAINT semantic_attractors_split_from_id_fkey FOREIGN KEY (split_from_id) REFERENCES meta.semantic_attractors(id);


--
-- Name: swarm_agent_positions swarm_agent_positions_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.swarm_agent_positions
    ADD CONSTRAINT swarm_agent_positions_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES meta.swarm_snapshots(snapshot_id) ON DELETE CASCADE;


--
-- Name: agenda_operations agenda_operations_escalated_to_incident_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_operations
    ADD CONSTRAINT agenda_operations_escalated_to_incident_id_fkey FOREIGN KEY (escalated_to_incident_id) REFERENCES public.agenda_incidents(id);


--
-- Name: agenda_phase_events agenda_phase_events_agenda_incident_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agenda_phase_events
    ADD CONSTRAINT agenda_phase_events_agenda_incident_id_fkey FOREIGN KEY (agenda_incident_id) REFERENCES public.agenda_incidents(id) ON DELETE CASCADE;


--
-- Name: agent_evaluations agent_evaluations_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_evaluations
    ADD CONSTRAINT agent_evaluations_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.agent_versions(version_id);


--
-- Name: agent_versions agent_versions_parent_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_parent_version_fkey FOREIGN KEY (parent_version) REFERENCES public.agent_versions(version_id);


--
-- Name: aiops_events aiops_events_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aiops_events
    ADD CONSTRAINT aiops_events_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: archive_rotations archive_rotations_doc_archive_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archive_rotations
    ADD CONSTRAINT archive_rotations_doc_archive_id_fkey FOREIGN KEY (doc_archive_id) REFERENCES public.doc_archives(id) ON DELETE SET NULL;


--
-- Name: cognition_thoughts cognition_thoughts_predecessor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cognition_thoughts
    ADD CONSTRAINT cognition_thoughts_predecessor_id_fkey FOREIGN KEY (predecessor_id) REFERENCES public.cognition_thoughts(id);


--
-- Name: content_items content_items_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE SET NULL;


--
-- Name: current_state current_state_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.current_state
    ADD CONSTRAINT current_state_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE SET NULL;


--
-- Name: doc_archives doc_archives_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doc_archives
    ADD CONSTRAINT doc_archives_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE CASCADE;


--
-- Name: document_topics document_topics_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_topics
    ADD CONSTRAINT document_topics_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.topic_models(id);


--
-- Name: engine_observations engine_observations_related_thought_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations
    ADD CONSTRAINT engine_observations_related_thought_id_fkey FOREIGN KEY (related_thought_id) REFERENCES public.cognition_thoughts(id);


--
-- Name: evolution_calibrations evolution_calibrations_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evolution_calibrations
    ADD CONSTRAINT evolution_calibrations_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.agent_versions(version_id);


--
-- Name: fetch_jobs fetch_jobs_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs
    ADD CONSTRAINT fetch_jobs_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE CASCADE;


--
-- Name: action fk_action_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT fk_action_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id);


--
-- Name: action fk_action_made_public_by_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT fk_action_made_public_by_id FOREIGN KEY (made_public_by_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: action fk_action_model_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action
    ADD CONSTRAINT fk_action_model_id FOREIGN KEY (model_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: api_key fk_api_key_created_by_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT fk_api_key_created_by_user_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id);


--
-- Name: api_key fk_api_key_updated_by_id_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT fk_api_key_updated_by_id_user_id FOREIGN KEY (updated_by_id) REFERENCES public.core_user(id);


--
-- Name: api_key fk_api_key_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_key
    ADD CONSTRAINT fk_api_key_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id);


--
-- Name: bookmark_ordering fk_bookmark_ordering_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bookmark_ordering
    ADD CONSTRAINT fk_bookmark_ordering_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: card_bookmark fk_card_bookmark_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_bookmark
    ADD CONSTRAINT fk_card_bookmark_dashboard_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: card_bookmark fk_card_bookmark_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_bookmark
    ADD CONSTRAINT fk_card_bookmark_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_card fk_card_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_card_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE SET NULL;


--
-- Name: card_label fk_card_label_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_label
    ADD CONSTRAINT fk_card_label_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: card_label fk_card_label_ref_label_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_label
    ADD CONSTRAINT fk_card_label_ref_label_id FOREIGN KEY (label_id) REFERENCES public.label(id) ON DELETE CASCADE;


--
-- Name: report_card fk_card_made_public_by_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_card_made_public_by_id FOREIGN KEY (made_public_by_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_card fk_card_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_card_ref_user_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_cardfavorite fk_cardfavorite_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_cardfavorite
    ADD CONSTRAINT fk_cardfavorite_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: report_cardfavorite fk_cardfavorite_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_cardfavorite
    ADD CONSTRAINT fk_cardfavorite_ref_user_id FOREIGN KEY (owner_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: collection_bookmark fk_collection_bookmark_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_bookmark
    ADD CONSTRAINT fk_collection_bookmark_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE CASCADE;


--
-- Name: collection_bookmark fk_collection_bookmark_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_bookmark
    ADD CONSTRAINT fk_collection_bookmark_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: collection fk_collection_personal_owner_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection
    ADD CONSTRAINT fk_collection_personal_owner_id FOREIGN KEY (personal_owner_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: collection_permission_graph_revision fk_collection_revision_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_permission_graph_revision
    ADD CONSTRAINT fk_collection_revision_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: connection_impersonations fk_conn_impersonation_db_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.connection_impersonations
    ADD CONSTRAINT fk_conn_impersonation_db_id FOREIGN KEY (db_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: connection_impersonations fk_conn_impersonation_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.connection_impersonations
    ADD CONSTRAINT fk_conn_impersonation_group_id FOREIGN KEY (group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: dashboard_bookmark fk_dashboard_bookmark_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_bookmark
    ADD CONSTRAINT fk_dashboard_bookmark_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: dashboard_bookmark fk_dashboard_bookmark_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_bookmark
    ADD CONSTRAINT fk_dashboard_bookmark_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_dashboard fk_dashboard_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT fk_dashboard_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE SET NULL;


--
-- Name: dashboard_favorite fk_dashboard_favorite_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_favorite
    ADD CONSTRAINT fk_dashboard_favorite_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: dashboard_favorite fk_dashboard_favorite_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_favorite
    ADD CONSTRAINT fk_dashboard_favorite_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_dashboard fk_dashboard_made_public_by_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT fk_dashboard_made_public_by_id FOREIGN KEY (made_public_by_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_dashboard fk_dashboard_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboard
    ADD CONSTRAINT fk_dashboard_ref_user_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: dashboard_tab fk_dashboard_tab_ref_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_tab
    ADD CONSTRAINT fk_dashboard_tab_ref_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: report_dashboardcard fk_dashboardcard_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT fk_dashboardcard_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: report_dashboardcard fk_dashboardcard_ref_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT fk_dashboardcard_ref_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: dashboardcard_series fk_dashboardcard_series_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboardcard_series
    ADD CONSTRAINT fk_dashboardcard_series_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: dashboardcard_series fk_dashboardcard_series_ref_dashboardcard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboardcard_series
    ADD CONSTRAINT fk_dashboardcard_series_ref_dashboardcard_id FOREIGN KEY (dashboardcard_id) REFERENCES public.report_dashboardcard(id) ON DELETE CASCADE;


--
-- Name: data_permissions fk_data_permissions_ref_db_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_permissions
    ADD CONSTRAINT fk_data_permissions_ref_db_id FOREIGN KEY (db_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: data_permissions fk_data_permissions_ref_permissions_group; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_permissions
    ADD CONSTRAINT fk_data_permissions_ref_permissions_group FOREIGN KEY (group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: data_permissions fk_data_permissions_ref_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_permissions
    ADD CONSTRAINT fk_data_permissions_ref_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: metabase_database fk_database_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_database
    ADD CONSTRAINT fk_database_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE SET NULL;


--
-- Name: db_router fk_db_router_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.db_router
    ADD CONSTRAINT fk_db_router_database_id FOREIGN KEY (database_id) REFERENCES public.metabase_database(id);


--
-- Name: dimension fk_dimension_displayfk_ref_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dimension
    ADD CONSTRAINT fk_dimension_displayfk_ref_field_id FOREIGN KEY (human_readable_field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: dimension fk_dimension_ref_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dimension
    ADD CONSTRAINT fk_dimension_ref_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: timeline_event fk_event_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline_event
    ADD CONSTRAINT fk_event_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: timeline_event fk_events_timeline_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline_event
    ADD CONSTRAINT fk_events_timeline_id FOREIGN KEY (timeline_id) REFERENCES public.timeline(id) ON DELETE CASCADE;


--
-- Name: metabase_field fk_field_parent_ref_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field
    ADD CONSTRAINT fk_field_parent_ref_field_id FOREIGN KEY (parent_id) REFERENCES public.metabase_field(id) ON DELETE RESTRICT;


--
-- Name: metabase_field fk_field_ref_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field
    ADD CONSTRAINT fk_field_ref_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: field_usage fk_field_usage_field_id_metabase_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_usage
    ADD CONSTRAINT fk_field_usage_field_id_metabase_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: field_usage fk_field_usage_query_execution_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_usage
    ADD CONSTRAINT fk_field_usage_query_execution_id FOREIGN KEY (query_execution_id) REFERENCES public.query_execution(id) ON DELETE CASCADE;


--
-- Name: metabase_field_user_settings fk_field_user_setting_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_field_user_settings
    ADD CONSTRAINT fk_field_user_setting_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: metabase_fieldvalues fk_fieldvalues_ref_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_fieldvalues
    ADD CONSTRAINT fk_fieldvalues_ref_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: application_permissions_revision fk_general_permissions_revision_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_permissions_revision
    ADD CONSTRAINT fk_general_permissions_revision_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id);


--
-- Name: sandboxes fk_gtap_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandboxes
    ADD CONSTRAINT fk_gtap_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: sandboxes fk_gtap_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandboxes
    ADD CONSTRAINT fk_gtap_group_id FOREIGN KEY (group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: sandboxes fk_gtap_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandboxes
    ADD CONSTRAINT fk_gtap_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: http_action fk_http_action_ref_action_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.http_action
    ADD CONSTRAINT fk_http_action_ref_action_id FOREIGN KEY (action_id) REFERENCES public.action(id) ON DELETE CASCADE;


--
-- Name: implicit_action fk_implicit_action_action_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.implicit_action
    ADD CONSTRAINT fk_implicit_action_action_id FOREIGN KEY (action_id) REFERENCES public.action(id) ON DELETE CASCADE;


--
-- Name: login_history fk_login_history_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_history
    ADD CONSTRAINT fk_login_history_session_id FOREIGN KEY (session_id) REFERENCES public.core_session(id) ON DELETE SET NULL;


--
-- Name: login_history fk_login_history_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_history
    ADD CONSTRAINT fk_login_history_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: metabase_database fk_metabase_database_metabase_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_database
    ADD CONSTRAINT fk_metabase_database_metabase_database_id FOREIGN KEY (router_database_id) REFERENCES public.metabase_database(id) ON DELETE RESTRICT;


--
-- Name: metabot_conversation fk_metabot_conversation_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_conversation
    ADD CONSTRAINT fk_metabot_conversation_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id);


--
-- Name: metabot_entity fk_metabot_entity_metabot_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_entity
    ADD CONSTRAINT fk_metabot_entity_metabot_id FOREIGN KEY (metabot_id) REFERENCES public.metabot(id) ON DELETE CASCADE;


--
-- Name: metabot_message fk_metabot_message_conversation_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_message
    ADD CONSTRAINT fk_metabot_message_conversation_id FOREIGN KEY (conversation_id) REFERENCES public.metabot_conversation(id);


--
-- Name: metabot_prompt fk_metabot_prompt_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_prompt
    ADD CONSTRAINT fk_metabot_prompt_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: metabot_prompt fk_metabot_prompt_metabot_entity_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabot_prompt
    ADD CONSTRAINT fk_metabot_prompt_metabot_entity_id FOREIGN KEY (metabot_entity_id) REFERENCES public.metabot_entity(id) ON DELETE CASCADE;


--
-- Name: metric_important_field fk_metric_important_field_metabase_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_important_field
    ADD CONSTRAINT fk_metric_important_field_metabase_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: metric_important_field fk_metric_important_field_metric_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_important_field
    ADD CONSTRAINT fk_metric_important_field_metric_id FOREIGN KEY (metric_id) REFERENCES public.metric(id) ON DELETE CASCADE;


--
-- Name: metric fk_metric_ref_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric
    ADD CONSTRAINT fk_metric_ref_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: metric fk_metric_ref_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric
    ADD CONSTRAINT fk_metric_ref_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: model_index fk_model_index_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_index
    ADD CONSTRAINT fk_model_index_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: model_index fk_model_index_model_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_index
    ADD CONSTRAINT fk_model_index_model_id FOREIGN KEY (model_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: model_index_value fk_model_index_value_model_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_index_value
    ADD CONSTRAINT fk_model_index_value_model_id FOREIGN KEY (model_index_id) REFERENCES public.model_index(id) ON DELETE CASCADE;


--
-- Name: notification_card fk_notification_card_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_card
    ADD CONSTRAINT fk_notification_card_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: notification fk_notification_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT fk_notification_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: notification_handler fk_notification_handler_channel_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_handler
    ADD CONSTRAINT fk_notification_handler_channel_id FOREIGN KEY (channel_id) REFERENCES public.channel(id) ON DELETE CASCADE;


--
-- Name: notification_handler fk_notification_handler_notification_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_handler
    ADD CONSTRAINT fk_notification_handler_notification_id FOREIGN KEY (notification_id) REFERENCES public.notification(id) ON DELETE CASCADE;


--
-- Name: notification_handler fk_notification_handler_template_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_handler
    ADD CONSTRAINT fk_notification_handler_template_id FOREIGN KEY (template_id) REFERENCES public.channel_template(id) ON DELETE SET NULL;


--
-- Name: notification_recipient fk_notification_recipient_notification_handler_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_recipient
    ADD CONSTRAINT fk_notification_recipient_notification_handler_id FOREIGN KEY (notification_handler_id) REFERENCES public.notification_handler(id) ON DELETE CASCADE;


--
-- Name: notification_recipient fk_notification_recipient_permissions_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_recipient
    ADD CONSTRAINT fk_notification_recipient_permissions_group_id FOREIGN KEY (permissions_group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: notification_recipient fk_notification_recipient_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_recipient
    ADD CONSTRAINT fk_notification_recipient_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: notification_subscription fk_notification_subscription_notification_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_subscription
    ADD CONSTRAINT fk_notification_subscription_notification_id FOREIGN KEY (notification_id) REFERENCES public.notification(id) ON DELETE CASCADE;


--
-- Name: parameter_card fk_parameter_card_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parameter_card
    ADD CONSTRAINT fk_parameter_card_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: permissions_group_membership fk_permissions_group_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group_membership
    ADD CONSTRAINT fk_permissions_group_group_id FOREIGN KEY (group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: permissions fk_permissions_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT fk_permissions_group_id FOREIGN KEY (group_id) REFERENCES public.permissions_group(id) ON DELETE CASCADE;


--
-- Name: permissions_group_membership fk_permissions_group_membership_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_group_membership
    ADD CONSTRAINT fk_permissions_group_membership_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: permissions fk_permissions_ref_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT fk_permissions_ref_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE CASCADE;


--
-- Name: permissions_revision fk_permissions_revision_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions_revision
    ADD CONSTRAINT fk_permissions_revision_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: persisted_info fk_persisted_info_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persisted_info
    ADD CONSTRAINT fk_persisted_info_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE SET NULL;


--
-- Name: persisted_info fk_persisted_info_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persisted_info
    ADD CONSTRAINT fk_persisted_info_database_id FOREIGN KEY (database_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: persisted_info fk_persisted_info_ref_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persisted_info
    ADD CONSTRAINT fk_persisted_info_ref_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id);


--
-- Name: pulse_card fk_pulse_card_ref_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_card
    ADD CONSTRAINT fk_pulse_card_ref_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: pulse_card fk_pulse_card_ref_pulse_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_card
    ADD CONSTRAINT fk_pulse_card_ref_pulse_card_id FOREIGN KEY (dashboard_card_id) REFERENCES public.report_dashboardcard(id) ON DELETE CASCADE;


--
-- Name: pulse_card fk_pulse_card_ref_pulse_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_card
    ADD CONSTRAINT fk_pulse_card_ref_pulse_id FOREIGN KEY (pulse_id) REFERENCES public.pulse(id) ON DELETE CASCADE;


--
-- Name: pulse_channel fk_pulse_channel_channel_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel
    ADD CONSTRAINT fk_pulse_channel_channel_id FOREIGN KEY (channel_id) REFERENCES public.channel(id) ON DELETE CASCADE;


--
-- Name: pulse_channel_recipient fk_pulse_channel_recipient_ref_pulse_channel_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel_recipient
    ADD CONSTRAINT fk_pulse_channel_recipient_ref_pulse_channel_id FOREIGN KEY (pulse_channel_id) REFERENCES public.pulse_channel(id) ON DELETE CASCADE;


--
-- Name: pulse_channel_recipient fk_pulse_channel_recipient_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel_recipient
    ADD CONSTRAINT fk_pulse_channel_recipient_ref_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: pulse_channel fk_pulse_channel_ref_pulse_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse_channel
    ADD CONSTRAINT fk_pulse_channel_ref_pulse_id FOREIGN KEY (pulse_id) REFERENCES public.pulse(id) ON DELETE CASCADE;


--
-- Name: pulse fk_pulse_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT fk_pulse_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE SET NULL;


--
-- Name: pulse fk_pulse_ref_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT fk_pulse_ref_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: pulse fk_pulse_ref_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT fk_pulse_ref_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: qrtz_blob_triggers fk_qrtz_blob_triggers_triggers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_blob_triggers
    ADD CONSTRAINT fk_qrtz_blob_triggers_triggers FOREIGN KEY (sched_name, trigger_name, trigger_group) REFERENCES public.qrtz_triggers(sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_cron_triggers fk_qrtz_cron_triggers_triggers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_cron_triggers
    ADD CONSTRAINT fk_qrtz_cron_triggers_triggers FOREIGN KEY (sched_name, trigger_name, trigger_group) REFERENCES public.qrtz_triggers(sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_simple_triggers fk_qrtz_simple_triggers_triggers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_simple_triggers
    ADD CONSTRAINT fk_qrtz_simple_triggers_triggers FOREIGN KEY (sched_name, trigger_name, trigger_group) REFERENCES public.qrtz_triggers(sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_simprop_triggers fk_qrtz_simprop_triggers_triggers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_simprop_triggers
    ADD CONSTRAINT fk_qrtz_simprop_triggers_triggers FOREIGN KEY (sched_name, trigger_name, trigger_group) REFERENCES public.qrtz_triggers(sched_name, trigger_name, trigger_group);


--
-- Name: qrtz_triggers fk_qrtz_triggers_job_details; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qrtz_triggers
    ADD CONSTRAINT fk_qrtz_triggers_job_details FOREIGN KEY (sched_name, job_name, job_group) REFERENCES public.qrtz_job_details(sched_name, job_name, job_group);


--
-- Name: query_action fk_query_action_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_action
    ADD CONSTRAINT fk_query_action_database_id FOREIGN KEY (database_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: query_action fk_query_action_ref_action_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_action
    ADD CONSTRAINT fk_query_action_ref_action_id FOREIGN KEY (action_id) REFERENCES public.action(id) ON DELETE CASCADE;


--
-- Name: query_field fk_query_field_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_field
    ADD CONSTRAINT fk_query_field_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: query_field fk_query_field_field_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_field
    ADD CONSTRAINT fk_query_field_field_id FOREIGN KEY (field_id) REFERENCES public.metabase_field(id) ON DELETE CASCADE;


--
-- Name: query_table fk_query_table_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_table
    ADD CONSTRAINT fk_query_table_card_id FOREIGN KEY (card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: query_table fk_query_table_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_table
    ADD CONSTRAINT fk_query_table_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: recent_views fk_recent_views_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recent_views
    ADD CONSTRAINT fk_recent_views_ref_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: report_card fk_report_card_ref_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_report_card_ref_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: report_card fk_report_card_ref_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_report_card_ref_database_id FOREIGN KEY (database_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: report_card fk_report_card_ref_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_report_card_ref_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: report_card fk_report_card_source_card_id_ref_report_card_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_card
    ADD CONSTRAINT fk_report_card_source_card_id_ref_report_card_id FOREIGN KEY (source_card_id) REFERENCES public.report_card(id) ON DELETE CASCADE;


--
-- Name: report_dashboardcard fk_report_dashboardcard_ref_action_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT fk_report_dashboardcard_ref_action_id FOREIGN KEY (action_id) REFERENCES public.action(id) ON DELETE CASCADE;


--
-- Name: report_dashboardcard fk_report_dashboardcard_ref_dashboard_tab_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_dashboardcard
    ADD CONSTRAINT fk_report_dashboardcard_ref_dashboard_tab_id FOREIGN KEY (dashboard_tab_id) REFERENCES public.dashboard_tab(id) ON DELETE CASCADE;


--
-- Name: revision fk_revision_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revision
    ADD CONSTRAINT fk_revision_ref_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: secret fk_secret_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret
    ADD CONSTRAINT fk_secret_ref_user_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id);


--
-- Name: segment fk_segment_ref_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segment
    ADD CONSTRAINT fk_segment_ref_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: segment fk_segment_ref_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segment
    ADD CONSTRAINT fk_segment_ref_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: core_session fk_session_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_session
    ADD CONSTRAINT fk_session_ref_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: native_query_snippet fk_snippet_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_query_snippet
    ADD CONSTRAINT fk_snippet_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE SET NULL;


--
-- Name: native_query_snippet fk_snippet_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_query_snippet
    ADD CONSTRAINT fk_snippet_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: table_privileges fk_table_privileges_table_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.table_privileges
    ADD CONSTRAINT fk_table_privileges_table_id FOREIGN KEY (table_id) REFERENCES public.metabase_table(id) ON DELETE CASCADE;


--
-- Name: metabase_table fk_table_ref_database_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metabase_table
    ADD CONSTRAINT fk_table_ref_database_id FOREIGN KEY (db_id) REFERENCES public.metabase_database(id) ON DELETE CASCADE;


--
-- Name: timeline fk_timeline_collection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline
    ADD CONSTRAINT fk_timeline_collection_id FOREIGN KEY (collection_id) REFERENCES public.collection(id) ON DELETE CASCADE;


--
-- Name: timeline fk_timeline_creator_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.timeline
    ADD CONSTRAINT fk_timeline_creator_id FOREIGN KEY (creator_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: user_key_value fk_user_key_value_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_key_value
    ADD CONSTRAINT fk_user_key_value_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id);


--
-- Name: user_parameter_value fk_user_parameter_value_dashboard_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_parameter_value
    ADD CONSTRAINT fk_user_parameter_value_dashboard_id FOREIGN KEY (dashboard_id) REFERENCES public.report_dashboard(id) ON DELETE CASCADE;


--
-- Name: user_parameter_value fk_user_parameter_value_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_parameter_value
    ADD CONSTRAINT fk_user_parameter_value_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: view_log fk_view_log_ref_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_log
    ADD CONSTRAINT fk_view_log_ref_user_id FOREIGN KEY (user_id) REFERENCES public.core_user(id) ON DELETE CASCADE;


--
-- Name: fmea_adjustments fmea_adjustments_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_adjustments
    ADD CONSTRAINT fmea_adjustments_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: fmea_occurrences fmea_occurrences_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_occurrences
    ADD CONSTRAINT fmea_occurrences_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: fmea_outcomes fmea_outcomes_aiops_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_outcomes
    ADD CONSTRAINT fmea_outcomes_aiops_event_id_fkey FOREIGN KEY (aiops_event_id) REFERENCES public.aiops_events(id);


--
-- Name: fmea_outcomes fmea_outcomes_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_outcomes
    ADD CONSTRAINT fmea_outcomes_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: fmea_outcomes fmea_outcomes_mlops_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fmea_outcomes
    ADD CONSTRAINT fmea_outcomes_mlops_event_id_fkey FOREIGN KEY (mlops_event_id) REFERENCES public.mlops_events(id);


--
-- Name: grid_allocations grid_allocations_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_allocations
    ADD CONSTRAINT grid_allocations_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE CASCADE;


--
-- Name: grid_clusters grid_clusters_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_clusters
    ADD CONSTRAINT grid_clusters_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE CASCADE;


--
-- Name: grid_embeddings grid_embeddings_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_embeddings
    ADD CONSTRAINT grid_embeddings_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE CASCADE;


--
-- Name: grid_points grid_points_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_points
    ADD CONSTRAINT grid_points_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE CASCADE;


--
-- Name: grid_tda_features grid_tda_features_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_tda_features
    ADD CONSTRAINT grid_tda_features_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.grid_snapshots(id) ON DELETE CASCADE;


--
-- Name: healing_events healing_events_aiops_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events
    ADD CONSTRAINT healing_events_aiops_event_id_fkey FOREIGN KEY (aiops_event_id) REFERENCES public.aiops_events(id);


--
-- Name: healing_events healing_events_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.healing_events
    ADD CONSTRAINT healing_events_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: kb_sync_runs kb_sync_runs_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_runs
    ADD CONSTRAINT kb_sync_runs_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.kb_sync_targets(id) ON DELETE CASCADE;


--
-- Name: kb_sync_state kb_sync_state_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_sync_state
    ADD CONSTRAINT kb_sync_state_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.kb_sync_targets(id) ON DELETE CASCADE;


--
-- Name: mlops_events mlops_events_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mlops_events
    ADD CONSTRAINT mlops_events_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: objective_verifications objective_verifications_calibration_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objective_verifications
    ADD CONSTRAINT objective_verifications_calibration_id_fkey FOREIGN KEY (calibration_id) REFERENCES public.evolution_calibrations(id);


--
-- Name: optimization_runs optimization_runs_best_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs
    ADD CONSTRAINT optimization_runs_best_version_id_fkey FOREIGN KEY (best_version_id) REFERENCES public.agent_versions(version_id);


--
-- Name: paper_scores paper_scores_rubric_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_scores
    ADD CONSTRAINT paper_scores_rubric_id_fkey FOREIGN KEY (rubric_id) REFERENCES public.scoring_rubrics(id);


--
-- Name: profile_content profile_content_content_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_content
    ADD CONSTRAINT profile_content_content_id_fkey FOREIGN KEY (content_id) REFERENCES public.content_items(id) ON DELETE CASCADE;


--
-- Name: profile_content profile_content_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_content
    ADD CONSTRAINT profile_content_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE CASCADE;


--
-- Name: profile_domains profile_domains_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_domains
    ADD CONSTRAINT profile_domains_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE CASCADE;


--
-- Name: profile_sources profile_sources_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_sources
    ADD CONSTRAINT profile_sources_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE CASCADE;


--
-- Name: profile_sources profile_sources_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_sources
    ADD CONSTRAINT profile_sources_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE CASCADE;


--
-- Name: remediation_approvals remediation_approvals_failure_mode_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remediation_approvals
    ADD CONSTRAINT remediation_approvals_failure_mode_id_fkey FOREIGN KEY (failure_mode_id) REFERENCES public.fmea_catalog(failure_mode_id);


--
-- Name: research_threads research_threads_created_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_threads
    ADD CONSTRAINT research_threads_created_session_id_fkey FOREIGN KEY (created_session_id) REFERENCES public.sessions(id);


--
-- Name: research_threads research_threads_last_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_threads
    ADD CONSTRAINT research_threads_last_session_id_fkey FOREIGN KEY (last_session_id) REFERENCES public.sessions(id);


--
-- Name: summary_lineage summary_lineage_content_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage
    ADD CONSTRAINT summary_lineage_content_item_id_fkey FOREIGN KEY (content_item_id) REFERENCES public.content_items(id);


--
-- Name: topic_models topic_models_corpus_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_models
    ADD CONSTRAINT topic_models_corpus_version_id_fkey FOREIGN KEY (corpus_version_id) REFERENCES public.corpus_versions(id);


--
-- Name: triage_assessments triage_assessments_content_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.triage_assessments
    ADD CONSTRAINT triage_assessments_content_item_id_fkey FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE CASCADE;


--
-- Name: x_api_requests x_api_requests_sync_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_api_requests
    ADD CONSTRAINT x_api_requests_sync_run_id_fkey FOREIGN KEY (sync_run_id) REFERENCES public.x_sync_runs(id) ON DELETE CASCADE;


--
-- Name: x_api_requests x_api_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_api_requests
    ADD CONSTRAINT x_api_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- Name: x_auto_sync_schedules x_auto_sync_schedules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_auto_sync_schedules
    ADD CONSTRAINT x_auto_sync_schedules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- Name: x_bookmark_folders x_bookmark_folders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_bookmark_folders
    ADD CONSTRAINT x_bookmark_folders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- Name: x_bookmarks_sync x_bookmarks_sync_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_bookmarks_sync
    ADD CONSTRAINT x_bookmarks_sync_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES public.x_bookmark_folders(x_folder_id) ON DELETE SET NULL;


--
-- Name: x_bookmarks_sync x_bookmarks_sync_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_bookmarks_sync
    ADD CONSTRAINT x_bookmarks_sync_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- Name: x_rate_limits x_rate_limits_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_rate_limits
    ADD CONSTRAINT x_rate_limits_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- Name: x_sync_runs x_sync_runs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.x_sync_runs
    ADD CONSTRAINT x_sync_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.x_oauth_tokens(user_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict CbjSDoC4JeqeKqMard6L7gvnisVL4Qv9YeePD5XWhs8gSnG5dOuZ58BmT97uf79


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20250102000001'),
    ('20251130000001'),
    ('20251130000002'),
    ('20251130000003'),
    ('20251130000004'),
    ('20251130000005'),
    ('20251130000006'),
    ('20251201000001'),
    ('20251201000002'),
    ('20251204000001'),
    ('20251204000002'),
    ('20251207000001'),
    ('20251208000001'),
    ('20251208000002'),
    ('20251210000001'),
    ('20251212000001'),
    ('20251212001000'),
    ('20251214000001'),
    ('20251214000002'),
    ('20251214000003'),
    ('20251215000001'),
    ('20251215000002'),
    ('20251217000001'),
    ('20251218000001'),
    ('20251221000001'),
    ('20251222000001'),
    ('20251222000002'),
    ('20251222000003'),
    ('20251222000004'),
    ('20251222000005'),
    ('20251223000001'),
    ('20251224000001'),
    ('20251225000001'),
    ('20251227000001'),
    ('20251228000001'),
    ('20251228000002'),
    ('20251229000001'),
    ('20251229000002'),
    ('20260102000002'),
    ('20260102000003'),
    ('20260103000001'),
    ('20260109000001'),
    ('20260109120000'),
    ('20260111000001'),
    ('20260111000002'),
    ('20260114000001'),
    ('20260114000002'),
    ('20260114000003'),
    ('20260115000001'),
    ('20260118000001'),
    ('20260119000001');
