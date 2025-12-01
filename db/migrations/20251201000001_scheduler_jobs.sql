-- Scheduler Jobs Table
-- ======================
-- Persistent storage for inference jobs enabling:
-- - Job recovery after app restart
-- - Retry of failed jobs
-- - Complete audit trail

-- Job priority levels
CREATE TYPE job_priority AS ENUM ('critical', 'high', 'normal', 'low');

-- Job execution status
CREATE TYPE job_status AS ENUM ('pending', 'scheduled', 'running', 'completed', 'failed', 'cancelled');

-- Main jobs table
CREATE TABLE scheduler_jobs (
    -- Primary key (UUID for distributed generation)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Job specification
    model TEXT NOT NULL,
    messages JSONB NOT NULL,
    priority job_priority NOT NULL DEFAULT 'normal',
    status job_status NOT NULL DEFAULT 'pending',

    -- Scheduling hints
    preferred_endpoint TEXT,           -- Requested endpoint
    assigned_endpoint TEXT,            -- Actually assigned endpoint
    estimated_tokens INT DEFAULT 500,  -- Estimated output tokens
    deadline_ms INT DEFAULT 30000,     -- Max acceptable latency

    -- Timing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_at TIMESTAMPTZ,          -- When scheduled
    started_at TIMESTAMPTZ,            -- When execution started
    completed_at TIMESTAMPTZ,          -- When completed/failed

    -- Results
    result TEXT,                       -- Response content
    error TEXT,                        -- Error message if failed
    input_tokens INT DEFAULT 0,        -- Actual input tokens
    output_tokens INT DEFAULT 0,       -- Actual output tokens
    latency_ms INT DEFAULT 0,          -- Actual latency

    -- Recovery
    retry_count INT DEFAULT 0,         -- Number of retry attempts
    max_retries INT DEFAULT 3,         -- Max allowed retries

    -- Context
    role TEXT,                         -- Agent role (Leader, Critic, etc.)
    metadata JSONB DEFAULT '{}'::jsonb -- Additional metadata
);

-- Indexes for common queries

-- Find pending jobs by priority (for scheduler)
CREATE INDEX idx_scheduler_jobs_pending ON scheduler_jobs(priority, created_at)
    WHERE status = 'pending';

-- Find jobs by status (for monitoring)
CREATE INDEX idx_scheduler_jobs_status ON scheduler_jobs(status);

-- Find failed jobs eligible for retry
CREATE INDEX idx_scheduler_jobs_retry ON scheduler_jobs(created_at)
    WHERE status = 'failed' AND retry_count < max_retries;

-- Find jobs by endpoint (for endpoint-specific queries)
CREATE INDEX idx_scheduler_jobs_endpoint ON scheduler_jobs(assigned_endpoint)
    WHERE assigned_endpoint IS NOT NULL;

-- Find recent completed jobs (for metrics)
CREATE INDEX idx_scheduler_jobs_completed ON scheduler_jobs(completed_at DESC)
    WHERE status IN ('completed', 'failed');

-- Comments
COMMENT ON TABLE scheduler_jobs IS 'Persistent inference job queue for Gaius scheduler';
COMMENT ON COLUMN scheduler_jobs.model IS 'Model ID (e.g., Qwen/QwQ-32B)';
COMMENT ON COLUMN scheduler_jobs.messages IS 'OpenAI-format messages array';
COMMENT ON COLUMN scheduler_jobs.preferred_endpoint IS 'User-requested endpoint preference';
COMMENT ON COLUMN scheduler_jobs.assigned_endpoint IS 'Endpoint where job was actually scheduled';
COMMENT ON COLUMN scheduler_jobs.role IS 'Swarm agent role if part of swarm execution';
