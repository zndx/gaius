# Security

Gaius employs a multi-layer security model focused on protecting autonomous operations. Security verification is **mandatory and cannot be disabled** -- this is by design to prevent generated code from bypassing security checks.

## Threat Model

The primary attack surface is the ACP (Agent Client Protocol) integration, which allows autonomous health maintenance via GitHub issue workflows. Without controls, an agent could:

- Leak internal state to public repositories
- Be influenced by prompt injection in externally-controlled issues
- Expose credentials in issue comments
- Be tricked by repository visibility changes

## Security Layers

| Layer | Check | Purpose |
|-------|-------|---------|
| 0 | [Format validation](./acp-security.md) | Reject malformed repository names |
| 1 | [HOCON allowlist](./acp-security.md) | Explicit repository patterns only |
| 2 | [Visibility verification](./acp-security.md) | Repository must be private (via `gh api`) |
| 3 | [Content sanitization](./sanitization.md) | Redact secrets, strip injection markers |

All four layers execute on every operation. There is no parameter or configuration to skip layers.

## Cadence Controls

To prevent runaway automation:

- Maximum 3 GitHub issues per 24 hours
- Minimum 5 minutes between restart attempts
- Maximum 3 restarts per endpoint per hour
- All changes committed to `acp-claude/health-fix` branch for human review

## Guru Meditation Codes

Security failures use the `#ACP.SEC.*` code family:

| Code | Description |
|------|-------------|
| `#ACP.SEC.00000002.NOTALLOWED` | Repository not in allowlist |
| `#ACP.SEC.00000003.NOTPRIVATE` | Repository not private |
| `#ACP.SEC.00000004.NOTCONFIGURED` | No repositories configured |
| `#ACP.SEC.00000005.BADFORMAT` | Invalid repository format |

See [ACP Security Model](./acp-security.md) for implementation details and [Content Sanitization](./sanitization.md) for redaction rules.
