-- migrate:up
-- Resident Nautilus (2026-09-04, user decision): the deterministic supervisor runs
-- OUT of process beside the engine, dials the engine's EngineSupervision stream,
-- and keeps its own records in the tiered store (Kudu tier0 through this
-- database's impala_fdw foreign tables) behind a write-ahead journal on object
-- storage. What lives in THIS Postgres is only the contract the engine reads
-- (nautilus.supervisor_status) and the shared-ledger appends the supervision spec
-- §6 sanctions. Privilege is the invariant: the supervisor can READ the mechanics
-- tables and APPEND forecasts, but has no UPDATE on scheduled_tasks — reclaiming an
-- orphaned claim is a DIRECTIVE the engine executes after re-checking progress, so
-- the supervisor never kills (progress-over-timeouts).
--
-- Role creation may be refused in a devenv where the migration role lacks
-- CREATEROLE; the fallback is documented: Nautilus connects as `gaius`.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nautilus') THEN
    BEGIN
      CREATE ROLE nautilus LOGIN PASSWORD 'nautilus';
    EXCEPTION WHEN insufficient_privilege THEN
      RAISE NOTICE 'nautilus role not created (insufficient privilege) — Nautilus connects as gaius';
    END;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS nautilus;
COMMENT ON SCHEMA nautilus IS
  'Resident Nautilus supervisor contract rows. The supervisor writes; the engine reads. '
  'Product rows (backlog cells, supervisor events, positions) are NOT here — they are '
  'Kudu tier0 via the impala_fdw foreign tables nautilus_*_tier0 (THS pattern).';

CREATE TABLE IF NOT EXISTS nautilus.supervisor_status (
    project        TEXT PRIMARY KEY,
    epoch          TEXT NOT NULL,
    spec_loaded_at TIMESTAMPTZ NOT NULL,
    status         JSONB NOT NULL,
    filled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE nautilus.supervisor_status IS
  'Nautilus upserts its SupervisorStatus (processes[], armed[], breaker, buffered_records, '
  'engine_connected, last_tick) each poll. /nautilus status answers from this row and reports '
  'its staleness (#SV.00000011.NOSUPERVISOR when filled_at is older than 2x the poll).';

GRANT USAGE ON SCHEMA nautilus TO gaius;
GRANT SELECT ON ALL TABLES IN SCHEMA nautilus TO gaius;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nautilus') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA nautilus TO nautilus';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON nautilus.supervisor_status TO nautilus';
    -- observation (read) of the mechanics the supervision spec lets it derive from
    EXECUTE 'GRANT SELECT ON scheduled_tasks, objective_verifications, healing_events, '
            'overwatch_events, probe_forecasts, probe_resolutions, fsm_transitions TO nautilus';
    -- the shared ledger (spec §6): append only, never update
    EXECUTE 'GRANT INSERT ON probe_forecasts, probe_resolutions, fsm_transitions TO nautilus';
    EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE probe_forecasts_id_seq, probe_resolutions_id_seq, '
            'fsm_transitions_id_seq TO nautilus';
    EXECUTE 'GRANT USAGE ON SCHEMA cron TO nautilus';
    EXECUTE 'GRANT SELECT ON cron.job, cron.job_run_details TO nautilus';
  END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS nautilus.supervisor_status;
DROP SCHEMA IF EXISTS nautilus;
-- the role is left in place (dropping a LOGIN role is an operator action)
