# Grok as ACP Agent Option (config-gated)

Added xAI Grok as a second ACP agent alongside Mistral Vibe, gated behind
`acp.agent` in `~/.config/gaius/acp.conf` (default remains `vibe`), per the
agreed condition: only after proving QR-based subscription login end-to-end.

## Proof Sequence (the gate)

1. **Discovery**: `grok agent stdio` speaks native ACP v1 — verified with a
   raw JSON-RPC `initialize` probe. Advertises `loadSession`, embedded
   context, MCP passthrough, and auth methods `xai.api_key` + `grok.com`.
2. **QR login**: `grok login --device-auth` run headless in background;
   verification URL (`accounts.x.ai/oauth2/device?user_code=...`) extracted
   from **stderr** (not stdout!), rendered as ASCII QR using the production
   `_generate_qr_ascii` from `gaius.app` (same path as the X Bookmarks
   modal). Scanned on phone → signed in as rch@zndx.org → `~/.grok/auth.json`.
3. **Subscription proof**: ACP `session/new` + `session/prompt` round-trip
   with `XAI_API_KEY` stripped from env. Auth method offered: `cached_token`.
   Response received (model `grok-build`, end_turn) — billed to subscription,
   zero API-key involvement.
4. **Production client proof**: `GaiusACPClient` with `ACPConfig(agent="grok")`,
   no API key → connected, prompted, exact-string response received.

## Implementation

| File | Change |
|------|--------|
| `src/gaius/acp/client.py` | `ACP_AGENT_KEYS`, `load_acp_agent_selection()` (env `GAIUS_ACP_AGENT` > HOCON `acp.agent` > "vibe"), `resolve_acp_agent()` with fail-fast checks, `ACPConfig.agent` + `__post_init__` resolution |
| `src/gaius/acp/attribution.py` | `"grok"` → Grok ⚡ https://x.ai |
| `src/gaius/acp/__init__.py` | Export new helpers |
| `src/gaius/cli.py` | `/acp` (status) and `/acp agents` commands |
| `tests/acp/test_agent_selection.py` | 9 tests (selection, fail-fast, resolution, attribution) |
| `~/.config/gaius/acp.conf` | Documented `agent = "vibe"` key (user config, not committed) |
| `CLAUDE.md` | HOCON example updated |

## Guru Meditation Codes (new)

| Code | Description |
|------|-------------|
| `#ACP.00000011.BADAGENT` | Unknown `acp.agent` value |
| `#ACP.00000012.AGENTMISSING` | Selected agent binary not in PATH |
| `#ACP.00000013.GROKAUTH` | Grok selected but no subscription token / API key |

## Gotchas Recorded

- `grok login --device-auth` prints URL/code to **stderr**; silent on stdout.
- Bare `grok` ENXIO (os error 6) = TUI failing to open `/dev/tty` in
  non-interactive contexts; the CLI itself is healthy.
- dbmate-format caution from yesterday still applies to any migration work.

## Verification (2026-06-11)

- `uv run pytest tests/acp/` → 39 passed
- `uv run gaius-cli --cmd "/acp" --format json` → vibe, available
- `GAIUS_ACP_AGENT=grok ... "/acp"` → grok, available, auth: subscription
- `/acp agents` → both agents available
- Production client e2e via grok subscription → exact-string response

## Follow-ups (not done)

- `/acp auth grok` TUI command: drive device-auth + QRCodeModal in-app
  (manual login proven; in-app flow is UX sugar)
- Generalize Mistral-specific rate-limit wording in `ACPRateLimitError`
- First supervised Grok escalation on the acp/health-fix branch before
  considering it for default
