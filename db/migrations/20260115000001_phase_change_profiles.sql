-- migrate:up
-- Phase Change Profiles for Resilient Dynamic Workload Coordination
--
-- Accumulates timing statistics for phase change transitions (e.g., ColNomic load,
-- instruct restore). Statistical power requires ~70 samples (~1 week at 10 changes/day)
-- before enabling threshold-based decision support interventions.
--
-- Design Philosophy: "Premature performance optimization is the root of all evil."
-- The system prioritizes resilience over speed by deferring interventions until
-- sufficient baseline data is collected.

CREATE TABLE IF NOT EXISTS meta.phase_change_profiles (
    change_type TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL DEFAULT 0,
    total_duration_ms BIGINT NOT NULL DEFAULT 0,
    min_duration_ms INTEGER,
    max_duration_ms INTEGER,
    failures INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE meta.phase_change_profiles IS
    'Accumulated phase change timing statistics for decision support. '
    'Requires ~70 samples (~1 week baseline) before enabling threshold-based interventions.';

COMMENT ON COLUMN meta.phase_change_profiles.change_type IS
    'Phase change type: colnomic_load, instruct_restore, reasoning_load, baseline_restore';

COMMENT ON COLUMN meta.phase_change_profiles.sample_count IS
    'Number of successful convergences';

COMMENT ON COLUMN meta.phase_change_profiles.total_duration_ms IS
    'Sum of all convergence durations in milliseconds';

COMMENT ON COLUMN meta.phase_change_profiles.min_duration_ms IS
    'Fastest recorded convergence in milliseconds';

COMMENT ON COLUMN meta.phase_change_profiles.max_duration_ms IS
    'Slowest recorded convergence in milliseconds';

COMMENT ON COLUMN meta.phase_change_profiles.failures IS
    'Count of failed phase change attempts';

-- Create view for easy profile inspection
CREATE OR REPLACE VIEW meta.v_phase_change_stats AS
SELECT
    change_type,
    sample_count,
    failures,
    CASE WHEN sample_count > 0
        THEN round((total_duration_ms::NUMERIC / sample_count), 1)
        ELSE NULL
    END AS avg_duration_ms,
    min_duration_ms,
    max_duration_ms,
    CASE WHEN (sample_count + failures) > 0
        THEN round((failures::NUMERIC / (sample_count + failures)) * 100, 2)
        ELSE 0
    END AS failure_rate_pct,
    sample_count >= 70 AS has_statistical_power,
    updated_at
FROM meta.phase_change_profiles
ORDER BY change_type;

COMMENT ON VIEW meta.v_phase_change_stats IS
    'Phase change profiles with computed statistics. '
    'has_statistical_power indicates whether sufficient samples exist for decision support.';

-- Seed initial profiles for all change types
INSERT INTO meta.phase_change_profiles (change_type, sample_count, total_duration_ms, failures, updated_at)
VALUES
    ('colnomic_load', 0, 0, 0, NOW()),
    ('instruct_restore', 0, 0, 0, NOW()),
    ('reasoning_load', 0, 0, 0, NOW()),
    ('baseline_restore', 0, 0, 0, NOW())
ON CONFLICT (change_type) DO NOTHING;

-- migrate:down
DROP VIEW IF EXISTS meta.v_phase_change_stats;
DROP TABLE IF EXISTS meta.phase_change_profiles;
