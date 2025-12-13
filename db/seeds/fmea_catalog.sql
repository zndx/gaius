-- FMEA Failure Mode Catalog Seed Data
-- 30 failure modes across 7 categories

-- GPU Failures (6 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('GPU_001', 'gpu', 'GPU Memory Exhaustion', 'GPU VRAM completely consumed, causing OOM errors', 8, 6, 4, 'health_check', ARRAY['restart_endpoint', 'reduce_batch_size', 'clear_cuda_cache'], 1),
('GPU_002', 'gpu', 'GPU Temperature Critical', 'GPU temperature exceeds safe operating threshold (>85C)', 9, 3, 2, 'metric_threshold', ARRAY['reduce_load', 'increase_cooling', 'throttle_requests'], 0),
('GPU_003', 'gpu', 'GPU Hardware Error', 'Hardware failure detected via nvidia-smi or CUDA errors', 10, 2, 3, 'health_check', ARRAY['failover_routing', 'disable_gpu', 'alert_operator'], 2),
('GPU_004', 'gpu', 'GPU Driver Crash', 'NVIDIA driver crash requiring system intervention', 8, 3, 4, 'health_check', ARRAY['cold_restart', 'driver_reload'], 2),
('GPU_005', 'gpu', 'GPU Memory Fragmentation', 'Free VRAM available but allocation fails due to fragmentation', 7, 5, 4, 'metric_threshold', ARRAY['cold_restart', 'clear_cuda_cache'], 1),
('GPU_006', 'gpu', 'GPU Power Throttling', 'GPU power limited affecting performance', 5, 4, 3, 'metric_threshold', ARRAY['reduce_batch_size', 'adjust_power_limit'], 0)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- vLLM Endpoint Failures (6 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('VLLM_001', 'vllm', 'Endpoint Stuck Starting', 'vLLM endpoint stuck in STARTING state for >5 minutes', 6, 5, 5, 'health_check', ARRAY['force_restart', 'kill_process'], 0),
('VLLM_002', 'vllm', 'Endpoint Stuck Stopping', 'vLLM endpoint stuck in STOPPING state for >2 minutes', 4, 4, 4, 'health_check', ARRAY['force_kill', 'pkill_process'], 0),
('VLLM_003', 'vllm', 'Health Check Failure', 'Endpoint health check returning non-200 status', 7, 6, 3, 'health_check', ARRAY['restart_endpoint', 'check_dependencies'], 0),
('VLLM_004', 'vllm', 'Orphan Process', 'vLLM process running without management', 5, 5, 4, 'health_check', ARRAY['kill_orphan', 'reconcile_state'], 0),
('VLLM_005', 'vllm', 'OOM Crash', 'Endpoint crashed due to out-of-memory error', 8, 5, 3, 'health_check', ARRAY['restart_reduced_memory', 'reduce_batch_size', 'cold_restart'], 1),
('VLLM_006', 'vllm', 'KV-Cache Exhaustion', 'KV-cache full causing request rejections', 5, 6, 5, 'metric_threshold', ARRAY['restart_endpoint', 'increase_kv_cache', 'reduce_max_seq'], 0)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- Model Quality Failures (5 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('MQ_001', 'model_quality', 'Hallucination Increase', 'Model producing factually incorrect outputs at elevated rate', 7, 4, 6, 'metric_threshold', ARRAY['rollback_version', 'retrain', 'increase_temperature'], 2),
('MQ_002', 'model_quality', 'Latency Degradation', 'Response times significantly above baseline', 4, 5, 3, 'metric_threshold', ARRAY['restart_endpoint', 'optimize_kv_cache', 'reduce_batch_size'], 0),
('MQ_003', 'model_quality', 'Output Quality Drift', 'Gradual degradation in output quality metrics', 5, 6, 7, 'anomaly', ARRAY['trigger_evolution', 'rollback', 'refresh_training_data'], 1),
('MQ_004', 'model_quality', 'Semantic Drift', 'Embedding space drifting from domain anchors', 6, 4, 8, 'anomaly', ARRAY['reanchor_embeddings', 'retrain_domain'], 2),
('MQ_005', 'model_quality', 'Context Exhaustion', 'Model hitting context window limits frequently', 6, 5, 4, 'metric_threshold', ARRAY['chunk_context', 'summarize_history', 'upgrade_model'], 0)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- Evolution System Failures (5 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('EV_001', 'evolution', 'Training Divergence', 'Evolution cycle producing worse performance', 8, 4, 3, 'metric_threshold', ARRAY['reject_version', 'rollback', 'reduce_learning_rate'], 1),
('EV_002', 'evolution', 'Held-out Score Drop', 'Performance on held-out queries declining', 6, 5, 4, 'metric_threshold', ARRAY['pause_evolution', 'analyze_drift', 'refresh_held_out'], 1),
('EV_003', 'evolution', 'Version Conflict', 'Multiple agent versions competing for activation', 5, 3, 5, 'health_check', ARRAY['resolve_conflict', 'force_version'], 0),
('EV_004', 'evolution', 'Optimization Loop', 'Evolution cycling without improvement', 4, 3, 6, 'metric_threshold', ARRAY['pause_evolution', 'increase_diversity'], 0),
('EV_005', 'evolution', 'Training Data Staleness', 'Training examples becoming outdated', 7, 6, 5, 'anomaly', ARRAY['refresh_examples', 'trigger_ideation'], 1)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- Emergent Behavior Failures (4 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('EB_001', 'emergent', 'Swarm Consensus Failure', 'Multi-agent swarm failing to reach consensus', 6, 4, 6, 'health_check', ARRAY['retry_swarm', 'reduce_agents', 'increase_timeout'], 0),
('EB_002', 'emergent', 'Cognition Loop', 'Self-observation generating recursive thought chains', 5, 4, 7, 'metric_threshold', ARRAY['inject_stimulus', 'reset_cognition', 'force_novelty'], 1),
('EB_003', 'emergent', 'Embedding Drift', 'Grid projection embeddings drifting over time', 6, 5, 8, 'anomaly', ARRAY['recompute_embeddings', 'recalibrate_grid'], 1),
('EB_004', 'emergent', 'Self-Observation Bias', 'Thoughts becoming increasingly self-referential', 6, 5, 9, 'anomaly', ARRAY['inject_external', 'reset_thought_history', 'diversity_boost'], 2)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- Resource Contention Failures (4 modes)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('RC_001', 'resource', 'Scheduler Queue Starvation', 'Job queue depth exceeding capacity', 6, 4, 4, 'metric_threshold', ARRAY['scale_workers', 'prioritize_queue', 'reject_low_priority'], 0),
('RC_002', 'resource', 'Batch Fairness Violation', 'Some requests receiving disproportionate resources', 4, 5, 5, 'metric_threshold', ARRAY['rebalance_batches', 'enforce_quotas'], 0),
('RC_003', 'resource', 'XAI Budget Exhausted', 'External AI API budget depleted', 5, 5, 2, 'metric_threshold', ARRAY['fallback_local', 'pause_evaluations', 'alert_operator'], 0),
('RC_004', 'resource', 'DB Connection Pool', 'Database connection pool exhausted', 7, 4, 3, 'health_check', ARRAY['restart_pool', 'increase_connections', 'optimize_queries'], 1)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();

-- Infrastructure Failures (4 modes - new category for completeness)
INSERT INTO fmea_catalog (failure_mode_id, category, name, description, base_severity, base_occurrence, base_detection, detection_method, recommended_actions, escalation_tier) VALUES
('INFRA_001', 'infra', 'gRPC Connection Failure', 'Engine gRPC connection unavailable', 8, 4, 3, 'health_check', ARRAY['restart_engine', 'check_network', 'failover'], 1),
('INFRA_002', 'infra', 'PostgreSQL Unavailable', 'Database connection failed', 9, 3, 2, 'health_check', ARRAY['restart_postgres', 'check_disk', 'failover_replica'], 2),
('INFRA_003', 'infra', 'Qdrant Unavailable', 'Vector database connection failed', 7, 3, 3, 'health_check', ARRAY['restart_qdrant', 'check_memory'], 1),
('INFRA_004', 'infra', 'MinIO Unavailable', 'Object storage connection failed', 6, 3, 3, 'health_check', ARRAY['restart_minio', 'check_disk'], 1)
ON CONFLICT (failure_mode_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    base_severity = EXCLUDED.base_severity,
    base_occurrence = EXCLUDED.base_occurrence,
    base_detection = EXCLUDED.base_detection,
    updated_at = NOW();
