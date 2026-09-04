"""Token budgets and hard limits at agent-integration points.

Doctrine (2026-09-03): minute per-call token budgets are anachronistic.
The thinking endpoint serves Qwen3.8-27B at a 262 144-token window
(``--max-model-len`` from ``agents.conf`` ``resources.context-length``) and
its reasoning traces count against ``max_tokens``. ``max_tokens`` is a
CEILING, not a spend — generation stops at the model's closing token — so
a generous ceiling costs nothing on the normal path, while a tight one
fails silently: a 2 048 cap produced empty Agenda Briefs, a 4 096 cap
THINKBURNed cognition, a 1 536 rubric self-score returned no JSON at all.

Every ``max_tokens`` on a thinking-lane or agent path imports from here so
the doctrine is auditable with one grep::

    grep -rnE "max_tokens[=:] *[0-9]{3,4}\\b" src/gaius/engine src/gaius/client

should return only deliberate exceptions (connectivity probes, scalar
reward parses, bytez bench calls).
"""

# One Engine/Complete on the thinking lane: analysis, decisions, scoring,
# self-observation. Reasoning trace + answer.
REASONING_MAX_TOKENS = 16384

# Long-form deliverables: Agenda Briefs, prospects syntheses and .base
# generation, research reports, cot_reflection syntheses.
LONG_FORM_MAX_TOKENS = 32768

# One ACP agent turn (grok-build on thinking: edit sessions, RCA, judge
# consultations). The agent's whole reasoning for a turn fits here.
AGENT_TURN_MAX_TOKENS = 65536

# Mirror of agents.conf ``thinking.resources.context-length`` — the live
# ``--max-model-len``. Advertised to grok-build so its compaction logic
# sees the real window.
THINKING_CONTEXT_WINDOW = 262144

# External API models (xAI grok-4-1-fast, Cerebras). Reasoning tokens
# count against the cap there too; still a ceiling, billed per token
# generated.
EXTERNAL_MAX_TOKENS = 8192

# Grid-position explanations (short, structured).
EXPLAIN_MAX_TOKENS = 4096

# ACP agent process: spawn + initialize handshake, under GPU-load
# contention.
ACP_CONNECTION_TIMEOUT_S = 60.0

# grok-build's inference_idle_timeout_secs for the thinking lane. Its
# default (600) killed every long weave turn: the façade advertises
# stream=true but Engine/Complete is unary, so the agent sees NO chunks
# until the whole reasoning trace is done — "idle" here means "still
# thinking". The engine supervises token progress itself
# (GAIUS_INFERENCE_STALL_S); this is a dead-lane outer net only.
ACP_INFERENCE_IDLE_TIMEOUT_S = 7200

# Overwatch judge (ACP+Grok, subscription). Daily caps guard against
# trigger storms, not spend; legitimate load is 4 objective verifies/day
# plus Nautilus escalations.
JUDGE_CONSULTS_PER_DAY = 24
RUBRIC_JUDGMENTS_PER_DAY = 24

# Outer net for one multi-turn ACP incorporation session (progress
# doctrine: a net for a dead lane, never a deadline). Matches the
# prospects synthesis net.
INCORPORATION_NET_S = 1800.0

# Queue-share apply (Signals arbiter → YuniKorn ConfigMap). The apply
# itself takes ~4 s when the applier runs and minutes when its single
# worker is busy or backing off; a fixed 30 s deadline mistook the latter
# for a stall (2026-09-04). EXPECTED is the forecast threshold scored in
# the ledger; the wait itself is progress-based (APPLYING resets patience)
# under the outer NET, and STALL is how long without a state change before
# the wait warns.
QUEUE_SHARE_APPLY_EXPECTED_S = 30.0
QUEUE_SHARE_APPLY_STALL_S = 120.0
QUEUE_SHARE_APPLY_NET_S = 600.0
