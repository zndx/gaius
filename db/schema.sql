\restrict pA15IWjC9GHlajlodLPRYDRE1gHkeQVG2f2EkZbzoct6PVuMi3TiLhxaBclTr4L

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
    'shutdown'
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


SET default_tablespace = '';

SET default_table_access_method = heap;

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
    embedding_id text
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
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


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
-- Name: content_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items ALTER COLUMN id SET DEFAULT nextval('public.content_items_id_seq'::regclass);


--
-- Name: daily_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_summaries ALTER COLUMN id SET DEFAULT nextval('public.daily_summaries_id_seq'::regclass);


--
-- Name: feed_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feed_sources ALTER COLUMN id SET DEFAULT nextval('public.feed_sources_id_seq'::regclass);


--
-- Name: fetch_jobs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs ALTER COLUMN id SET DEFAULT nextval('public.fetch_jobs_id_seq'::regclass);


--
-- Name: profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles ALTER COLUMN id SET DEFAULT nextval('public.profiles_id_seq'::regclass);


--
-- Name: activity_events activity_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_events
    ADD CONSTRAINT activity_events_pkey PRIMARY KEY (id);


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
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


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
-- Name: idx_daily_summaries_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_summaries_date ON public.daily_summaries USING btree (summary_date DESC);


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
-- Name: idx_profile_content_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_content_score ON public.profile_content USING btree (profile_id, relevance_score DESC);


--
-- Name: idx_profiles_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_name ON public.profiles USING btree (name);


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
-- Name: content_items content_items_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE SET NULL;


--
-- Name: fetch_jobs fetch_jobs_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_jobs
    ADD CONSTRAINT fetch_jobs_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.feed_sources(id) ON DELETE CASCADE;


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
-- PostgreSQL database dump complete
--

\unrestrict pA15IWjC9GHlajlodLPRYDRE1gHkeQVG2f2EkZbzoct6PVuMi3TiLhxaBclTr4L


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20251130000001'),
    ('20251130000002'),
    ('20251130000003'),
    ('20251130000004'),
    ('20251130000005');
