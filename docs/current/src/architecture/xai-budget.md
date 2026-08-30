# XAI Budget

The XAI budget system tracks and limits usage of external AI APIs (xAI Grok, Cerebras) to prevent runaway costs while enabling strategic use for evaluation, critique, and calibration.

## Why External APIs

Local models (24B on vLLM) handle most inference. External frontier models serve specific roles where independent judgment matters:

| Use Case | Provider | Model | Purpose |
|----------|----------|-------|---------|
| Agent evaluation | xAI | Grok 4.1 Fast | Independent critique of agent output quality |
| Calibration | xAI + Cerebras | Grok + Llama | Cross-validate local evaluation scores against frontier |
| Held-out evaluation | xAI | Grok 4.1 Fast | Measuring agent improvement on unseen queries |
| Documentation review | xAI | Grok 4.1 Fast | Precision audits and tone calibration |

The `CalibrationOracle` specifically uses external APIs to detect evaluation drift — if local scores diverge significantly from frontier assessments, it flags calibration drift, preventing the system from optimizing toward a biased local metric.

## Budget Tracking

The budget persists in PostgreSQL so it survives engine restarts:

```python
budget = scheduler.get_xai_budget()
# budget.daily_remaining — tokens left for today
# budget.daily_limit — configured daily cap
# budget.reset_time — midnight UTC
# budget.used_today — tokens consumed since last reset
```

## Usage Controls

- **Daily token limit**: Configured per provider in HOCON (`engine.xai_daily_limit`)
- **Request rejection**: When budget exhausted, requests fail with `#SCHED.00001.BUDGETEXHAUSTED`
- **Priority gating**: Only HIGH and CRITICAL priority jobs can use external APIs — evolution and batch jobs use local inference only
- **Evaluation budget**: Separate allocation for agent evaluation tasks, preventing held-out evaluation from consuming the interactive budget
- **Cost tracking**: Each external API call records provider, model, token count, and latency for cost attribution

## Routing

The `ExternalInferenceRouter` dispatches to the appropriate provider:

```python
from gaius.engine.backends.external.router import ExternalInferenceRouter

router = ExternalInferenceRouter()
result = await router.complete(
    prompt="Evaluate this agent response...",
    provider="xai",          # or "cerebras"
    max_tokens=2048,
)
```

The router checks budget before dispatching. If the daily limit is reached, it raises an error rather than silently falling back to local inference — the caller must decide whether to retry locally or wait for budget reset.

## CLI Commands

```bash
# Check current budget
uv run gaius-cli --cmd "/xai budget" --format json

# Reset budget (admin)
uv run gaius-cli --cmd "/xai reset" --format json

# Evaluate with external model
uv run gaius-cli --cmd "/xai evaluate" --format json

# Compare local vs external evaluation
uv run gaius-cli --cmd "/xai compare" --format json
```
