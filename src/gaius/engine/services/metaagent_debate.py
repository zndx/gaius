"""Multi-Agent Debate coordinator for MetaAgent audits.

Implements the 5-phase debate flow (SOTA LLM agent architecture):
1. Data Gathering (existing MetaAgentManager - SQL queries)
2. Initial Analysis (Cerebras GLM 4.7 - fast synthesis)
3. Skeptic Critique (XAI Grok - adversarial review)
4. Actionability Validation (Cerebras - command validation)
5. Judge Synthesis (XAI Grok - final verdict)

This architecture overcomes "Degeneration-of-Thought" (Du et al., 2023) where
single-agent systems become overconfident. Multi-Agent Debate provides:
- Adversarial critique that challenges assumptions
- Actionability validation ensuring recommendations are executable
- Balanced synthesis weighing evidence from both sides

All LLM calls use source_context for HX exchange tracking, enabling:
- Full lineage from LLM calls to KB artifacts
- Budget tracking via PooledBudgetManager
- Auditability via raw.exchange table

Guru Meditation Codes:
- #MA.DEBATE.00000001.GATHERINGFAIL - Data gathering phase failed
- #MA.DEBATE.00000002.ANALYSISFAIL - Initial analysis phase failed
- #MA.DEBATE.00000003.SKEPTICFAIL - Skeptic critique phase failed
- #MA.DEBATE.00000004.CRITICFAIL - Actionability validation failed
- #MA.DEBATE.00000005.JUDGEFAIL - Judge synthesis failed
- #MA.DEBATE.00000006.NOXAI - XAI backend not available
- #MA.DEBATE.00000007.NOCEREBRAS - Cerebras backend not available
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import asyncpg

if TYPE_CHECKING:
    from gaius.engine.backends.external.base import ExternalResponse
    from gaius.engine.backends.external.router import ExternalInferenceRouter

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DebateTranscript:
    """Record of the multi-agent debate for transparency.

    Stores each phase's output plus exchange IDs for HX lineage.
    """

    initial_analysis: str = ""
    skeptic_critique: str = ""
    actionability_assessment: str = ""
    judge_synthesis: str = ""
    exchange_ids: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Format debate as markdown for KB storage."""
        return f"""# Audit Debate Transcript

Generated: {datetime.now().isoformat()}

## Phase 2: Initial Analysis

{self.initial_analysis}

---

## Phase 3: Skeptic Critique

{self.skeptic_critique}

---

## Phase 4: Actionability Assessment

{self.actionability_assessment}

---

## Phase 5: Judge Synthesis

{self.judge_synthesis}

---

## Lineage

Exchange IDs: {', '.join(self.exchange_ids) if self.exchange_ids else 'None'}
"""


@dataclass
class Finding:
    """A finding from the audit with confidence tracking."""

    title: str
    description: str
    evidence: list[str]
    initial_confidence: float
    final_confidence: float
    confidence_delta: float
    skeptic_concerns: list[str]
    status: str  # confirmed, qualified, dismissed


@dataclass
class Recommendation:
    """An actionable recommendation."""

    title: str
    description: str
    commands: list[str]
    prerequisites: list[str]
    effort: str  # immediate, short-term, long-term
    risks: list[str]
    rollback: str
    priority: int


@dataclass
class DebateResult:
    """Final result of the multi-agent debate."""

    findings: list[Finding]
    recommendations: list[Recommendation]
    transcript: DebateTranscript
    verdict_summary: str
    total_llm_calls: int
    total_tokens: int
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Check if debate completed successfully."""
        return self.error is None


# ═══════════════════════════════════════════════════════════════════════════
# System Prompts
# ═══════════════════════════════════════════════════════════════════════════

ANALYST_PROMPT = """You are a systems analyst synthesizing operational data into findings.

Given data from multiple sources:
- Health incidents from the health_incidents table
- GPU utilization and memory metrics
- Endpoint status and recent failures
- System observations and anomalies

Your task is to produce findings in this structured format:

## Finding: [Title]
- Severity: [critical/high/medium/low]
- Confidence: [0.0-1.0]
- Evidence:
  - [Specific data point from the input]
  - [Another supporting observation]
- Recommendation: [What action to take]

Be specific and cite actual data from the input. Do not fabricate metrics.
If the data is sparse, acknowledge that and adjust confidence accordingly.
"""

SKEPTIC_PROMPT = """You are a skeptical analyst who challenges assumptions and identifies blind spots.

Your role in this Multi-Agent Debate is to:
1. Question the evidence quality behind each finding
2. Identify alternative explanations for observed patterns
3. Challenge causal claims - distinguish correlation from causation
4. Point out what data is MISSING that would strengthen conclusions
5. Rate confidence adjustments (-0.3 to 0) for each finding

Be constructively critical. Your goal is to make the analysis stronger, not to dismiss it.
The goal is robust findings that survive adversarial scrutiny.

For each finding, output:
## Critique of Finding: [title]
- Evidence Quality: [weak/moderate/strong]
- Alternative Explanations: [list plausible alternatives]
- Missing Data: [what evidence would help]
- Causal Concerns: [if causal claims made]
- Confidence Adjustment: [-0.X] with reasoning
"""

ACTIONABILITY_CRITIC_PROMPT = """You are an operations expert who validates that recommendations are actually executable.

You know the Gaius system well:
- /health fix commands for automated remediation
- devenv tasks for infrastructure management
- CLI commands (/gpu status, /evolve status, etc.)
- Engine restart procedures

For each recommendation, evaluate:
1. Is this actionable with current tools?
2. What specific commands would implement this?
3. Are prerequisites met? (permissions, resources, system state)
4. What is the estimated effort? (immediate/short-term/long-term)
5. What could go wrong? (rollback plan needed?)

Output format for each recommendation:
## Recommendation: [title]
- Actionable: [yes/partial/no]
- Commands: [list specific commands]
- Prerequisites: [list requirements, or "none"]
- Effort: [immediate (<5 min) / short-term (<1 hour) / long-term (>1 day)]
- Risks: [what could go wrong]
- Rollback: [how to undo if needed]
"""

JUDGE_PROMPT = """You are the final arbiter synthesizing the debate between analyst and skeptic.

You have received:
1. Initial findings from the analyst (Phase 2)
2. Critique from the skeptic (Phase 3)
3. Actionability assessment from the critic (Phase 4)

Your task:
1. Weigh evidence quality vs skeptic's concerns
2. Adjust confidence scores based on the debate
3. Prioritize recommendations by actionability and impact
4. Produce a final verdict with clear reasoning

Output your verdict in this format:

## Final Verdict

### Confirmed Findings (High Confidence)
[Findings that survived skeptic critique with strong evidence]
- Finding: [title]
  - Original Confidence: X.X
  - Final Confidence: X.X
  - Reasoning: [why it survived critique]

### Qualified Findings (Medium Confidence)
[Findings with valid concerns that warrant caution]
- Finding: [title]
  - Original Confidence: X.X
  - Final Confidence: X.X
  - Caveats: [what the skeptic raised that applies]

### Dismissed Findings
[Findings that skeptic successfully challenged]
- Finding: [title]
  - Reason for Dismissal: [what critique was fatal]

### Prioritized Recommendations
1. [Most actionable + highest impact] - Commands: [...]
2. [Second priority] - Commands: [...]

### Overall Assessment
[Summary paragraph of system health and key actions needed]
"""


# ═══════════════════════════════════════════════════════════════════════════
# Debate Coordinator
# ═══════════════════════════════════════════════════════════════════════════


class MetaAgentDebateCoordinator:
    """Coordinates Multi-Agent Debate for audit analysis.

    Implements the 5-phase debate flow with proper HX exchange tracking.
    Each LLM call includes source_context for lineage and budget tracking.

    Budget Allocation (Quality-First strategy):
    - Phase 2 (Initial Analysis): Cerebras GLM 4.7 (~1 call, ~4K tokens)
    - Phase 3 (Skeptic Critique): XAI Grok (~1 call, ~4K tokens) - ALWAYS
    - Phase 4 (Actionability): Cerebras GLM 4.7 (~1-3 calls, ~2K each)
    - Phase 5 (Judge Synthesis): XAI Grok (~1 call, ~4K tokens) - ALWAYS

    Total: ~5-6 LLM calls per audit, ~18K tokens.
    """

    def __init__(
        self,
        pool: asyncpg.Pool | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        """Initialize debate coordinator.

        Args:
            pool: Database connection pool for data gathering
            parent_run_id: Optional parent run ID for lineage nesting
        """
        self._pool = pool
        self._parent_run_id = parent_run_id
        self._router: ExternalInferenceRouter | None = None
        self._transcript = DebateTranscript()
        self._total_calls = 0
        self._total_tokens = 0

    def _get_router(self) -> "ExternalInferenceRouter":
        """Lazily get the external inference router."""
        if self._router is None:
            from gaius.engine.backends.external.router import get_external_router
            self._router = get_external_router()
        return self._router

    def _get_source_context(self, agent_alias: str, task_type: str) -> dict[str, Any]:
        """Build source_context for HX tracking.

        Args:
            agent_alias: Agent making the call (metaagent_analyst, etc.)
            task_type: Type of task (initial_analysis, etc.)

        Returns:
            Dict suitable for router.complete(source_context=...)
        """
        from gaius.engine.services.llm_exchange_context import get_source_context
        return get_source_context(
            agent_alias=agent_alias,
            task_type=task_type,
            parent_run_id=self._parent_run_id,
        )

    def _track_exchange(self, response: "ExternalResponse") -> None:
        """Track exchange for HX lineage and budget.

        Args:
            response: ExternalResponse from router.complete()
        """
        if response.exchange_id:
            self._transcript.exchange_ids.append(response.exchange_id)
        self._total_calls += 1
        self._total_tokens += response.input_tokens + response.output_tokens

    async def run_debate(self, scope: str) -> DebateResult:
        """Execute the full 5-phase debate flow.

        Args:
            scope: Audit scope (full, health, performance, etc.)

        Returns:
            DebateResult with findings, recommendations, and transcript
        """
        logger.info(f"Starting Multi-Agent Debate for scope: {scope}")

        # Verify backends available
        router = self._get_router()
        if "xai" not in router.available_backends:
            error = (
                "XAI backend not available. Multi-Agent Debate requires XAI for "
                "Skeptic and Judge phases (Quality-First strategy).\n"
                "  Set XAI_API_KEY environment variable.\n"
                "  Guru Meditation: #MA.DEBATE.00000006.NOXAI"
            )
            logger.error(error)
            return DebateResult(
                findings=[],
                recommendations=[],
                transcript=self._transcript,
                verdict_summary="",
                total_llm_calls=0,
                total_tokens=0,
                error=error,
            )

        if "cerebras" not in router.available_backends:
            error = (
                "Cerebras backend not available. Multi-Agent Debate requires Cerebras for "
                "Initial Analysis and Actionability phases.\n"
                "  Set CEREBRAS_API_KEY environment variable.\n"
                "  Guru Meditation: #MA.DEBATE.00000007.NOCEREBRAS"
            )
            logger.error(error)
            return DebateResult(
                findings=[],
                recommendations=[],
                transcript=self._transcript,
                verdict_summary="",
                total_llm_calls=0,
                total_tokens=0,
                error=error,
            )

        try:
            # Phase 1: Data Gathering (no LLM)
            logger.info("Phase 1: Data Gathering (SQL queries)")
            gathered_data = await self._gather_data(scope)

            # Phase 2: Initial Analysis (Cerebras)
            logger.info("Phase 2: Initial Analysis (Cerebras)")
            initial_findings = await self._run_initial_analysis(gathered_data)

            # Phase 3: Skeptic Critique (XAI - always)
            logger.info("Phase 3: Skeptic Critique (XAI Grok)")
            critique = await self._run_skeptic_critique(initial_findings)

            # Phase 4: Actionability Validation (Cerebras)
            logger.info("Phase 4: Actionability Validation (Cerebras)")
            actionability = await self._run_actionability_check(initial_findings)

            # Phase 5: Judge Synthesis (XAI - always)
            logger.info("Phase 5: Judge Synthesis (XAI Grok)")
            result = await self._run_judge_synthesis(
                initial_findings, critique, actionability
            )

            logger.info(
                f"Multi-Agent Debate complete: {self._total_calls} LLM calls, "
                f"{self._total_tokens} tokens"
            )

            return result

        except Exception as e:
            error = f"Multi-Agent Debate failed: {e}"
            logger.error(error)
            return DebateResult(
                findings=[],
                recommendations=[],
                transcript=self._transcript,
                verdict_summary="",
                total_llm_calls=self._total_calls,
                total_tokens=self._total_tokens,
                error=error,
            )

    async def _gather_data(self, scope: str) -> dict[str, Any]:
        """Phase 1: Gather data via SQL queries (no LLM).

        Args:
            scope: Audit scope

        Returns:
            Dict with gathered data from multiple sources
        """
        data: dict[str, Any] = {
            "scope": scope,
            "gathered_at": datetime.now().isoformat(),
            "health_incidents": [],
            "gpu_metrics": {},
            "endpoint_status": [],
        }

        if self._pool is None:
            logger.warning("No database pool provided, returning minimal data")
            return data

        try:
            async with self._pool.acquire() as conn:
                # Get recent unresolved health incidents
                incidents = await conn.fetch(
                    """
                    SELECT fingerprint, status, rpn_score, failure_mode_id,
                           first_seen, last_seen, attempt_count
                    FROM health_incidents
                    WHERE status != 'resolved'
                    ORDER BY rpn_score DESC
                    LIMIT 10
                    """
                )
                data["health_incidents"] = [dict(r) for r in incidents]

                # Get recent GPU utilization
                gpu_rows = await conn.fetch(
                    """
                    SELECT gpu_index, memory_used_mb, memory_total_mb,
                           utilization_percent, active_endpoint
                    FROM meta.gpu_utilization
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                    ORDER BY timestamp DESC
                    LIMIT 8
                    """
                )
                data["gpu_metrics"] = [dict(r) for r in gpu_rows]

        except Exception as e:
            logger.warning(
                f"Data gathering partial failure: {e}\n"
                f"  Guru Meditation: #MA.DEBATE.00000001.GATHERINGFAIL"
            )
            data["gathering_error"] = str(e)

        return data

    async def _run_initial_analysis(self, data: dict[str, Any]) -> str:
        """Phase 2: Synthesize data into preliminary findings (Cerebras).

        Args:
            data: Gathered data from Phase 1

        Returns:
            Initial analysis text with findings
        """
        # Format data for the analyst
        formatted_data = self._format_data_for_analysis(data)

        router = self._get_router()
        response = await router.complete(
            messages=[
                {"role": "system", "content": ANALYST_PROMPT},
                {"role": "user", "content": f"Analyze this operational data:\n\n{formatted_data}"},
            ],
            provider="cerebras",
            max_tokens=4096,
            temperature=0.3,
            source_context=self._get_source_context(
                agent_alias="metaagent_analyst",
                task_type="initial_analysis",
            ),
        )

        if response.error:
            logger.error(
                f"Initial analysis failed: {response.error}\n"
                f"  Guru Meditation: #MA.DEBATE.00000002.ANALYSISFAIL"
            )
            self._transcript.initial_analysis = f"ERROR: {response.error}"
            return ""

        self._track_exchange(response)
        self._transcript.initial_analysis = response.content
        return response.content

    async def _run_skeptic_critique(self, findings: str) -> str:
        """Phase 3: Challenge findings with XAI (always frontier quality).

        Args:
            findings: Initial analysis from Phase 2

        Returns:
            Skeptic critique text
        """
        if not findings:
            self._transcript.skeptic_critique = "SKIPPED: No findings to critique"
            return ""

        router = self._get_router()
        response = await router.complete(
            messages=[
                {"role": "system", "content": SKEPTIC_PROMPT},
                {"role": "user", "content": f"Critique these findings:\n\n{findings}"},
            ],
            provider="xai",  # Always XAI for skeptic (Quality-First)
            max_tokens=4096,
            temperature=0.3,
            source_context=self._get_source_context(
                agent_alias="metaagent_skeptic",
                task_type="skeptic_critique",
            ),
        )

        if response.error:
            logger.error(
                f"Skeptic critique failed: {response.error}\n"
                f"  Guru Meditation: #MA.DEBATE.00000003.SKEPTICFAIL"
            )
            self._transcript.skeptic_critique = f"ERROR: {response.error}"
            return ""

        self._track_exchange(response)
        self._transcript.skeptic_critique = response.content
        return response.content

    async def _run_actionability_check(self, findings: str) -> str:
        """Phase 4: Validate recommendations are executable (Cerebras).

        Args:
            findings: Initial analysis from Phase 2

        Returns:
            Actionability assessment text
        """
        if not findings:
            self._transcript.actionability_assessment = "SKIPPED: No findings to validate"
            return ""

        router = self._get_router()
        response = await router.complete(
            messages=[
                {"role": "system", "content": ACTIONABILITY_CRITIC_PROMPT},
                {"role": "user", "content": f"Validate actionability of recommendations in:\n\n{findings}"},
            ],
            provider="cerebras",
            max_tokens=4096,
            temperature=0.2,  # Very deterministic for commands
            source_context=self._get_source_context(
                agent_alias="metaagent_critic",
                task_type="actionability_critique",
            ),
        )

        if response.error:
            logger.error(
                f"Actionability check failed: {response.error}\n"
                f"  Guru Meditation: #MA.DEBATE.00000004.CRITICFAIL"
            )
            self._transcript.actionability_assessment = f"ERROR: {response.error}"
            return ""

        self._track_exchange(response)
        self._transcript.actionability_assessment = response.content
        return response.content

    async def _run_judge_synthesis(
        self, findings: str, critique: str, actionability: str
    ) -> DebateResult:
        """Phase 5: Final synthesis with XAI (always frontier quality).

        Args:
            findings: Initial analysis from Phase 2
            critique: Skeptic critique from Phase 3
            actionability: Actionability assessment from Phase 4

        Returns:
            Complete DebateResult with parsed findings and recommendations
        """
        combined_input = f"""## Initial Findings (Phase 2)
{findings or 'No initial findings generated.'}

## Skeptic Critique (Phase 3)
{critique or 'Skeptic phase skipped or failed.'}

## Actionability Assessment (Phase 4)
{actionability or 'Actionability phase skipped or failed.'}
"""
        router = self._get_router()
        response = await router.complete(
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": combined_input},
            ],
            provider="xai",  # Always XAI for judge (Quality-First)
            max_tokens=4096,
            temperature=0.4,
            source_context=self._get_source_context(
                agent_alias="metaagent_judge",
                task_type="judge_synthesis",
            ),
        )

        if response.error:
            logger.error(
                f"Judge synthesis failed: {response.error}\n"
                f"  Guru Meditation: #MA.DEBATE.00000005.JUDGEFAIL"
            )
            self._transcript.judge_synthesis = f"ERROR: {response.error}"
            return DebateResult(
                findings=[],
                recommendations=[],
                transcript=self._transcript,
                verdict_summary="",
                total_llm_calls=self._total_calls,
                total_tokens=self._total_tokens,
                error=f"Judge synthesis failed: {response.error}",
            )

        self._track_exchange(response)
        self._transcript.judge_synthesis = response.content

        # Parse judge output into structured result
        parsed_findings, parsed_recommendations = self._parse_judge_output(response.content)

        return DebateResult(
            findings=parsed_findings,
            recommendations=parsed_recommendations,
            transcript=self._transcript,
            verdict_summary=response.content,
            total_llm_calls=self._total_calls,
            total_tokens=self._total_tokens,
        )

    def _format_data_for_analysis(self, data: dict[str, Any]) -> str:
        """Format gathered data as readable text for LLM analysis.

        Args:
            data: Gathered data dict

        Returns:
            Formatted string for LLM consumption
        """
        lines = [
            f"## Audit Data (scope: {data.get('scope', 'unknown')})",
            f"Gathered at: {data.get('gathered_at', 'unknown')}",
            "",
        ]

        # Health incidents
        incidents = data.get("health_incidents", [])
        if incidents:
            lines.append("### Health Incidents")
            for inc in incidents:
                lines.append(
                    f"- {inc.get('fingerprint', 'unknown')}: "
                    f"status={inc.get('status')}, RPN={inc.get('rpn_score')}, "
                    f"failure_mode={inc.get('failure_mode_id')}"
                )
            lines.append("")
        else:
            lines.append("### Health Incidents")
            lines.append("No unresolved incidents.")
            lines.append("")

        # GPU metrics
        gpu_metrics = data.get("gpu_metrics", [])
        if gpu_metrics:
            lines.append("### GPU Metrics (last hour)")
            for gm in gpu_metrics:
                lines.append(
                    f"- GPU {gm.get('gpu_index', '?')}: "
                    f"{gm.get('memory_used_mb', 0)}/{gm.get('memory_total_mb', 0)} MB, "
                    f"{gm.get('utilization_percent', 0)}% util, "
                    f"endpoint={gm.get('active_endpoint', 'none')}"
                )
            lines.append("")
        else:
            lines.append("### GPU Metrics")
            lines.append("No GPU metrics available.")
            lines.append("")

        # Note any gathering errors
        if data.get("gathering_error"):
            lines.append("### Data Gathering Notes")
            lines.append(f"Warning: {data.get('gathering_error')}")
            lines.append("")

        return "\n".join(lines)

    def _parse_judge_output(
        self, content: str
    ) -> tuple[list[Finding], list[Recommendation]]:
        """Parse judge synthesis into structured findings and recommendations.

        Args:
            content: Raw judge output text

        Returns:
            Tuple of (findings, recommendations)
        """
        findings: list[Finding] = []
        recommendations: list[Recommendation] = []

        # Parse confirmed findings
        confirmed_match = re.search(
            r"### Confirmed Findings.*?(?=###|\Z)", content, re.DOTALL
        )
        if confirmed_match:
            for finding_match in re.finditer(
                r"- Finding: ([^\n]+).*?Final Confidence: ([\d.]+)",
                confirmed_match.group(0),
                re.DOTALL,
            ):
                findings.append(
                    Finding(
                        title=finding_match.group(1).strip(),
                        description="",
                        evidence=[],
                        initial_confidence=0.0,
                        final_confidence=float(finding_match.group(2)),
                        confidence_delta=0.0,
                        skeptic_concerns=[],
                        status="confirmed",
                    )
                )

        # Parse qualified findings
        qualified_match = re.search(
            r"### Qualified Findings.*?(?=###|\Z)", content, re.DOTALL
        )
        if qualified_match:
            for finding_match in re.finditer(
                r"- Finding: ([^\n]+).*?Final Confidence: ([\d.]+)",
                qualified_match.group(0),
                re.DOTALL,
            ):
                findings.append(
                    Finding(
                        title=finding_match.group(1).strip(),
                        description="",
                        evidence=[],
                        initial_confidence=0.0,
                        final_confidence=float(finding_match.group(2)),
                        confidence_delta=0.0,
                        skeptic_concerns=[],
                        status="qualified",
                    )
                )

        # Parse prioritized recommendations
        rec_match = re.search(
            r"### Prioritized Recommendations.*?(?=###|\Z)", content, re.DOTALL
        )
        if rec_match:
            priority = 1
            for rec_line in re.finditer(
                r"^\d+\.\s*\[?([^\]\n]+)\]?.*?Commands?:\s*\[?([^\]\n]+)\]?",
                rec_match.group(0),
                re.MULTILINE,
            ):
                recommendations.append(
                    Recommendation(
                        title=rec_line.group(1).strip(),
                        description="",
                        commands=[cmd.strip() for cmd in rec_line.group(2).split(",")],
                        prerequisites=[],
                        effort="unknown",
                        risks=[],
                        rollback="",
                        priority=priority,
                    )
                )
                priority += 1

        return findings, recommendations


# ═══════════════════════════════════════════════════════════════════════════
# Module-level helpers
# ═══════════════════════════════════════════════════════════════════════════


def get_debate_coordinator(
    pool: asyncpg.Pool | None = None,
    parent_run_id: str | None = None,
) -> MetaAgentDebateCoordinator:
    """Create a new debate coordinator.

    Note: Unlike services, coordinators are NOT singletons.
    Each audit should create a fresh coordinator instance.

    Args:
        pool: Database connection pool
        parent_run_id: Optional parent run ID for lineage

    Returns:
        New MetaAgentDebateCoordinator instance
    """
    return MetaAgentDebateCoordinator(pool=pool, parent_run_id=parent_run_id)
