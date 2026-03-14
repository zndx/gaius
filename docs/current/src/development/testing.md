# Testing

Gaius follows a CLI-first testing methodology. The CLI is the product — all functionality must be verifiable through it.

## Core Rules

### 1. Re-Test After Every Code Change

Previous test outputs are invalidated by code changes. Don't reason from stale context — run the command again.

```bash
# After editing code:
# BAD: "The fix should work based on my analysis"
# GOOD: Actually run it
uv run gaius-cli --cmd "/evolve status" --format json
```

### 2. No Static Test Data

We do not fall back to static test data. All functional aspects of new features must be verified directly against running services.

### 3. No Fallback Workarounds

Do not rely on fallbacks or workarounds when testing. If a service is down, fix it (via `/health fix`) rather than mocking around it.

## Verification Patterns

### Health Check

```bash
uv run gaius-cli --cmd "/health" --format json
```

### Endpoint Status

```bash
uv run gaius-cli --cmd "/gpu status" --format json | jq '.data.endpoints[] | {name, status}'
```

### Evolution Status

```bash
uv run gaius-cli --cmd "/evolve status" --format json
```

### Import Verification

For new modules or proto changes:

```bash
uv run python -c "from gaius.engine.generated import NewSymbol; print('OK')"
```

## TUI Testing

TUI behavior must be tested using Textual Pilot before committing:

```python
async with app.run_test() as pilot:
    await pilot.press("h")  # Navigate left
    assert app.cursor_x == expected_x
```

## Fail-Fast Compliance

Before committing, verify:

```bash
# No fallback patterns
grep -rn "fail_fast\|SELENIUM_AVAILABLE\)" src/gaius/
# No placeholder image colors
grep -rn "240, 240, 240" src/gaius/
```

All error messages must include guru meditation codes and remediation hints.
