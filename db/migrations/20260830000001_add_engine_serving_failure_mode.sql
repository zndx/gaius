-- migrate:up

-- Engine Serving Desync (INFRA_005) — the gaius-engine gRPC :50051 is dead or
-- wedged while devenv process-compose still reports the process "ready" (the
-- 2026-08-29 outage class). This is a PFMEA (process/runtime) failure mode. It is
-- detected OUT-OF-BAND by the gaius-engine-ready watchdog (scripts/engine-ready.sh)
-- — an in-engine observer cannot see it because it dies with the engine (a DFMEA
-- design finding, addressed by moving L0 detection out-of-band). Guru:
-- #EN.00000017.SERVEDESYNC.
--
-- Scores are HONEST — not distorted to steer a runtime tier. FMEA is the risk
-- discipline; it is decoupled from the SRE escalation ladder:
--   S=9  near-total product outage (every client — waterfall, CLI, MCP — fails)
--   O=3  uncommon (one benign occurrence, 2026-08-29; a benign uv-run venv churn)
--   D=5  moderate — previously SILENT (process-compose masked it) but now reliably
--        detected by the out-of-band watchdog + a real Engine/Status self-probe.
-- RPN = 135. The runtime escalation to ACP is driven by "deterministic recovery
-- exhausted" (the watchdog's recycle-budget breaker), NOT by this RPN — hence the
-- recommended escalation_tier=2 (agent root-cause) despite the RPN band.
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('INFRA_005', 'infra', 'Engine Serving Desync', 'gRPC :50051 dead or wedged while process-compose reports ready; out-of-band deterministic recycle budget exhausted (recurrence)', 9, 3, 5, 'health_check', ARRAY['restart_engine_unit', 'acp_root_cause', 'check_venv_churn', 'check_process_compose_daemon'], 2)
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

DELETE FROM fmea_catalog WHERE failure_mode_id = 'INFRA_005';
