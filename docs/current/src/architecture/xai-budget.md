# XAI Budget

The XAI budget system tracks and limits usage of external AI APIs (xAI Grok, Cerebras) to prevent runaway costs while enabling strategic use for evaluation and critique.

## Budget Tracking

```python
budget = scheduler.get_xai_budget()
# budget.daily_remaining — tokens left for today
# budget.daily_limit — configured daily cap
# budget.reset_time — when the budget resets (midnight UTC)
```

## Usage Controls

- **Daily token limit**: Configured per provider
- **Request rejection**: When budget exhausted, requests fail with clear error
- **Priority gating**: Only HIGH and CRITICAL priority jobs can use external APIs
- **Evaluation budget**: Separate allocation for agent evaluation tasks

## CLI Commands

```bash
# Check current budget
uv run gaius-cli --cmd "/xai budget" --format json

# Reset budget (admin)
uv run gaius-cli --cmd "/xai reset" --format json

# Evaluate with external model
uv run gaius-cli --cmd "/xai evaluate" --format json
```

## When External APIs Are Used

| Use Case | Provider | Purpose |
|----------|----------|---------|
| Agent evaluation | xAI Grok | Independent critique of agent output |
| Cross-validation | Cerebras | Second opinion on critical decisions |
| Held-out evaluation | xAI Grok | Measuring agent improvement |
