-- migrate:up

-- Probe-efficacy ledger (Synth calibration pattern, DB-backed).
-- Every probe/timeout/heuristic/judge verdict is a FORECAST: a crisp
-- proposition with an implied P(true), stamped with the logical FSM
-- position of its call site and the epoch that produced it. Outcomes
-- arrive later as appended resolution events (gold = human, silver =
-- downstream objective verification). Brier scores accumulate per
-- (observer x call_site x momentum bucket x epoch). One ledger per
-- engine, single-writer by design: federated peers probe our public
-- surfaces and record what they see in THEIR OWN ledgers, never here.
-- Append-only is enforced by privilege: SELECT + INSERT only.

CREATE TABLE probe_forecasts (
    id BIGSERIAL PRIMARY KEY,
    forecast_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    observer TEXT NOT NULL,
    call_site TEXT NOT NULL,
    observer_kind TEXT NOT NULL CHECK (observer_kind IN
        ('probe','timeout','heuristic','watchdog','judge','theory','objective')),
    proposition TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','inconclusive','error')),
    p REAL NOT NULL CHECK (p >= 0 AND p <= 1),
    evidence JSONB NOT NULL DEFAULT '{}',
    side_effect TEXT,
    -- FSM position stamp (all nullable; stamped by the caller)
    task_class TEXT,
    task_id BIGINT,
    task_lifecycle TEXT,
    flow_type TEXT,
    flow_run_id TEXT,
    flow_step TEXT,
    endpoint TEXT,
    endpoint_state TEXT,
    admission_phase TEXT,
    momentum INT,
    -- epoch: scores never average across regime boundaries
    engine_rev TEXT NOT NULL,
    model_id TEXT,
    config_hash TEXT,
    elapsed_ms INT,
    resolves TEXT[],
    sequence_id UUID
);

COMMENT ON TABLE probe_forecasts IS
    'Probe-efficacy ledger: every probe/timeout/heuristic/judge verdict as a forecast, stamped with FSM position + epoch. Append-only (privilege-enforced). Outcomes land in probe_resolutions.';
COMMENT ON COLUMN probe_forecasts.observer IS
    'Namespaced observer id: probe:|timeout:|heuristic:|watchdog:|judge:|theory:|objective: prefix + stable name';
COMMENT ON COLUMN probe_forecasts.call_site IS
    'The FSM call site (module.function). One probe function, many call sites, one row each — scoring is (observer x call_site x momentum bucket).';
COMMENT ON COLUMN probe_forecasts.p IS
    'Implied P(proposition is TRUE). Default mapping VERDICT_P = pass:0.85 fail:0.15 inconclusive:0.50 error:0.50; mature probes pass explicit p.';
COMMENT ON COLUMN probe_forecasts.verdict IS
    'inconclusive = explicitly unmeasurable (Synth vacuous) — distinct from measured-negative. A timeout is inconclusive about the world plus a separate theory: row for what it IS evidence of.';
COMMENT ON COLUMN probe_forecasts.side_effect IS
    'What this verdict triggered: stop_endpoint|watchdog_reset|skip_remediation|spawn_failed|none|... Side-effect-bearing forecasts are the priority scoring targets.';
COMMENT ON COLUMN probe_forecasts.momentum IS
    'Raw corroboration count in scope at claim time (bucketed only at scoring time: cold 0 / warming 1-2 / rolling 3-9 / deep 10+).';
COMMENT ON COLUMN probe_forecasts.resolves IS
    'Proposition LIKE-patterns a PASS from this observer retroactively silver-resolves (downstream proof).';
COMMENT ON COLUMN probe_forecasts.sequence_id IS
    'Optional read-only link to healing_events.sequence_id. The ledger never writes healing_events.';

CREATE INDEX idx_probe_forecasts_observer ON probe_forecasts (observer, created_at DESC);
CREATE INDEX idx_probe_forecasts_created ON probe_forecasts (created_at DESC);
CREATE INDEX idx_probe_forecasts_sequence ON probe_forecasts (sequence_id)
    WHERE sequence_id IS NOT NULL;
CREATE INDEX idx_probe_forecasts_side_effect ON probe_forecasts (created_at DESC)
    WHERE side_effect IS NOT NULL;
CREATE INDEX idx_probe_forecasts_proposition ON probe_forecasts (proposition text_pattern_ops);

CREATE TABLE probe_resolutions (
    id BIGSERIAL PRIMARY KEY,
    forecast_id UUID NOT NULL REFERENCES probe_forecasts(forecast_id),
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome BOOLEAN NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('gold','silver')),
    resolver TEXT NOT NULL,
    note TEXT
);

COMMENT ON TABLE probe_resolutions IS
    'Outcome events for probe_forecasts. Corrections are APPENDED rows (latest resolved_at wins at read) — belief revisions are themselves history, never mutations.';
COMMENT ON COLUMN probe_resolutions.tier IS
    'gold = human attestation (CLI /efficacy resolve); silver = downstream objective verification or self-resolution.';
COMMENT ON COLUMN probe_resolutions.resolver IS
    'Free-text provenance of the ground truth (e.g. self-recovered-noaction, freshness-3way:kv-missing-card_x, human:rch). The most valuable column — keep it descriptive.';

CREATE INDEX idx_probe_resolutions_forecast ON probe_resolutions (forecast_id, resolved_at DESC);

-- FSM transitions (v1 minimal): appended when a stamping call observes a
-- position change for a scope. p_prior reserved for the future Markov
-- predictor (the model as a scored forecaster) — NULL in v1.
CREATE TABLE fsm_transitions (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scope TEXT NOT NULL,
    from_position JSONB,
    to_position JSONB NOT NULL,
    trigger TEXT,
    p_prior REAL
);

COMMENT ON TABLE fsm_transitions IS
    'Observed Gaius FSM transitions per scope (endpoint:thinking, task:publish_cards, ...). p_prior reserved for the Dirichlet transition model (deferred).';

CREATE INDEX idx_fsm_transitions_scope ON fsm_transitions (scope, created_at DESC);

GRANT SELECT, INSERT ON probe_forecasts TO gaius;
GRANT USAGE, SELECT ON SEQUENCE probe_forecasts_id_seq TO gaius;
GRANT SELECT, INSERT ON probe_resolutions TO gaius;
GRANT USAGE, SELECT ON SEQUENCE probe_resolutions_id_seq TO gaius;
GRANT SELECT, INSERT ON fsm_transitions TO gaius;
GRANT USAGE, SELECT ON SEQUENCE fsm_transitions_id_seq TO gaius;

-- FMEA rows for the Phase-0 truth-repair failure modes (house rule:
-- every new failure mode gets a catalog row). Scores are honest, not
-- steering: severity from public-surface impact, occurrence from the
-- 2026-09-01 audit evidence, detection reflects the NEW (post-repair)
-- detectability — each of these was previously undetectable by design
-- (permanently-green check, default-to-success parse, frozen sequence).
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('COL_017', 'collections', 'Card KV Sync Divergence',
 'Card published in DB but its KV page absent — public site stale while the publish task reported success; non-atomic DB/KV write, per-card failures previously discarded (#COL.00000017.CARDKVFAIL)',
 6, 4, 3, 'task_error', ARRAY['retry_card_sync', 'freshness_3way_objective', 'publish_sync_cli'], 1),
('HO_003', 'health', 'ACP Verdict Inconclusive',
 'ACP remediation response had no recognizable outcome indicator; previously defaulted to SUCCESS (the "Remediation succeeded (RCA: None)" mechanism) — now fail-closed (#HO.00000003.ACPINCONCLUSIVE)',
 5, 4, 2, 'log_scan', ARRAY['fail_closed_not_success', 'escalate_tier', 'score_judge_forecast'], 2),
('HO_004', 'health', 'Recovering Incident Check Absent',
 'Incident stuck in recovering while its originating check vanished from reports — sequence frozen forever, neither resolved nor escalated (#HO.00000004.CHECKABSENT)',
 4, 3, 4, 'health_check', ARRAY['resolve_check_absent', 'audit_check_registry'], 1)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    detection_method = EXCLUDED.detection_method,
    recommended_actions = EXCLUDED.recommended_actions,
    escalation_tier = EXCLUDED.escalation_tier,
    updated_at = NOW();

-- migrate:down

DELETE FROM fmea_catalog WHERE failure_mode_id IN ('COL_017', 'HO_003', 'HO_004');
DROP TABLE IF EXISTS fsm_transitions;
DROP TABLE IF EXISTS probe_resolutions;
DROP TABLE IF EXISTS probe_forecasts;
