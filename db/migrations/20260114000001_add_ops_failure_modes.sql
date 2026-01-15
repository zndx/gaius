-- migrate:up

-- Operations Failure Modes (OPS) for heartbeat/progress anomaly detection
-- These track long-running operation anomalies detected via OTel heartbeats

INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('OPS_001', 'operations', 'Heartbeat Anomaly', 'Operation duration exceeds statistical baseline (Z > threshold)', 5, 4, 2, 'metric_threshold', ARRAY['investigate_operation', 'check_resource_contention', 'restart_if_stuck'], 0),
('OPS_002', 'operations', 'Missing Heartbeat', 'Expected heartbeat not received within interval', 6, 3, 3, 'health_check', ARRAY['check_process_health', 'restart_operation', 'investigate_hang'], 1),
('OPS_003', 'operations', 'Progress Stall', 'ResearchFlow progress not advancing for extended period', 5, 4, 3, 'metric_threshold', ARRAY['check_dependencies', 'restart_flow', 'investigate_deadlock'], 0)
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

DELETE FROM fmea_catalog WHERE failure_mode_id LIKE 'OPS_%';
