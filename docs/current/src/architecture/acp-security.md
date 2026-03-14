# ACP Security Model

The Agent Client Protocol uses four mandatory security layers for all GitHub operations. Every layer must pass; there is no bypass mechanism.

## Layer 0: Format Validation

Repository names are validated against strict regex patterns before any network call:

```python
# Supported formats:
"owner/repo"                  # Legacy (github.com assumed)
"github.com/owner/repo"      # Full URL
"github.example.com/org/repo" # On-prem GitHub Enterprise
```

Invalid characters, missing components, or malformed URLs raise `GitHubSecurityError` immediately with `#ACP.SEC.00000005.BADFORMAT`.

## Layer 1: HOCON Allowlist

Repositories must be explicitly listed in `~/.config/gaius/acp.conf`:

```hocon
acp {
  github {
    allowed_repos = ["zndx/gaius-acp"]
    require_private = true
    verify_on_each_operation = true
    cache_visibility_seconds = 300
  }
}
```

Glob patterns are supported: `"zndx/*"` allows any repo under the `zndx` org. An empty allowlist means no repositories are allowed (`#ACP.SEC.00000004.NOTCONFIGURED`).

## Layer 2: Visibility Verification

The `GitHubSecurityGuard` verifies repository visibility via `gh api repos/{owner}/{repo} --jq .visibility`. Only `"private"` passes; `"public"` and `"internal"` are rejected with `#ACP.SEC.00000003.NOTPRIVATE`.

Visibility is cached for 5 minutes (configurable via `cache_visibility_seconds`) and re-verified on each operation when `verify_on_each_operation = true`.

## Layer 3: Content Sanitization

Before including any content in GitHub issues, `sanitize_issue_content()` redacts secrets and strips prompt injection markers. See [Content Sanitization](./sanitization.md) for details.

Issue titles must start with `[HEALTH-FIX]` prefix and are limited to 200 characters.

## Attack Vectors Mitigated

| Attack | Mitigation |
|--------|------------|
| Info leak via public repo | Layer 2: visibility verification on every operation |
| Prompt injection from issues | Layer 1: explicit allowlist prevents attacker-controlled repos |
| Credential exposure in issues | Layer 3: automatic secret redaction |
| Visibility change attack | Re-verify on each operation (cache TTL 5 min) |
| Generated code bypass | Security is mandatory -- no parameter to disable |

## Usage

```python
from gaius.acp.security import GitHubSecurityGuard

guard = GitHubSecurityGuard.from_config()
await guard.verify_repo("zndx/gaius-acp")  # Raises on failure
```

## Source

`src/gaius/acp/security.py`
