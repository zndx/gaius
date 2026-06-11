# QR Login Extraction Map: Terminal OAuth via Cloudflare KV Relay

**Purpose**: Self-contained map for extracting the QR-based terminal login
technique out of Gaius into a standalone, reusable component. Written to be
read cold from a session in a *different* repository — all paths are absolute
into the Gaius checkout at `/home/rch/local/src/zndx/gaius`.

## The Technique (why it's worth extracting)

Terminal apps can't do browser OAuth well, and the auth often needs to happen
on a *different device* (your phone) than where the app runs (a headless
workstation). The localhost-callback trick fails there: the phone can't reach
`localhost:8765` on the workstation. Gaius solves this with a **Cloudflare
Worker as OAuth rendezvous**:

```
Terminal (TUI)                          Phone                    Cloudflare
──────────────                          ─────                    ──────────
1. Generate PKCE pair + random state
   persist (state, verifier, TTL) locally
2. Render auth URL as ASCII QR ───────► 3. Scan, log in to provider
                                        4. Provider redirects to
                                           Worker /x-callback ──► 5. Worker stores
                                                                    oauth-pending/{state}
                                                                    = {code} in KV (TTL 300s)
                                                                    + renders success page
                                                                    (code visible as manual
                                                                     fallback)
6. Engine polls KV (fast only while ◄───────────────────────────  Workers KV
   auth pending), finds code,
   exchanges code+verifier for tokens,
   DELETES the KV entry
7. Emits AUTH_COMPLETED event ─► TUI auto-dismisses the QR modal
```

Three security properties to preserve in any extraction:

1. **PKCE keeps the relay low-trust**: the code_verifier never leaves the
   workstation. The Worker/KV only ever see the authorization *code*, which
   is useless without the verifier. A compromised relay can't mint tokens.
2. **`state` is the rendezvous key**: random, single-use, TTL'd on *both*
   sides (local pending table AND KV expirationTtl=300).
3. **Cleanup**: KV entry deleted immediately after successful exchange;
   5-minute TTL caps the window if the flow is abandoned.

## Two Patterns — Don't Conflate Them

The repo actually contains **two** QR login patterns; the extraction should
offer both, because they serve different provider capabilities:

**Pattern A — Authorization Code + PKCE + Cloudflare relay** (the X/Twitter
bookmarks flow). Needed when the provider only supports redirect-based OAuth.
This is the novel piece and the bulk of this map.

**Pattern B — Device-code flow + QR** (the grok CLI subscription login,
proven 2026-06-11). **No Cloudflare needed** — the provider hosts the
rendezvous. The terminal runs the device flow, QR-encodes the
`verification_uri`, and polls the provider directly. If the target provider
supports RFC 8628 device flow, use this and skip the Worker entirely.
Gotcha learned: `grok login --device-auth` prints its URL/code to **stderr**,
not stdout — parse accordingly. A library should treat "where the URL comes
from" as pluggable (subprocess stderr, OIDC device endpoint response, etc.).

## Component Inventory (what to copy, where it lives)

### 1. QR rendering + modal (terminal side) — PORTABLE AS-IS
- `/home/rch/local/src/zndx/gaius/src/gaius/app.py` lines 72–97:
  `_generate_qr_ascii(url)` — qrcode lib, `ERROR_CORRECT_L`, `border=1`,
  `print_ascii(out=buffer, invert=True)`. ~25 lines, dep: `qrcode` (pure
  Python, no PIL needed for ASCII).
- Same file lines 100–194: `QRCodeModal(ModalScreen)` — Textual modal with
  title, QR display, URL text fallback, dismiss button. Generic (title+url),
  nothing X-specific. Note `CopyableTextModal = QRCodeModal` alias at L194.
- Auto-dismiss wiring: `/home/rch/local/src/zndx/gaius/src/gaius/widgets/init_panel.py`
  lines 626–673 — on `XB_AUTH_COMPLETED` event (engine→TUI gRPC event
  stream), pops the modal if it's the current screen.

### 2. OAuth core (PKCE, exchange, refresh) — PORTABLE WITH STORAGE SWAP
- `/home/rch/local/src/zndx/gaius/src/gaius/auth/x_oauth.py` (514 lines):
  - `generate_pkce_pair()` (L106) — verifier + S256 challenge
  - `get_authorization_url(state, config)` (L124)
  - `exchange_code_for_token()` (L156), `refresh_access_token()` (L209)
  - `save_tokens/get_tokens/ensure_valid_token` (L283–437) — **asyncpg;
    this is the part to re-back with sqlite/keyring/file in a standalone lib**
  - `XOAuthClient` facade (L438)
  - Default redirect: `https://gaius.zndx.org/x-callback` (L77), overridable
    via `X_REDIRECT_URI` / HOCON `callback_url`.
- `/home/rch/local/src/zndx/gaius/src/gaius/auth/README.md` — flow docs,
  scope table, env matrix (mermaid diagram is slightly stale: it shows
  manual code entry; KV relay is the primary path, manual entry the fallback).

### 3. Cloudflare Worker (the relay) — PORTABLE NEARLY AS-IS
- `/home/rch/local/src/zndx/gaius/gaius-ui/apps/worker/src/routes/callback.ts`
  (77 lines, Hono): stores `oauth-pending/{state}` → `{code, timestamp}` in
  KV binding `GAIUS_SESSIONS` with `expirationTtl: 300`; optional direct
  POST to `ENGINE_CALLBACK_URL` (`/api/oauth/x-callback`) when the engine is
  reachable; always renders a result page.
- Route registration: `.../worker/src/index.ts` L58.
- Result page rendering: `.../worker/src/a2ui/renderer.ts` (225 lines) —
  gaius-specific A2UI; for extraction, replace with ~20 lines of plain HTML
  showing success/failure + the code as manual fallback.
- KV binding: `.../worker/wrangler.toml` (`[[kv_namespaces]] binding =
  "GAIUS_SESSIONS"`). Standalone deploy is: one route, one KV namespace,
  `wrangler deploy`.

### 4. Engine-side KV polling + completion — THE ADAPTIVE LOOP
- `/home/rch/local/src/zndx/gaius/src/gaius/engine/services/x_bookmarks_service.py`:
  - `poll_kv_for_pending_auth()` (L463–560): reads pending states from DB,
    GETs `accounts/{acct}/storage/kv/namespaces/{ns}/values/oauth-pending/{state}`
    via Cloudflare REST API, completes auth, DELETEs the KV key, emits
    `XB_AUTH_COMPLETED`.
  - `complete_auth_by_state(code, state)` (L421) — looks up verifier by
    state from the pending table.
  - Adaptive poll loop (L2025–2055): **fast poll only while an auth is
    pending; slow existence-check otherwise.** Keep this — it's what makes
    REST-API polling acceptable (CF API is rate-limited and not free at
    high frequency).
- Config: `gaius.core.config` `cloudflare.account_id` / `cloudflare.api_token`
  + env `CLOUDFLARE_KV_NAMESPACE_ID`. Polling is skipped (not an error) when
  unconfigured — the manual code-entry path still works. Preserve this
  graceful tiering: relay configured → automatic; not configured → manual.

### 5. Persistence schema
- `/home/rch/local/src/zndx/gaius/db/migrations/20251227000001_x_bookmarks_sync.sql`
  — `x_oauth_pending` (state, code_verifier, expires_at) and token storage.
  For a standalone lib: a 2-table sqlite schema (pending, tokens) is enough.

## Dependency / Config Matrix

| Piece | Deps | Config |
|-------|------|--------|
| QR render | `qrcode` | — |
| OAuth core | `httpx` | provider client_id, redirect_uri, scopes |
| Worker | wrangler, Hono (or none) | KV namespace, optional ENGINE_CALLBACK_URL |
| KV polling | `httpx` | CF account_id, API token (KV read+delete ONLY — scope it minimally), namespace_id |
| Device-flow variant | none beyond subprocess/httpx | provider device endpoint or CLI |

## Suggested Extraction Shape

```
qrauth/  (working name)
├── qr.py            # ascii QR (from _generate_qr_ascii; UI-framework-free)
├── pkce.py          # generate_pkce_pair, auth URL builder (provider-pluggable)
├── relay/
│   ├── worker.ts    # callback route + KV put + plain-HTML result (~60 lines)
│   └── wrangler.toml
├── poller.py        # CF KV REST polling w/ adaptive cadence + completion hook
├── device_flow.py   # Pattern B: RFC 8628 / CLI-wrapped device auth
├── store.py         # pending-state + token storage protocol (sqlite default)
└── frontends/
    └── textual.py   # QRCodeModal port (optional extra)
```

Copy order for the extraction session: (1) `qr.py` + `pkce.py` (pure, no
deps on gaius), (2) worker (replace A2UI with plain HTML), (3) poller
(replace asyncpg pending lookup with store protocol), (4) device_flow
(new code; reference the grok stderr gotcha), (5) textual frontend last.

## Pitfalls Learned in Gaius (encode these in the lib)

1. **State lookup must be by-state, not by-session** — the phone completes
   the flow with zero knowledge of the terminal session; `state` is the only
   correlation key (`complete_auth_by_state`).
2. **Worker direct-POST is an optimization, not the mechanism** — the
   engine may be behind NAT/firewall; KV polling is the reliable path,
   direct callback just shortens latency when reachable. Keep both.
3. **Poll cadence**: fast-poll ONLY while a pending auth exists (Gaius
   checks the pending table first, then polls KV). Unconditional fast
   polling burns CF API quota for nothing.
4. **Delete-after-claim**: remove the KV entry on successful exchange or
   replays within the TTL window are possible (PKCE limits damage, but
   don't rely on it alone).
5. **QR rendering**: `invert=True` matters for dark terminals; keep the
   plain-URL fallback visible — some users will be on the same machine.
6. **Device flow (Pattern B)**: provider CLIs may write the verification
   URL to stderr (grok does) or require a PTY for display; capture both
   streams. Bare `grok` failing with ENXIO just means no `/dev/tty`.

## Verification Targets for the Extracted Lib

- Pattern A e2e against a real provider (X works with `bookmark.read` on
  API Pro tier; any OAuth2+PKCE provider is fine)
- Pattern B against grok CLI: start device-auth, parse stderr URL, QR it,
  poll for `~/.grok/auth.json`, then prove subscription via an ACP
  `initialize`→`authenticate`→`session/prompt` with `XAI_API_KEY` unset
  (see Gaius commit `0673cc7` and scratch note
  `docs/scratch/2026-06-11/001752_grok_acp_agent_option.md` for the exact
  proven sequence)
- Relay-unconfigured tier: manual code entry still completes
```
