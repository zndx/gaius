\restrict 4P643ORK22sRxExcPYBt85str14EPIdWFkKhklk6K7ExxYIuflXdt70l52Q3P8U

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
-- Name: pg_cron; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION pg_cron; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_cron IS 'Job scheduler for PostgreSQL';


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
    content text,
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
-- Name: COLUMN content_items.iceberg_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.iceberg_id IS 'UUID of record in Iceberg raw_content table';


--
-- Name: COLUMN content_items.iceberg_snapshot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.content_items.iceberg_snapshot_id IS 'Iceberg snapshot ID when content was written';


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
    metadata jsonb DEFAULT '{}'::jsonb
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
-- Name: activity_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_events ALTER COLUMN id SET DEFAULT nextval('public.activity_events_id_seq'::regclass);


--
-- Name: agent_evaluations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_evaluations ALTER COLUMN id SET DEFAULT nextval('public.agent_evaluations_id_seq'::regclass);


--
-- Name: cognition_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cognition_cycles ALTER COLUMN id SET DEFAULT nextval('public.cognition_cycles_id_seq'::regclass);


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
-- Name: held_out_queries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.held_out_queries ALTER COLUMN id SET DEFAULT nextval('public.held_out_queries_id_seq'::regclass);


--
-- Name: lineage_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lineage_events ALTER COLUMN id SET DEFAULT nextval('public.lineage_events_id_seq'::regclass);


--
-- Name: optimization_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.optimization_runs ALTER COLUMN id SET DEFAULT nextval('public.optimization_runs_id_seq'::regclass);


--
-- Name: profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles ALTER COLUMN id SET DEFAULT nextval('public.profiles_id_seq'::regclass);


--
-- Name: scheduled_tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks ALTER COLUMN id SET DEFAULT nextval('public.scheduled_tasks_id_seq'::regclass);


--
-- Name: summary_lineage id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.summary_lineage ALTER COLUMN id SET DEFAULT nextval('public.summary_lineage_id_seq'::regclass);


--
-- Name: user_interests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_interests ALTER COLUMN id SET DEFAULT nextval('public.user_interests_id_seq'::regclass);


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
-- Name: grid_points grid_points_snapshot_id_doc_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grid_points
    ADD CONSTRAINT grid_points_snapshot_id_doc_path_key UNIQUE (snapshot_id, doc_path);


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
-- Name: lineage_events lineage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lineage_events
    ADD CONSTRAINT lineage_events_pkey PRIMARY KEY (id);


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
-- Name: research_threads research_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_threads
    ADD CONSTRAINT research_threads_pkey PRIMARY KEY (id);


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
-- Name: idx_content_excluded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_excluded ON public.content_items USING btree (source_id, fetched_at DESC) WHERE (summary_excluded = true);


--
-- Name: idx_content_items_fetched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_content_items_fetched ON public.content_items USING btree (fetched_at DESC);


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
-- Name: idx_grid_points_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grid_points_position ON public.grid_points USING btree (snapshot_id, x, y);


--
-- Name: idx_grid_snapshots_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grid_snapshots_current ON public.grid_snapshots USING btree (kb_root, is_current) WHERE (is_current = true);


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

\unrestrict 4P643ORK22sRxExcPYBt85str14EPIdWFkKhklk6K7ExxYIuflXdt70l52Q3P8U


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
    ('20251208000001');
