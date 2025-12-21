\restrict bAOURaATvSdqMaH9BRqQgbWRx3wqAzXz6gcU41o73uZAf29GBiexKRXqxo6y7Gf

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
    metadata jsonb DEFAULT '{}'::jsonb
);


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
-- Name: sync_watermarks; Type: TABLE; Schema: meta; Owner: -
--

CREATE TABLE meta.sync_watermarks (
    sync_type text NOT NULL,
    last_sync_at timestamp with time zone,
    last_event_id bigint,
    records_synced integer DEFAULT 0
);


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
    exclusion_reason text
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
    updated_at timestamp with time zone DEFAULT now()
);


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
-- Name: search_index__xbo2_cawqvv61fpn_ortu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.search_index__xbo2_cawqvv61fpn_ortu (
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
-- Name: search_index__xbo2_cawqvv61fpn_ortu_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.search_index__xbo2_cawqvv61fpn_ortu ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.search_index__xbo2_cawqvv61fpn_ortu_id_seq
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
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE ui_preferences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ui_preferences IS 'Per-client UI state. TUI/CLI/MCP each have their own preferences.';


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
-- Name: data_dependencies id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.data_dependencies ALTER COLUMN id SET DEFAULT nextval('meta.data_dependencies_id_seq'::regclass);


--
-- Name: document_clusters id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.document_clusters ALTER COLUMN id SET DEFAULT nextval('meta.document_clusters_id_seq'::regclass);


--
-- Name: nifi_flows id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.nifi_flows ALTER COLUMN id SET DEFAULT nextval('meta.nifi_flows_id_seq'::regclass);


--
-- Name: semantic_regions region_id; Type: DEFAULT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_regions ALTER COLUMN region_id SET DEFAULT nextval('meta.semantic_regions_region_id_seq'::regclass);


--
-- Name: activity_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_events ALTER COLUMN id SET DEFAULT nextval('public.activity_events_id_seq'::regclass);


--
-- Name: agent_evaluations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_evaluations ALTER COLUMN id SET DEFAULT nextval('public.agent_evaluations_id_seq'::regclass);


--
-- Name: aiops_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aiops_events ALTER COLUMN id SET DEFAULT nextval('public.aiops_events_id_seq'::regclass);


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
-- Name: profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles ALTER COLUMN id SET DEFAULT nextval('public.profiles_id_seq'::regclass);


--
-- Name: remediation_approvals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remediation_approvals ALTER COLUMN id SET DEFAULT nextval('public.remediation_approvals_id_seq'::regclass);


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
-- Name: topic_models id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic_models ALTER COLUMN id SET DEFAULT nextval('public.topic_models_id_seq'::regclass);


--
-- Name: user_interests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_interests ALTER COLUMN id SET DEFAULT nextval('public.user_interests_id_seq'::regclass);


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
-- Name: flow_runs flow_runs_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.flow_runs
    ADD CONSTRAINT flow_runs_pkey PRIMARY KEY (run_id);


--
-- Name: gpu_utilization gpu_utilization_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.gpu_utilization
    ADD CONSTRAINT gpu_utilization_pkey PRIMARY KEY ("timestamp", gpu_index);


--
-- Name: inference_throughput inference_throughput_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.inference_throughput
    ADD CONSTRAINT inference_throughput_pkey PRIMARY KEY (hour, model);


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
-- Name: semantic_regions semantic_regions_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.semantic_regions
    ADD CONSTRAINT semantic_regions_pkey PRIMARY KEY (region_id);


--
-- Name: sync_watermarks sync_watermarks_pkey; Type: CONSTRAINT; Schema: meta; Owner: -
--

ALTER TABLE ONLY meta.sync_watermarks
    ADD CONSTRAINT sync_watermarks_pkey PRIMARY KEY (sync_type);


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
-- Name: search_index__xbo2_cawqvv61fpn_ortu search_index__xbo2_cawqvv61fpn_ortu_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index__xbo2_cawqvv61fpn_ortu
    ADD CONSTRAINT search_index__xbo2_cawqvv61fpn_ortu_pkey PRIMARY KEY (id);


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
-- Name: idx_meta_agent_perf_date; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_agent_perf_date ON meta.agent_performance USING btree (date DESC);


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
-- Name: idx_meta_flow_runs_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_runs_status ON meta.flow_runs USING btree (status);


--
-- Name: idx_meta_flow_runs_type; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_flow_runs_type ON meta.flow_runs USING btree (flow_type, started_at DESC);


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
-- Name: idx_meta_nifi_flows_status; Type: INDEX; Schema: meta; Owner: -
--

CREATE INDEX idx_meta_nifi_flows_status ON meta.nifi_flows USING btree (status);


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
-- Name: idx_routing_mismatch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_mismatch ON public.routing_decisions USING btree (capability_mismatch) WHERE capability_mismatch;


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
-- Name: search_index__xbo2_cawqvv61fpn_ortu_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__xbo2_cawqvv61fpn_ortu_archived_idx ON public.search_index__xbo2_cawqvv61fpn_ortu USING btree (archived);


--
-- Name: search_index__xbo2_cawqvv61fpn_ortu_identity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX search_index__xbo2_cawqvv61fpn_ortu_identity_idx ON public.search_index__xbo2_cawqvv61fpn_ortu USING btree (model, model_id);


--
-- Name: search_index__xbo2_cawqvv61fpn_ortu_model_archived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__xbo2_cawqvv61fpn_ortu_model_archived_idx ON public.search_index__xbo2_cawqvv61fpn_ortu USING btree (model, archived);


--
-- Name: search_index__xbo2_cawqvv61fpn_ortu_native_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__xbo2_cawqvv61fpn_ortu_native_tsvector_idx ON public.search_index__xbo2_cawqvv61fpn_ortu USING gin (with_native_query_vector);


--
-- Name: search_index__xbo2_cawqvv61fpn_ortu_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_index__xbo2_cawqvv61fpn_ortu_tsvector_idx ON public.search_index__xbo2_cawqvv61fpn_ortu USING gin (search_vector);


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
-- Name: profiles profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER profiles_updated_at BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: evolution_calibrations trg_update_calibration_summary; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_update_calibration_summary AFTER INSERT ON public.evolution_calibrations FOR EACH ROW EXECUTE FUNCTION public.update_calibration_summary();


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
-- PostgreSQL database dump complete
--

\unrestrict bAOURaATvSdqMaH9BRqQgbWRx3wqAzXz6gcU41o73uZAf29GBiexKRXqxo6y7Gf


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
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
    ('20251221000001');
