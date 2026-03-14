# Remediation Strategies

Fix strategies are multi-step procedures that diagnose, repair, and verify service health. Each strategy is registered in the `SERVICE_STRATEGIES` dictionary and invoked via `/health fix <service>`.

## Available Fix Strategies

| Service | Strategy | Steps |
|---------|----------|-------|
| `engine` | EngineFixStrategy | Kill stale processes, clean CUDA, restart |
| `dataset` | DatasetFixStrategy | Re-initialize NiFi connection, verify |
| `nifi` | NiFiFixStrategy | Check connectivity, restart processors |
| `postgres` | PostgresFixStrategy | Check connection, verify schema |
| `qdrant` | QdrantFixStrategy | Check connectivity, verify collections |
| `minio` | MinIOFixStrategy | Check connectivity, verify buckets |
| `endpoints` | EndpointsFixStrategy | Health check, restart unhealthy |
| `evolution` | EvolutionFixStrategy | Restart evolution daemon |

## Strategy Pattern

Each strategy follows the same pattern:

```python
class EngineFixStrategy:
    async def execute(self) -> FixResult:
        # Step 1: Diagnose
        issues = await self.diagnose()

        # Step 2: Remediate
        for issue in issues:
            await self.fix(issue)

        # Step 3: Verify
        healthy = await self.verify()

        return FixResult(
            success=healthy,
            steps_taken=self.steps,
            duration_ms=elapsed,
        )
```

## Three-Tier System

### Tier 0: Procedural (RPN < 100)

Automatic restart without agent involvement:

```python
# Kill stale process, wait, restart
await orchestrator.stop_endpoint(endpoint)
await asyncio.sleep(5)  # Cool-down
await orchestrator.start_endpoint(endpoint)
```

### Tier 1: Agent-Assisted (RPN 100-200)

Uses a healthy inference endpoint to diagnose and decide on remediation:

```python
diagnosis = await inference.analyze(issue.to_dict())
if diagnosis.action == "clear_cache":
    await clear_kv_cache(endpoint)
elif diagnosis.action == "rollback":
    await rollback_config(endpoint)
```

### Tier 2: Approval Required (RPN > 200)

Creates an approval record for human review. Destructive operations (data modification, configuration changes) always require Tier 2 regardless of RPN.

## Usage

```bash
# Fix a specific service
uv run gaius-cli --cmd "/health fix engine" --format json

# Fix all unhealthy services
uv run gaius-cli --cmd "/health fix all" --format json
```

## Adding a New Fix Strategy

1. Create a class in `health/service_fixes.py` implementing `execute() -> FixResult`
2. Register it in `SERVICE_STRATEGIES`
3. Add a KB heuristic document
4. Test via `/health fix <service>`
