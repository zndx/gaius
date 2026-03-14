# Content Sanitization

Before any content is included in GitHub issues (via ACP escalation), the `sanitize_issue_content()` function automatically redacts secrets and strips prompt injection markers.

## Secret Patterns

The following patterns are detected and replaced with `[REDACTED_*]` tags:

| Pattern | Example | Replacement |
|---------|---------|-------------|
| Anthropic API keys | `sk-ant-api03-...` | `[REDACTED_ANTHROPIC_KEY]` |
| OpenAI keys | `sk-proj-...`, `sk-...` | `[REDACTED_OPENAI_KEY]` |
| GitHub PAT | `ghp_...` | `[REDACTED_GH_PAT]` |
| GitHub OAuth | `gho_...` | `[REDACTED_GH_OAUTH]` |
| GitHub App | `ghs_...` | `[REDACTED_GH_APP]` |
| GitHub Refresh | `ghr_...` | `[REDACTED_GH_REFRESH]` |
| AWS Access Key | `AKIA...` (20 chars) | `[REDACTED_AWS_KEY]` |
| Bearer tokens | `Bearer <token>` | `Bearer [REDACTED_BEARER]` |
| Generic secrets | `api_key=`, `token=`, `password=`, `secret=` | `[REDACTED]` |

Pattern order matters: specific patterns (e.g., `sk-ant-`) are matched before generic ones (e.g., `sk-`) to ensure correct replacement labels.

## Prompt Injection Markers

The following injection patterns are replaced with `[SANITIZED]`:

- LLM role markers: `<|system|>`, `<|user|>`, `<|assistant|>`, `[INST]`, `<<SYS>>`
- Override attempts: `IGNORE PREVIOUS INSTRUCTIONS`, `SYSTEM OVERRIDE:`, `ADMIN MODE:`
- Known bypass patterns: `JAILBREAK`, `DAN MODE`, `DEVELOPER MODE:`

All matching is case-insensitive.

## Usage

```python
from gaius.acp.security import sanitize_issue_content

raw = "Error with key sk-ant-api03-abc123... calling endpoint"
safe = sanitize_issue_content(raw)
# "Error with key [REDACTED_ANTHROPIC_KEY] calling endpoint"
```

## Issue Title Validation

Issue titles are validated separately via `validate_issue_title()`:

- Must start with `[HEALTH-FIX]` prefix
- Truncated to 200 characters
- Control characters stripped

## Source

`src/gaius/acp/security.py` (the `sanitize_issue_content` and `validate_issue_title` functions).
