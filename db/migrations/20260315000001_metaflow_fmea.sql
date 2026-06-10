-- migrate:up

-- Metaflow Pipeline Stack Failures (4 modes)
-- These cover the full pg_cron → NOTIFY → engine → Metaflow → K8s chain
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('MF_001', 'metaflow', 'Metaflow Service Unreachable', 'Metaflow service HTTP endpoint not responding — K8s pods down or port-forward broken', 7, 4, 3, 'health_check', ARRAY['restart_port_forward', 'check_k8s_pods', 'restart_service'], 1),
('MF_002', 'metaflow', 'Flow Execution Failure', 'Metaflow flows start but fail — missing deps, timeout, or K8s resource issues', 6, 5, 4, 'health_check', ARRAY['check_flow_logs', 'restart_flow', 'check_k8s_resources'], 1),
('MF_003', 'metaflow', 'Full Stack Disconnection', 'K8s cluster unreachable — no flows can run, entire pipeline chain broken', 9, 3, 6, 'health_check', ARRAY['check_k8s_cluster', 'restart_rke2', 'check_network', 'alert_operator'], 2),
('MF_004', 'metaflow', 'K8s DNS Resolution Failure', 'CoreDNS CrashLoopBackOff — pods cannot resolve service names, blocking all K8s-dependent services', 9, 2, 7, 'health_check', ARRAY['check_coredns_pods', 'restart_coredns', 'check_resolv_conf', 'alert_operator'], 2)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- migrate:down

DELETE FROM fmea_catalog WHERE failure_mode_id LIKE 'MF_%';
