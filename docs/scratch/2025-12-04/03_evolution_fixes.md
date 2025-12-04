# Evolution System Fixes - 2025-12-04

## Summary

Fixed multiple issues preventing the evolution daemon from running overnight:

1. **DB Enum Values**: Added missing `research_complete`, `reflection_complete`, `evolution_cycle` to `activity_type` enum

2. **Bootstrap Training Examples**: Added fallback in `TrainingCollector` to use `held_out_queries` when no organic training data exists (cold-start scenario)

3. **Endpoint Discovery**: Added `_discover_vllm_endpoint()` to `InferenceConfig` that automatically finds the first available vLLM endpoint instead of hardcoding port 8084

4. **Evaluation API Fix**: Fixed `_generate_agent_output()` to use `scheduler.submit(Job(...))` instead of non-existent `scheduler.submit_job()`

5. **Daemon Attribute Fix**: Changed `result.candidates_evaluated` to `result.num_candidates` to match `OptimizationResult` dataclass

6. **DB Logging Schema**: Fixed evolution cycle DB logging to match actual `evolution_cycles` table schema (uses `training_scores` JSONB instead of separate columns)

## Test Results

Successfully ran evolution cycle:
- Agent: leader
- Improvement: 6.29%
- New version: `leader-eca211a0a16d64d9-d1c99269`
- Examples used: 10 (from bootstrap)
- Candidates evaluated: 1

## Remaining Issues

- optillm API key warnings (fallback to vLLM works but generates noise)
- Consider starting optillm with correct API key or skipping it entirely

## Files Modified

- `db/migrations/20251204000002_add_activity_types.sql` (new)
- `src/gaius/agents/evolution/collector.py` - bootstrap fallback
- `src/gaius/agents/evolution/evaluation.py` - scheduler API fix
- `src/gaius/agents/evolution/daemon.py` - attribute + DB schema fixes
- `src/gaius/inference/config.py` - endpoint discovery
