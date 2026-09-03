"""Overwatch: the ACP + Grok judgement capability — its own capability,
distinct from Nautilus (the model-free watcher that escalates here).
Structurally immune to local-model outages.

Overwatch is invoked event-driven (never cron) when Nautilus fires a
trigger whose question deterministic verification cannot settle.

Independence properties (the load-bearing part):
- ``JUDGE_AGENT = "grok"`` is a FROZEN constant — never
  ``load_acp_agent_selection()``, whose default "thinking" routes
  grok-build through the local engine at 127.0.0.1:9890 (Engine/Complete)
  — the exact circular dependency that failed on 2026-09-01 when the
  incident under diagnosis WAS the thinking endpoint.
- Preflight requires the subscription credential (~/.grok/auth.json or
  XAI_API_KEY). Absent → FAIL CLOSED: record judge_unavailable, take no
  action, never fall back to thinking. Detection is unaffected.
- Contract-gated verdict: exactly one JSON object
  ``{in_contract, diagnosis, recommended_action, confidence}``.
  ``in_contract=true → recommend nothing`` is a first-class outcome.
  Malformed/missing JSON → judge_error, no action, no default-to-success.
- The judge is a scored forecaster: every verdict is recorded as a
  ``judge:overwatch-grok`` forecast in the efficacy ledger and resolved
  by subsequent deterministic observations or operator gold.

Autonomy: v1 is ``monitor`` (record + report). ``propose`` wiring exists
via the aiops approval machinery; promotion is gated on the judge's OWN
ledger calibration (n>=10 resolved, Brier < 0.25) — the system eating
its own dogfood.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# FROZEN. Not configurable by env or config the judge's own actions could
# reach (the PROVIDER_AFFECTING_KEYS discipline from Atelier).
JUDGE_AGENT = "grok"

MAX_JUDGE_INVOCATIONS_PER_DAY = 6

# Objective rubric judgments (LLM-as-Judge on the final surfaced result)
# have their own budget so they never starve trigger consultations.
MAX_RUBRIC_JUDGMENTS_PER_DAY = 8

VERDICT_KEYS = {"in_contract", "diagnosis", "recommended_action", "confidence"}

RUBRIC_VERDICT_KEYS = {"sufficient", "items", "note", "confidence"}

ALLOWED_ACTIONS = {
    "none",
    "report",
    "propose_restart_endpoint",
    "propose_restart_engine",
    "propose_config_change",
    "propose_escalate_github",
}


class OverwatchJudge:
    """Wraps one event-driven ACP+Grok consultation."""

    def __init__(self) -> None:
        self._invocations_today = 0
        self._rubric_today = 0
        self._counter_date: date = date.today()

    def _roll_date(self) -> None:
        today = date.today()
        if today != self._counter_date:
            self._counter_date = today
            self._invocations_today = 0
            self._rubric_today = 0

    def _budget_ok(self) -> bool:
        self._roll_date()
        return self._invocations_today < MAX_JUDGE_INVOCATIONS_PER_DAY

    def _rubric_budget_ok(self) -> bool:
        self._roll_date()
        return self._rubric_today < MAX_RUBRIC_JUDGMENTS_PER_DAY

    @staticmethod
    def preflight() -> str | None:
        """Fail-closed availability check. Returns an error string when
        the grok subscription path is unavailable, else None."""
        try:
            from gaius.acp.client import resolve_acp_agent

            resolve_acp_agent(JUDGE_AGENT)
            return None
        except Exception as e:  # noqa: BLE001 — the reason is the payload
            return str(e)

    async def consult(
        self,
        trigger: str,
        scope: str,
        detail: str,
        snapshot_markdown: str,
        ledger_report: list[dict[str, Any]],
        healing_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """One consultation. Returns a judge event payload; never raises.

        Outcomes: {"status": "verdict", "verdict": {...}} |
                  {"status": "judge_unavailable", "reason": ...} |
                  {"status": "judge_error", "reason": ...} |
                  {"status": "budget_exhausted"}
        """
        if not self._budget_ok():
            logger.warning(
                "#OW.00000003.BUDGET judge budget exhausted "
                f"({MAX_JUDGE_INVOCATIONS_PER_DAY}/day) — detection continues"
            )
            return {"status": "budget_exhausted"}

        unavailable = self.preflight()
        if unavailable is not None:
            logger.warning(
                f"#OW.00000001.JUDGEDOWN grok judge unavailable — fail "
                f"closed, NO thinking fallback: {unavailable}"
            )
            return {"status": "judge_unavailable", "reason": unavailable}

        self._invocations_today += 1
        prompt = self._build_prompt(
            trigger, scope, detail, snapshot_markdown, ledger_report,
            healing_context or [],
        )

        try:
            from gaius.acp import ACPConfig, GaiusACPClient

            async with GaiusACPClient(
                ACPConfig(
                    agent=JUDGE_AGENT,
                    auto_approve_terminal=False,  # judge reads, never mutates
                    auto_approve_fs=False,
                    include_gaius_mcp=False,
                )
            ) as client:
                response = await client.prompt(message=prompt)
        except Exception as e:  # noqa: BLE001 — recorded, never masked
            logger.warning(f"#OW.00000002.JUDGEERR judge consultation failed: {e}")
            return {"status": "judge_error", "reason": str(e)[:500]}

        verdict = self._parse_verdict(response or "")
        if verdict is None:
            logger.warning(
                "#OW.00000002.JUDGEERR judge returned no parseable verdict "
                "JSON — no action, no default-to-success"
            )
            return {
                "status": "judge_error",
                "reason": "no parseable verdict JSON",
                "raw_tail": (response or "")[-400:],
            }

        await self._record_forecast(trigger, scope, verdict)
        return {"status": "verdict", "verdict": verdict}

    async def judge_rubric(
        self,
        objective: str,
        surface: str,
        rubric: str,
        artifacts: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """LLM-as-Judge FINAL CALL on an objective's surfaced result.

        The judge reasons about the artifact the user actually receives,
        against the objective's explicit quality rubric, and renders the
        verdict that resolves the forecast chain (Brier propagation
        follows this call). Fail-closed: unavailable/budget/error never
        falls back to a local model.

        Outcomes mirror consult():
            {"status": "verdict", "verdict": {sufficient, items, note,
             confidence}} | judge_unavailable | judge_error |
            budget_exhausted
        """
        if not self._rubric_budget_ok():
            logger.warning(
                "#OW.00000003.BUDGET rubric judge budget exhausted "
                f"({MAX_RUBRIC_JUDGMENTS_PER_DAY}/day) — objective gate "
                "records an error verdict, never a default"
            )
            return {"status": "budget_exhausted"}

        unavailable = self.preflight()
        if unavailable is not None:
            logger.warning(
                f"#OW.00000001.JUDGEDOWN grok judge unavailable — fail "
                f"closed, NO thinking fallback: {unavailable}"
            )
            return {"status": "judge_unavailable", "reason": unavailable}

        self._rubric_today += 1
        blocks = "\n\n".join(
            f"--- {name} ---\n{text[:4000]}" for name, text in artifacts[:5]
        )
        prompt = f"""You are the Gaius Overwatch judge — an INDEPENDENT reviewer running
on Grok, deliberately outside the local model stack. This is an
OBJECTIVE RUBRIC judgment (LLM-as-Judge): you make the FINAL CALL on
whether the final surfaced result the user receives is sufficient to
the task. Internal checks and local-model scores are forecasts that
will be Brier-scored against your call.

OBJECTIVE: {objective}
USER SURFACE: {surface}

QUALITY RUBRIC (score each item 0 or 1 over the artifact set):
{rubric}

ARTIFACTS (verbatim — what the user actually receives):
{blocks}

Rules:
- Judge ONLY what is in front of you: the artifact text, never the
  machinery that produced it.
- sufficient=true means a reader opening these artifacts is adequately
  served for the objective's task; hollow, malformed, or padded
  content is NOT sufficient.
- Your FINAL message must be exactly one JSON object and nothing after it
  — no prose, no code fence, no trailing commentary. Reasoning before it
  is fine; the object must be last and complete:
{{"sufficient": bool, "items": {{"<rubric item>": 0 or 1, ...}},
 "note": "one line", "confidence": 0.0-1.0}}"""

        try:
            from gaius.acp import ACPConfig, GaiusACPClient

            async with GaiusACPClient(
                ACPConfig(
                    agent=JUDGE_AGENT,
                    auto_approve_terminal=False,  # judge reads, never mutates
                    auto_approve_fs=False,
                    include_gaius_mcp=False,
                )
            ) as client:
                response = await client.prompt(message=prompt)
        except Exception as e:  # noqa: BLE001 — recorded, never masked
            logger.warning(f"#OW.00000002.JUDGEERR rubric judgment failed: {e}")
            return {"status": "judge_error", "reason": str(e)[:500]}

        verdict = self._parse_rubric_verdict(response or "")
        if verdict is None:
            logger.warning(
                "#OW.00000002.JUDGEERR rubric judge returned no parseable "
                "verdict JSON — error verdict, no default-to-success; "
                f"reply tail: {(response or '')[-600:]!r}"
            )
            return {
                "status": "judge_error",
                "reason": "no parseable rubric verdict JSON",
                "raw_tail": (response or "")[-400:],
            }

        await self._record_rubric_forecast(objective, surface, verdict)
        return {"status": "verdict", "verdict": verdict}

    @staticmethod
    def _candidate_json_objects(text: str) -> list[str]:
        """Every balanced top-level {...} span in text, in order.

        A greedy `\\{.*\\}` across a long agent reply swallows everything
        between the first and last brace and never parses (2026-09-03:
        a 30-minute rubric consultation lost to "no parseable verdict").
        Brace-match instead and let the caller pick the LAST object that
        carries the verdict keys."""
        out: list[str] = []
        depth = 0
        start = -1
        in_str = False
        esc = False
        for i, ch in enumerate(text):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
                    start = -1
        return out

    @classmethod
    def _parse_rubric_verdict(cls, response: str) -> dict[str, Any] | None:
        verdict: dict[str, Any] | None = None
        # Prefer the LAST well-formed object carrying the verdict keys — the
        # agent's final answer, after any tool chatter or reasoning.
        for raw in reversed(cls._candidate_json_objects(response or "")):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and RUBRIC_VERDICT_KEYS.issubset(obj):
                verdict = obj
                break
        if verdict is None:
            return None
        verdict["sufficient"] = bool(verdict["sufficient"])
        if not isinstance(verdict.get("items"), dict):
            verdict["items"] = {}
        try:
            verdict["confidence"] = max(0.0, min(1.0, float(verdict["confidence"])))
        except (TypeError, ValueError):
            verdict["confidence"] = 0.5
        return verdict

    @staticmethod
    async def _record_rubric_forecast(
        objective: str, surface: str, verdict: dict[str, Any]
    ) -> None:
        """The judge's rubric call is itself Brier-scored (resolved gold
        by the human at the CLI, or by later surface observations)."""
        try:
            from gaius.engine.services.efficacy_ledger import get_ledger

            ledger = get_ledger()
            if ledger is None:
                return
            conf = float(verdict["confidence"])
            await ledger.record_forecast(
                observer="judge:overwatch-grok",
                observer_kind="judge",
                call_site="overwatch_judge.judge_rubric",
                proposition=(
                    f"{objective} surfaced result ({surface}) is "
                    "sufficient per rubric"
                ),
                verdict="pass" if verdict["sufficient"] else "fail",
                p=conf if verdict["sufficient"] else 1.0 - conf,
                evidence={
                    "items": verdict.get("items"),
                    "note": str(verdict.get("note", ""))[:200],
                },
                model_id="grok",
            )
        except Exception:  # noqa: BLE001 — ledger is fail-open
            logger.debug("rubric judge forecast record skipped", exc_info=True)

    @staticmethod
    def _build_prompt(
        trigger: str,
        scope: str,
        detail: str,
        snapshot_markdown: str,
        ledger_report: list[dict[str, Any]],
        healing_context: list[dict[str, Any]],
    ) -> str:
        ledger_lines = "\n".join(
            f"- {r['observer']} @{r.get('call_site','?')} "
            f"[{r.get('momentum_bucket')}]: Brier={r.get('brier')} "
            f"α={r.get('alpha')} (n={r.get('resolved')}/{r.get('n')})"
            for r in ledger_report[:20]
        ) or "- (no calibrated observers yet)"
        healing_lines = "\n".join(
            f"- {e.get('event_type')} t{e.get('tier')} {e.get('created_at')}"
            for e in healing_context[:15]
        ) or "- (none)"
        return f"""You are the Gaius Overwatch judge — an INDEPENDENT reviewer running
on Grok, deliberately outside the local model stack, consulted because
the Nautilus detector fired a trigger that deterministic verification
could not settle.

TRIGGER: {trigger} (scope: {scope})
DETAIL: {detail}

PROBE CALIBRATION (Brier-scored efficacy ledger — a poorly-scored
observer's verdicts deserve salt; do not treat any single probe as
ground truth):
{ledger_lines}

RECENT HEALING EVENTS for this scope:
{healing_lines}

SYSTEM SNAPSHOT:
{snapshot_markdown}

Contract-gated verdict rules:
- If the signals are within normal operating tolerances, say so:
  in_contract=true and recommended_action="none". Recommending nothing
  is a first-class, expected outcome — do not invent work.
- recommended_action MUST be one of: none, report,
  propose_restart_endpoint, propose_restart_engine,
  propose_config_change, propose_escalate_github.
- You are in MONITOR autonomy: nothing you recommend executes
  automatically; proposals go to the operator approval queue.

Respond with EXACTLY one JSON object and nothing else:
{{"in_contract": bool, "diagnosis": "one paragraph",
 "recommended_action": "<action>", "confidence": 0.0-1.0}}"""

    @staticmethod
    def _parse_verdict(response: str) -> dict[str, Any] | None:
        m = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
        raw = m.group(1) if m else None
        if raw is None:
            m = re.search(r"\{[^{}]*\"in_contract\"[^{}]*\}", response, re.DOTALL)
            raw = m.group(0) if m else None
        if raw is None:
            return None
        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not VERDICT_KEYS.issubset(verdict):
            return None
        action = str(verdict.get("recommended_action", "")).strip()
        if action not in ALLOWED_ACTIONS:
            # Unknown verbs are dropped to "report" — provenance-tagged
            # merge discipline: unknown keys never execute.
            verdict["recommended_action"] = "report"
            verdict["unknown_action_dropped"] = action
        try:
            verdict["confidence"] = max(0.0, min(1.0, float(verdict["confidence"])))
        except (TypeError, ValueError):
            verdict["confidence"] = 0.5
        return verdict

    @staticmethod
    async def _record_forecast(
        trigger: str, scope: str, verdict: dict[str, Any]
    ) -> None:
        """The judge is Brier-scored like everyone else."""
        try:
            from gaius.engine.services.efficacy_ledger import get_ledger

            ledger = get_ledger()
            if ledger is None:
                return
            # in_contract=true claims "nothing is wrong in this scope";
            # in_contract=false claims the diagnosis identifies a real
            # fault. Both are falsifiable by subsequent observations.
            proposition = (
                f"{scope} is within contract per {trigger}"
                if verdict["in_contract"]
                else f"{scope} fault: {str(verdict.get('diagnosis', ''))[:120]}"
            )
            await ledger.record_forecast(
                observer="judge:overwatch-grok",
                observer_kind="judge",
                call_site="overwatch_judge.consult",
                proposition=proposition,
                verdict="pass",
                p=float(verdict["confidence"]),
                evidence={
                    "trigger": trigger,
                    "recommended_action": verdict["recommended_action"],
                },
                model_id="grok",
            )
        except Exception:  # noqa: BLE001 — ledger is fail-open
            logger.debug("judge forecast record skipped", exc_info=True)


_JUDGE: OverwatchJudge | None = None


def get_judge() -> OverwatchJudge:
    """Process-wide judge instance — trigger consultations and rubric
    judgments share one set of daily budget counters."""
    global _JUDGE
    if _JUDGE is None:
        _JUDGE = OverwatchJudge()
    return _JUDGE


_ENV_FLAG = "GAIUS_OVERWATCH_AUTONOMY"


def autonomy_tier() -> str:
    """monitor (default) | propose. `autonomous` is deliberately not
    implemented in v1."""
    tier = os.environ.get(_ENV_FLAG, "monitor").strip().lower()
    return tier if tier in ("monitor", "propose") else "monitor"
