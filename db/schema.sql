\restrict ZxSmj0ECBdNOLeW0QN7iMvnpZGg57DL3hfjfreV1gu7oQZqxmU0hfAdAKblEY1Z

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
-- Name: age; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS age WITH SCHEMA ag_catalog;


--
-- Name: EXTENSION age; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION age IS 'AGE database extension';


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
    last_remediation_at timestamp with time zone
);


--
-- Name: TABLE health_loop_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.health_loop_state IS 'Persistent state for autonomous health loop';


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
-- Name: daily_eval_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_eval_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_eval_summaries_id_seq'::regclass);


--
-- Name: daily_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_summaries_id_seq'::regclass);


--
-- Name: engine_observations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations ALTER COLUMN id SET DEFAULT nextval('public.engine_observations_id_seq'::regclass);


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
-- Name: optimization_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs ALTER COLUMN id SET DEFAULT nextval('public.optimization_runs_id_seq'::regclass);


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
-- Name: state_changes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_changes ALTER COLUMN id SET DEFAULT nextval('public.state_changes_id_seq'::regclass);


--
-- Name: summary_lineage id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage ALTER COLUMN id SET DEFAULT nextval('public.summary_lineage_id_seq'::regclass);


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
-- Name: command_history command_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_pkey PRIMARY KEY (id);


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
-- Name: engine_observations engine_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations
    ADD CONSTRAINT engine_observations_pkey PRIMARY KEY (id);


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
-- Name: lineage_events lineage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lineage_events
    ADD CONSTRAINT lineage_events_pkey PRIMARY KEY (id);


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
-- Name: optimization_runs optimization_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs
    ADD CONSTRAINT optimization_runs_pkey PRIMARY KEY (id);


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
-- Name: remediation_approvals remediation_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remediation_approvals
    ADD CONSTRAINT remediation_approvals_pkey PRIMARY KEY (id);


--
-- Name: research_threads research_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_threads
    ADD CONSTRAINT research_threads_pkey PRIMARY KEY (id);


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
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


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
-- Name: ui_preferences ui_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ui_preferences
    ADD CONSTRAINT ui_preferences_pkey PRIMARY KEY (client_id);


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
-- Name: idx_approvals_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_event ON public.remediation_approvals USING btree (event_type, event_id);


--
-- Name: idx_approvals_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_pending ON public.remediation_approvals USING btree (status, expires_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_command_history_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_command_history_client ON public.command_history USING btree (client_id, executed_at DESC);


--
-- Name: idx_command_history_kb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_command_history_kb ON public.command_history USING btree (kb_root, executed_at DESC);


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
-- Name: idx_cycles_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cycles_recent ON public.cognition_cycles USING btree (profile_name, started_at DESC);


--
-- Name: idx_daily_summaries_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_summaries_date ON public.daily_summaries USING btree (summary_date DESC);


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
-- Name: idx_profile_content_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_content_score ON public.profile_content USING btree (profile_id, relevance_score DESC);


--
-- Name: idx_profiles_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_name ON public.profiles USING btree (name);


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
-- Name: idx_sessions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_profile ON public.sessions USING btree (profile_name, started_at DESC);


--
-- Name: idx_sessions_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_recent ON public.sessions USING btree (started_at DESC) WHERE (ended_at IS NOT NULL);


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
-- Name: engine_observations engine_observations_related_thought_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.engine_observations
    ADD CONSTRAINT engine_observations_related_thought_id_fkey FOREIGN KEY (related_thought_id) REFERENCES public.cognition_thoughts(id);


--
-- Name: fetch_jobs fetch_jobs_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs
    ADD CONSTRAINT fetch_jobs_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE CASCADE;


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
-- Name: optimization_runs optimization_runs_best_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs
    ADD CONSTRAINT optimization_runs_best_version_id_fkey FOREIGN KEY (best_version_id) REFERENCES public.agent_versions(version_id);


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
-- PostgreSQL database dump complete
--

\unrestrict ZxSmj0ECBdNOLeW0QN7iMvnpZGg57DL3hfjfreV1gu7oQZqxmU0hfAdAKblEY1Z


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
    ('20251215000001');
