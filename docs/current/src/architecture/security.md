# Security

Gaius employs a multi-layer security model focused on protecting autonomous operations. Security verification is **mandatory and cannot be disabled** — this is by design to prevent generated code from bypassing security checks.

## Threat Model

The primary attack surface is the ACP (Agent Client Protocol) integration, which allows autonomous health maintenance via GitHub issue workflows. Without controls, an agent could:

- Leak internal state to public repositories
- Be influenced by prompt injection in externally-controlled issues
- Expose credentials in issue comments
- Be tricked by repository visibility changes

## Four Security Layers

All four layers execute on every GitHub operation. There is no parameter or configuration to skip layers — security is structural, not optional.

| Layer | Check | Purpose | Guru Code on Failure |
|-------|-------|---------|---------------------|
| 0 | [Format validation](./acp-security.md) | Reject malformed repository names | `#ACP.SEC.00000005.BADFORMAT` |
| 1 | [HOCON allowlist](./acp-security.md) | Explicit repository patterns only | `#ACP.SEC.00000002.NOTALLOWED` |
| 2 | [Visibility verification](./acp-security.md) | Repository must be private (via `gh api`) | `#ACP.SEC.00000003.NOTPRIVATE` |
| 3 | [Content sanitization](./sanitization.md) | Redact secrets, strip injection markers | N/A (sanitizes, doesn't reject) |

Layer 2 re-verifies repository visibility on each operation (configurable cache TTL of 5 minutes). This protects against visibility change attacks where a repository is made public after initial validation.

## Cadence Controls

To prevent runaway automation:

- Maximum 3 GitHub issues per 24 hours
- Minimum 5 minutes between restart attempts
- Maximum 3 restarts per endpoint per hour
- Cooldown per incident fingerprint (prevents repeated escalation)
- All changes committed to `acp/health-fix` branch for human review

## Content Sanitization

Before any content is included in GitHub issues, `sanitize_issue_content()` automatically redacts:

- **API keys**: Anthropic (`sk-ant-`), OpenAI (`sk-proj-`), AWS (`AKIA`)
- **GitHub tokens**: PAT (`ghp_`), OAuth (`gho_`), App (`ghs_`), Refresh (`ghr_`)
- **Bearer tokens**: `Bearer <token>` → `Bearer [REDACTED_BEARER]`
- **Generic secrets**: `api_key=`, `token=`, `password=`, `secret=`
- **Prompt injection markers**: `<|system|>`, `IGNORE PREVIOUS INSTRUCTIONS`, `JAILBREAK`

Pattern order matters — specific patterns are matched before generic ones to ensure correct replacement labels.

## Design Principle

Security verification is mandatory because the ACP agent generates code. If security were an option (`fail_fast=True`), generated code could set it to `False`. Making it structural — mandatory, with no bypass parameter — ensures that even compromised agent output cannot disable the security layer.

See [ACP Security Model](./acp-security.md) for implementation details and [Content Sanitization](./sanitization.md) for redaction rules.
