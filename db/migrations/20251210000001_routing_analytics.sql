-- migrate:up
-- Routing analytics for capability-based inference decisions
-- Tracks when agents are "starved" of optimal model selections

CREATE TABLE routing_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Request context
    agent_role TEXT,
    agent_alias TEXT NOT NULL,
    workflow_phase TEXT,

    -- Capability requirements
    requested_capabilities TEXT[] DEFAULT '{}',
    preferred_model TEXT,

    -- Routing outcome
    actual_endpoint TEXT NOT NULL,
    actual_model TEXT NOT NULL,

    -- Mismatch tracking
    fallback_used BOOLEAN DEFAULT FALSE,
    fallback_reason TEXT,
    capability_mismatch BOOLEAN DEFAULT FALSE,
    mismatched_capabilities TEXT[] DEFAULT '{}',

    -- Outcome
    success BOOLEAN NOT NULL,
    latency_ms INTEGER NOT NULL
);

-- Index for time-based queries (health checks look at recent data)
CREATE INDEX idx_routing_created ON routing_decisions(created_at);

-- Partial index for mismatch queries (only care about mismatches)
CREATE INDEX idx_routing_mismatch ON routing_decisions(capability_mismatch)
    WHERE capability_mismatch;

-- Index for agent-specific queries
CREATE INDEX idx_routing_agent ON routing_decisions(agent_alias, created_at);

-- Index for capability gap analysis
CREATE INDEX idx_routing_capabilities ON routing_decisions
    USING GIN (mismatched_capabilities)
    WHERE capability_mismatch;

COMMENT ON TABLE routing_decisions IS 'Tracks capability-based inference routing decisions';
COMMENT ON COLUMN routing_decisions.capability_mismatch IS 'True when agent got suboptimal model due to capability/availability mismatch';
COMMENT ON COLUMN routing_decisions.mismatched_capabilities IS 'List of capabilities that could not be satisfied';

-- migrate:down
DROP TABLE IF EXISTS routing_decisions;
