-- Two-hour Gaius workload window: CLT in-line with extract, admit, label, curate.
-- Source=workload-window. Cognition/scheduled_task_processor picks these up.
-- thinking must be HEALTHY before the first clt_skos_label (T+25).

INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for) VALUES
('feature_probe',     '{"gpu_index":4}'::jsonb, 'workload-window', NOW() + interval '5 minutes'),
('clt_skos_admit',    '{}'::jsonb,              'workload-window', NOW() + interval '15 minutes'),
('clt_skos_label',    '{}'::jsonb,              'workload-window', NOW() + interval '28 minutes'),
('article_curate',    '{}'::jsonb,              'workload-window', NOW() + interval '40 minutes'),
('feature_probe',     '{"gpu_index":4}'::jsonb, 'workload-window', NOW() + interval '52 minutes'),
('clt_skos_admit',    '{}'::jsonb,              'workload-window', NOW() + interval '65 minutes'),
('clt_skos_label',    '{}'::jsonb,              'workload-window', NOW() + interval '78 minutes'),
('knowledge_summary', '{}'::jsonb,              'workload-window', NOW() + interval '92 minutes'),
('clt_skos_label',    '{}'::jsonb,              'workload-window', NOW() + interval '105 minutes'),
('feature_probe',     '{"gpu_index":4}'::jsonb, 'workload-window', NOW() + interval '115 minutes');
