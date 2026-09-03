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
from gaius.core.budgets import EXTERNAL_MAX_TOKENS

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
    fused_opinion: "Opinion | None" = None

    @property
    def succeeded(self) -> bool:
        """Check if debate completed successfully."""
        return self.error is None


# ═══════════════════════════════════════════════════════════════════════════
# Subjective Logic Opinion (Jøsang 2016)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Opinion:
    """Subjective Logic opinion tuple ω = (b, d, u, a).

    Constraint: b + d + u = 1
    Where:
      b = belief (evidence supports claim)
      d = disbelief (evidence refutes claim)
      u = uncertainty (insufficient evidence)
      a = base rate (prior probability when uncertain)

    Reference: Jøsang 2016 "Subjective Logic: A Formalism for Reasoning
    Under Uncertainty"

    This enables explicit epistemic uncertainty tracking in the Agentic Judge
    phase, where each tool verification produces an opinion that can be
    fused with other opinions via cumulative or averaging fusion.
    """

    belief: float
    disbelief: float
    uncertainty: float
    base_rate: float = 0.5

    def __post_init__(self) -> None:
        """Validate the b + d + u = 1 constraint."""
        total = self.belief + self.disbelief + self.uncertainty
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Subjective Logic constraint violation: b + d + u must equal 1, "
                f"got {total:.4f} (b={self.belief}, d={self.disbelief}, u={self.uncertainty})"
            )

    @property
    def expected_probability(self) -> float:
        """Expected probability E[P] = b + a * u.

        When uncertainty is high, the expected probability moves toward
        the base rate. When evidence is strong (u → 0), the expected
        probability equals the belief.
        """
        return self.belief + self.base_rate * self.uncertainty

    @classmethod
    def vacuous(cls, base_rate: float = 0.5) -> "Opinion":
        """Create a vacuous opinion representing complete uncertainty.

        A vacuous opinion has no evidence (b=0, d=0, u=1), so the
        expected probability equals the base rate.
        """
        return cls(belief=0.0, disbelief=0.0, uncertainty=1.0, base_rate=base_rate)

    @classmethod
    def from_tool_result(cls, verified: bool, confidence: float = 0.8) -> "Opinion":
        """Create opinion from a tool verification result.

        Args:
            verified: Whether the tool verified the claim
            confidence: How confident the tool result is (default 0.8)

        Returns:
            Opinion with belief/disbelief proportional to confidence
        """
        uncertainty = 1.0 - confidence
        if verified:
            return cls(belief=confidence, disbelief=0.0, uncertainty=uncertainty)
        else:
            return cls(belief=0.0, disbelief=confidence, uncertainty=uncertainty)

    @classmethod
    def from_rase_verdict(cls, verdict_name: str, accuracy: float) -> "Opinion":
        """Create opinion from RASE verification result.

        Args:
            verdict_name: VerdictKind name (PASS, FAIL, INCONCLUSIVE, ERROR)
            accuracy: RASE accuracy score (0.0-1.0)

        Returns:
            Opinion reflecting the RASE verification outcome
        """
        if verdict_name == "PASS":
            return cls(belief=accuracy, disbelief=0.0, uncertainty=1.0 - accuracy)
        elif verdict_name == "FAIL":
            return cls(belief=0.0, disbelief=accuracy, uncertainty=1.0 - accuracy)
        else:  # INCONCLUSIVE, ERROR
            return cls.vacuous()

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary for serialization."""
        return {
            "belief": self.belief,
            "disbelief": self.disbelief,
            "uncertainty": self.uncertainty,
            "base_rate": self.base_rate,
            "expected_probability": self.expected_probability,
        }


def cumulative_fusion(opinions: list[Opinion]) -> Opinion:
    """Combine multiple independent opinions via averaging fusion.

    This is a simplified version of Jøsang's cumulative fusion operator.
    For the full cumulative fusion with proper uncertainty handling, see
    Jøsang 2016 Chapter 12.

    For Gaius's Agentic Judge, averaging fusion provides a reasonable
    approximation that:
    - Reduces uncertainty as more evidence is collected
    - Balances conflicting evidence proportionally
    - Preserves the b + d + u = 1 constraint

    Args:
        opinions: List of opinions to fuse

    Returns:
        Fused opinion representing combined evidence
    """
    if not opinions:
        return Opinion.vacuous()
    if len(opinions) == 1:
        return opinions[0]

    n = len(opinions)
    b = sum(o.belief for o in opinions) / n
    d = sum(o.disbelief for o in opinions) / n
    u = sum(o.uncertainty for o in opinions) / n
    a = sum(o.base_rate for o in opinions) / n

    # Renormalize to ensure b + d + u = 1 (handles floating point drift)
    total = b + d + u
    if total > 0:
        b, d, u = b / total, d / total, u / total
    else:
        # Degenerate case - return vacuous
        b, d, u = 0.0, 0.0, 1.0

    return Opinion(belief=b, disbelief=d, uncertainty=u, base_rate=a)


# ═══════════════════════════════════════════════════════════════════════════
# Agentic Judge Tools (MCP-style function definitions)
# ═══════════════════════════════════════════════════════════════════════════

AGENTIC_JUDGE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "verify_gpu_state",
            "description": "Check actual GPU health (VRAM, temp, utilization) to verify claims about GPU status in the debate.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_endpoint_health",
            "description": "Check if a specific vLLM endpoint is actually healthy/unhealthy by querying orchestrator status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "Endpoint name (e.g., 'reasoning', 'instruct', 'embedding')",
                    }
                },
                "required": ["endpoint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_precedent",
            "description": "Search KB heuristics for similar past incidents or remediation patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for KB heuristics",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_recommendation",
            "description": "Use RASE verification to validate that a recommendation meets quality gates (syntactic, semantic, empirical).",
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation": {
                        "type": "string",
                        "description": "The recommendation text to verify",
                    },
                    "objective": {
                        "type": "string",
                        "description": "RASE objective name (default: audit-recommendation-quality)",
                        "default": "audit-recommendation-quality",
                    },
                },
                "required": ["recommendation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metabase",
            "description": "Query Metabase to understand available dashboards, models, and questions for observability. Provides situational awareness about what monitoring artifacts exist and what could be created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["status", "dashboards", "models", "questions"],
                        "description": "Type of Metabase query: status (overview), dashboards (list), models (semantic layer), questions (saved queries)",
                    }
                },
                "required": ["query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metaflow",
            "description": "Query Metaflow operational data to understand pipeline execution history, success rates, and recent failures. Provides situational awareness about what flows are running, which have failed, and overall pipeline health.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["status", "types", "recent_runs", "failed", "stats"],
                        "description": "Type of Metaflow query: status (summary), types (flow types with counts), recent_runs (recent executions), failed (recent failures), stats (success rates and durations)",
                    },
                    "flow_type": {
                        "type": "string",
                        "description": "Optional: Filter by flow type (e.g., 'research', 'arxiv', 'cloudera_docs')",
                    },
                },
                "required": ["query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "Query Prometheus/OTel metrics to verify claims about system performance, resource usage, and operational health. Can execute PromQL queries or get metric summaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["health", "summary", "query"],
                        "description": "Type of metrics query: health (Prometheus availability), summary (current metrics overview), query (execute PromQL)",
                    },
                    "promql": {
                        "type": "string",
                        "description": "PromQL query string (required when query_type='query'). Example: 'gaius_gaius_inference_requests_total'",
                    },
                },
                "required": ["query_type"],
            },
        },
    },
]


@dataclass
class ToolResult:
    """Result from an Agentic Judge tool invocation."""

    tool_name: str
    arguments: dict[str, Any]
    output: str
    opinion: Opinion
    success: bool
    error: str | None = None

    def to_message(self) -> str:
        """Format as a tool result message for the LLM."""
        if not self.success:
            return f"Tool {self.tool_name} failed: {self.error}"
        return f"Tool {self.tool_name} result:\n{self.output}"


class AgenticJudgeToolHandler:
    """Handles tool calls from the Agentic Judge phase.

    The handler provides access to:
    - GPU health via Orchestrator gRPC
    - Endpoint status via Orchestrator gRPC
    - KB search for precedent heuristics
    - RASE verification for recommendation quality

    Each tool returns both a text result (for LLM context) and a Subjective
    Logic Opinion for uncertainty quantification and fusion.
    """

    def __init__(self, pool: "asyncpg.Pool | None" = None) -> None:
        """Initialize the tool handler.

        Args:
            pool: Database pool for KB operations (optional)
        """
        self._pool = pool

    async def handle_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Dispatch a tool call and return result with opinion.

        Args:
            name: Tool name (verify_gpu_state, verify_endpoint_health, etc.)
            arguments: Tool arguments from LLM

        Returns:
            ToolResult with output text and Subjective Logic opinion
        """
        try:
            if name == "verify_gpu_state":
                return await self._verify_gpu_state()
            elif name == "verify_endpoint_health":
                endpoint = arguments.get("endpoint", "")
                return await self._verify_endpoint_health(endpoint)
            elif name == "search_precedent":
                query = arguments.get("query", "")
                return await self._search_precedent(query)
            elif name == "verify_recommendation":
                recommendation = arguments.get("recommendation", "")
                objective = arguments.get("objective", "audit-recommendation-quality")
                return await self._verify_recommendation(recommendation, objective)
            elif name == "query_metabase":
                query_type = arguments.get("query_type", "status")
                return await self._query_metabase(query_type)
            elif name == "query_metaflow":
                query_type = arguments.get("query_type", "status")
                flow_type = arguments.get("flow_type", "")
                return await self._query_metaflow(query_type, flow_type)
            elif name == "query_metrics":
                query_type = arguments.get("query_type", "health")
                promql = arguments.get("promql", "")
                return await self._query_metrics(query_type, promql)
            else:
                return ToolResult(
                    tool_name=name,
                    arguments=arguments,
                    output="",
                    opinion=Opinion.vacuous(),
                    success=False,
                    error=f"Unknown tool: {name}",
                )
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return ToolResult(
                tool_name=name,
                arguments=arguments,
                output="",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )

    async def _verify_gpu_state(self) -> ToolResult:
        """Verify GPU health claims against actual state.

        Returns:
            ToolResult with GPU health summary and opinion
        """
        from gaius.mcp.operations import mcp_call

        result = await mcp_call("gpu_health")

        if "error" in result:
            return ToolResult(
                tool_name="verify_gpu_state",
                arguments={},
                output=f"GPU health check failed: {result['error']}",
                opinion=Opinion.vacuous(),
                success=False,
                error=result["error"],
            )

        # Extract GPU status from result
        gpus = result.get("gpus", result.get("data", {}).get("gpus", []))
        if not gpus:
            return ToolResult(
                tool_name="verify_gpu_state",
                arguments={},
                output="No GPU data available",
                opinion=Opinion.vacuous(),
                success=True,
            )

        # Build summary
        lines = ["GPU Health Status:"]
        healthy_count = 0
        total_count = len(gpus)

        for gpu in gpus:
            idx = gpu.get("index", gpu.get("id", "?"))
            name = gpu.get("name", "Unknown")
            util = gpu.get("utilization_gpu", gpu.get("utilization", 0))
            mem_used = gpu.get("memory_used_mib", gpu.get("memory_used", 0))
            mem_total = gpu.get("memory_total_mib", gpu.get("memory_total", 1))
            temp = gpu.get("temperature_gpu", gpu.get("temperature", 0))

            mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
            status = "healthy" if util < 95 and mem_pct < 95 and temp < 85 else "degraded"
            if status == "healthy":
                healthy_count += 1

            lines.append(
                f"  GPU {idx} ({name}): {status} "
                f"[util={util}%, mem={mem_pct:.0f}%, temp={temp}C]"
            )

        output = "\n".join(lines)

        # Generate opinion based on health ratio
        health_ratio = healthy_count / total_count if total_count > 0 else 0.5
        if health_ratio >= 0.9:
            opinion = Opinion.from_tool_result(verified=True, confidence=0.9)
        elif health_ratio >= 0.5:
            opinion = Opinion(belief=health_ratio * 0.8, disbelief=0.1, uncertainty=0.9 - health_ratio * 0.8)
        else:
            opinion = Opinion.from_tool_result(verified=False, confidence=0.8)

        return ToolResult(
            tool_name="verify_gpu_state",
            arguments={},
            output=output,
            opinion=opinion,
            success=True,
        )

    async def _verify_endpoint_health(self, endpoint: str) -> ToolResult:
        """Verify endpoint health claims against actual state.

        Args:
            endpoint: Endpoint name to check

        Returns:
            ToolResult with endpoint status and opinion
        """
        from gaius.mcp.operations import mcp_call

        if not endpoint:
            return ToolResult(
                tool_name="verify_endpoint_health",
                arguments={"endpoint": endpoint},
                output="No endpoint specified",
                opinion=Opinion.vacuous(),
                success=False,
                error="endpoint parameter required",
            )

        result = await mcp_call("orchestrator_status")

        if "error" in result:
            return ToolResult(
                tool_name="verify_endpoint_health",
                arguments={"endpoint": endpoint},
                output=f"Orchestrator status check failed: {result['error']}",
                opinion=Opinion.vacuous(),
                success=False,
                error=result["error"],
            )

        # Find the specific endpoint
        endpoints = result.get("endpoints", result.get("data", {}).get("endpoints", []))
        target = None
        for ep in endpoints:
            if ep.get("name", "").lower() == endpoint.lower():
                target = ep
                break

        if not target:
            return ToolResult(
                tool_name="verify_endpoint_health",
                arguments={"endpoint": endpoint},
                output=f"Endpoint '{endpoint}' not found in orchestrator status",
                opinion=Opinion.vacuous(),
                success=True,
            )

        # Extract status
        status = target.get("status", "unknown")
        healthy = target.get("healthy", status.lower() in ("healthy", "running"))
        port = target.get("port", "?")
        pid = target.get("pid", "?")

        output = (
            f"Endpoint '{endpoint}' status:\n"
            f"  Status: {status}\n"
            f"  Healthy: {healthy}\n"
            f"  Port: {port}\n"
            f"  PID: {pid}"
        )

        # Generate opinion based on health
        if healthy:
            opinion = Opinion.from_tool_result(verified=True, confidence=0.9)
        elif status.lower() in ("starting", "pending"):
            opinion = Opinion(belief=0.3, disbelief=0.2, uncertainty=0.5)
        else:
            opinion = Opinion.from_tool_result(verified=False, confidence=0.85)

        return ToolResult(
            tool_name="verify_endpoint_health",
            arguments={"endpoint": endpoint},
            output=output,
            opinion=opinion,
            success=True,
        )

    async def _search_precedent(self, query: str) -> ToolResult:
        """Search KB for similar past incidents or heuristics.

        Args:
            query: Search query

        Returns:
            ToolResult with matching heuristics and opinion
        """
        if not query:
            return ToolResult(
                tool_name="search_precedent",
                arguments={"query": query},
                output="No query specified",
                opinion=Opinion.vacuous(),
                success=False,
                error="query parameter required",
            )

        from gaius.storage.kb_ops import search_kb

        results = await search_kb(query, max_results=5)

        if not results:
            return ToolResult(
                tool_name="search_precedent",
                arguments={"query": query},
                output=f"No KB entries found matching '{query}'",
                opinion=Opinion(belief=0.1, disbelief=0.1, uncertainty=0.8),
                success=True,
            )

        # Format results
        lines = [f"KB search results for '{query}':"]
        for r in results:
            path = r.path if hasattr(r, "path") else str(r)
            snippet = r.snippet[:100] if hasattr(r, "snippet") and r.snippet else ""
            lines.append(f"  - {path}")
            if snippet:
                lines.append(f"    {snippet}...")

        output = "\n".join(lines)

        # More results = higher confidence that precedent exists
        confidence = min(0.9, 0.5 + len(results) * 0.1)
        opinion = Opinion(belief=confidence, disbelief=0.0, uncertainty=1.0 - confidence)

        return ToolResult(
            tool_name="search_precedent",
            arguments={"query": query},
            output=output,
            opinion=opinion,
            success=True,
        )

    async def _verify_recommendation(
        self,
        recommendation: str,
        objective: str = "audit-recommendation-quality",
    ) -> ToolResult:
        """Verify recommendation via RASE verification case.

        Args:
            recommendation: The recommendation text to verify
            objective: RASE objective name

        Returns:
            ToolResult with RASE verdict and opinion
        """
        if not recommendation:
            return ToolResult(
                tool_name="verify_recommendation",
                arguments={"recommendation": recommendation, "objective": objective},
                output="No recommendation specified",
                opinion=Opinion.vacuous(),
                success=False,
                error="recommendation parameter required",
            )

        try:
            # Import RASE components
            from gaius.rase.domains.kb.verification import KBVerificationCase
            from gaius.rase.domains.kb.state import KBState
            from gaius.rase.domains.kb.objective import load_objective

            # Load objective from KB
            objective_path = f"current/objectives/{objective}.md"
            obj = load_objective(objective_path)

            # Build verification case
            case = KBVerificationCase(objective=obj)

            # Create state from recommendation text
            state = KBState.from_text(recommendation)

            # Evaluate
            result = case.evaluate(state)

            # Format output
            verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
            accuracy = result.accuracy if hasattr(result, "accuracy") else 0.0

            gate_results = []
            if hasattr(result, "constraint_results"):
                for name, r in result.constraint_results.items():
                    satisfied = r.satisfied if hasattr(r, "satisfied") else "?"
                    gate_results.append(f"  - {name}: {'PASS' if satisfied else 'FAIL'}")

            output = (
                f"RASE Verification Result:\n"
                f"  Verdict: {verdict}\n"
                f"  Accuracy: {accuracy:.2f}\n"
                f"Gate Results:\n" + "\n".join(gate_results) if gate_results else ""
            )

            # Generate opinion from RASE result
            opinion = Opinion.from_rase_verdict(verdict, accuracy)

            return ToolResult(
                tool_name="verify_recommendation",
                arguments={"recommendation": recommendation, "objective": objective},
                output=output,
                opinion=opinion,
                success=True,
            )

        except FileNotFoundError:
            # Objective not found - return vacuous opinion
            return ToolResult(
                tool_name="verify_recommendation",
                arguments={"recommendation": recommendation, "objective": objective},
                output=f"RASE objective '{objective}' not found in KB. Skipping verification.",
                opinion=Opinion.vacuous(),
                success=True,
            )
        except ImportError as e:
            # RASE not available
            return ToolResult(
                tool_name="verify_recommendation",
                arguments={"recommendation": recommendation, "objective": objective},
                output=f"RASE verification not available: {e}",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"RASE verification failed: {e}")
            return ToolResult(
                tool_name="verify_recommendation",
                arguments={"recommendation": recommendation, "objective": objective},
                output=f"RASE verification error: {e}",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )

    async def _query_metabase(self, query_type: str) -> ToolResult:
        """Query Metabase for situational awareness.

        Provides read-only access to Metabase dashboards, models, and questions
        to understand what monitoring artifacts exist and what could be created.

        Args:
            query_type: Type of query (status, dashboards, models, questions)

        Returns:
            ToolResult with Metabase data and opinion
        """
        from gaius.engine.services.metabase_sync import get_metabase_client

        client = get_metabase_client()

        if not client.is_configured:
            return ToolResult(
                tool_name="query_metabase",
                arguments={"query_type": query_type},
                output="Metabase not configured. Set METABASE_URL, METABASE_API_KEY, METABASE_DATABASE_ID.",
                opinion=Opinion.vacuous(),
                success=False,
                error="Metabase not configured",
            )

        try:
            connected = await client.test_connection()
            if not connected:
                return ToolResult(
                    tool_name="query_metabase",
                    arguments={"query_type": query_type},
                    output="Failed to connect to Metabase",
                    opinion=Opinion.vacuous(),
                    success=False,
                    error="Connection failed",
                )

            if query_type == "status":
                status = await client.get_status()
                summary = (
                    f"Metabase Status:\n"
                    f"  Connected: {status.get('connected', False)}\n"
                    f"  URL: {status.get('url', 'unknown')}\n"
                    f"  Dashboards: {status.get('dashboards', 0)}\n"
                    f"  Models: {status.get('models', 0)}\n"
                    f"  Questions: {status.get('questions', 0)}\n"
                    f"  Collections: {status.get('collections', 0)}"
                )

            elif query_type == "dashboards":
                dashboards = await client.list_dashboards()
                if dashboards:
                    names = [d.get("name", "?") for d in dashboards[:10]]
                    summary = f"Found {len(dashboards)} dashboards: {', '.join(names)}"
                    if len(dashboards) > 10:
                        summary += f" (and {len(dashboards) - 10} more)"
                else:
                    summary = "No dashboards found in Metabase"

            elif query_type == "models":
                models = await client.list_cards(filter_type="model")
                if models:
                    names = [m.get("name", "?") for m in models[:10]]
                    summary = f"Found {len(models)} models: {', '.join(names)}"
                    if len(models) > 10:
                        summary += f" (and {len(models) - 10} more)"
                else:
                    summary = "No models (semantic layer) found in Metabase"

            elif query_type == "questions":
                questions = await client.list_cards(filter_type="question")
                if questions:
                    names = [q.get("name", "?") for q in questions[:10]]
                    summary = f"Found {len(questions)} saved questions: {', '.join(names)}"
                    if len(questions) > 10:
                        summary += f" (and {len(questions) - 10} more)"
                else:
                    summary = "No saved questions found in Metabase"

            else:
                return ToolResult(
                    tool_name="query_metabase",
                    arguments={"query_type": query_type},
                    output=f"Unknown query_type: {query_type}. Use: status, dashboards, models, questions",
                    opinion=Opinion.vacuous(),
                    success=False,
                    error=f"Unknown query_type: {query_type}",
                )

            # Metabase queries provide context, not verification
            # Return a neutral opinion (high uncertainty)
            opinion = Opinion(belief=0.5, disbelief=0.0, uncertainty=0.5)

            return ToolResult(
                tool_name="query_metabase",
                arguments={"query_type": query_type},
                output=summary,
                opinion=opinion,
                success=True,
            )

        except Exception as e:
            logger.error(f"Metabase query failed: {e}")
            return ToolResult(
                tool_name="query_metabase",
                arguments={"query_type": query_type},
                output=f"Metabase query error: {e}",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )

    async def _query_metaflow(self, query_type: str, flow_type: str = "") -> ToolResult:
        """Query Metaflow for operational insights.

        Provides read-only access to Metaflow run history, success rates,
        and failure information for situational awareness.

        Args:
            query_type: Type of query (status, types, recent_runs, failed, stats)
            flow_type: Optional flow type filter

        Returns:
            ToolResult with Metaflow data and opinion
        """
        from gaius.engine.services.metaflow_query import get_metaflow_client

        client = get_metaflow_client()

        try:
            if query_type == "status":
                status = await client.get_status_summary()
                stats_24h = status.get("stats_24h", {})
                running = status.get("currently_running", [])
                failures = status.get("recent_failures", [])

                summary = (
                    f"Metaflow Operational Status (last 24h):\n"
                    f"  Total Runs: {stats_24h.get('total_runs', 0)}\n"
                    f"  Completed: {stats_24h.get('completed', 0)}\n"
                    f"  Failed: {stats_24h.get('failed', 0)}\n"
                    f"  Running: {stats_24h.get('running', 0)}\n"
                    f"  Success Rate: {stats_24h.get('success_rate_pct', 0):.1f}%\n"
                    f"  Currently Running: {len(running)}\n"
                    f"  Recent Failures (1h): {len(failures)}"
                )

                # Success rate affects opinion
                success_rate = stats_24h.get("success_rate_pct", 50) / 100
                if success_rate >= 0.9:
                    opinion = Opinion(belief=0.8, disbelief=0.0, uncertainty=0.2)
                elif success_rate >= 0.7:
                    opinion = Opinion(belief=0.5, disbelief=0.2, uncertainty=0.3)
                else:
                    opinion = Opinion(belief=0.2, disbelief=0.5, uncertainty=0.3)

            elif query_type == "types":
                flow_types = await client.list_flow_types()
                if flow_types:
                    lines = ["Available Flow Types:"]
                    for ft in flow_types[:10]:
                        lines.append(
                            f"  - {ft.get('flow_type', '?')}: "
                            f"{ft.get('total_runs', 0)} runs, "
                            f"{ft.get('completed', 0)} completed, "
                            f"{ft.get('failed', 0)} failed"
                        )
                    if len(flow_types) > 10:
                        lines.append(f"  ... and {len(flow_types) - 10} more")
                    summary = "\n".join(lines)
                else:
                    summary = "No flow types found in Metaflow history"

                opinion = Opinion(belief=0.5, disbelief=0.0, uncertainty=0.5)

            elif query_type == "recent_runs":
                runs = await client.list_recent_runs(
                    flow_type=flow_type if flow_type else None,
                    limit=10,
                )
                if runs:
                    lines = [f"Recent Runs{' (' + flow_type + ')' if flow_type else ''}:"]
                    for r in runs:
                        lines.append(
                            f"  - {r.get('run_id', '?')[:8]}: "
                            f"{r.get('flow_type', '?')} "
                            f"[{r.get('status', '?')}] "
                            f"duration={r.get('duration_ms', 0)}ms"
                        )
                    summary = "\n".join(lines)
                else:
                    summary = f"No recent runs found{' for ' + flow_type if flow_type else ''}"

                opinion = Opinion(belief=0.5, disbelief=0.0, uncertainty=0.5)

            elif query_type == "failed":
                runs = await client.list_recent_runs(status="failed", limit=10)
                if runs:
                    lines = ["Recent Failed Runs:"]
                    for r in runs:
                        lines.append(
                            f"  - {r.get('run_id', '?')[:8]}: "
                            f"{r.get('flow_type', '?')} "
                            f"at {r.get('completed_at', '?')}"
                        )
                    summary = "\n".join(lines)
                    # Failures indicate potential issues
                    opinion = Opinion(belief=0.2, disbelief=0.5, uncertainty=0.3)
                else:
                    summary = "No recent failed runs found"
                    opinion = Opinion(belief=0.8, disbelief=0.0, uncertainty=0.2)

            elif query_type == "stats":
                stats = await client.get_flow_stats(
                    flow_type=flow_type if flow_type else None,
                    hours=24,
                )
                summary = (
                    f"Flow Statistics (last 24h){' for ' + flow_type if flow_type else ''}:\n"
                    f"  Total Runs: {stats.get('total_runs', 0)}\n"
                    f"  Completed: {stats.get('completed', 0)}\n"
                    f"  Failed: {stats.get('failed', 0)}\n"
                    f"  Running: {stats.get('running', 0)}\n"
                    f"  Success Rate: {stats.get('success_rate_pct', 0):.1f}%\n"
                    f"  Avg Duration: {stats.get('avg_duration_ms', 0)}ms\n"
                    f"  Total Inputs: {stats.get('total_inputs', 0)}\n"
                    f"  Total Outputs: {stats.get('total_outputs', 0)}"
                )

                success_rate = stats.get("success_rate_pct", 50) / 100
                opinion = Opinion(
                    belief=success_rate * 0.8,
                    disbelief=(1 - success_rate) * 0.5,
                    uncertainty=1.0 - success_rate * 0.8 - (1 - success_rate) * 0.5,
                )

            else:
                return ToolResult(
                    tool_name="query_metaflow",
                    arguments={"query_type": query_type, "flow_type": flow_type},
                    output=f"Unknown query_type: {query_type}. Use: status, types, recent_runs, failed, stats",
                    opinion=Opinion.vacuous(),
                    success=False,
                    error=f"Unknown query_type: {query_type}",
                )

            return ToolResult(
                tool_name="query_metaflow",
                arguments={"query_type": query_type, "flow_type": flow_type},
                output=summary,
                opinion=opinion,
                success=True,
            )

        except Exception as e:
            logger.error(f"Metaflow query failed: {e}")
            return ToolResult(
                tool_name="query_metaflow",
                arguments={"query_type": query_type, "flow_type": flow_type},
                output=f"Metaflow query error: {e}",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )

    async def _query_metrics(self, query_type: str, promql: str = "") -> ToolResult:
        """Query Prometheus/OTel metrics for verification.

        Provides access to system metrics for verifying claims about
        performance, resource usage, and operational health.

        Args:
            query_type: Type of query (health, summary, query)
            promql: PromQL query string (required when query_type='query')

        Returns:
            ToolResult with metrics data and opinion
        """
        from gaius.observability.sources.prometheus import get_prometheus_source

        source = get_prometheus_source()

        try:
            if query_type == "health":
                health = await source.health_check()
                if health.get("healthy", False):
                    summary = (
                        f"Prometheus Health:\n"
                        f"  Status: Healthy\n"
                        f"  URL: {source.base_url}\n"
                        f"  Version: {health.get('version', 'unknown')}"
                    )
                    opinion = Opinion(belief=0.9, disbelief=0.0, uncertainty=0.1)
                else:
                    summary = (
                        f"Prometheus Health:\n"
                        f"  Status: Unhealthy\n"
                        f"  URL: {source.base_url}\n"
                        f"  Error: {health.get('error', 'Unknown error')}"
                    )
                    opinion = Opinion(belief=0.0, disbelief=0.8, uncertainty=0.2)

            elif query_type == "summary":
                # Query a few key metrics for summary
                metrics = []

                # Try to get inference request count
                try:
                    result = await source.query_instant("gaius_gaius_inference_requests_total")
                    if result.get("data", {}).get("result"):
                        for r in result["data"]["result"][:3]:
                            metric = r.get("metric", {})
                            value = r.get("value", [0, "0"])[1]
                            metrics.append(f"  - inference_requests ({metric.get('agent', 'total')}): {value}")
                except Exception:
                    pass

                # Try to get KB entries
                try:
                    result = await source.query_instant("gaius_gaius_kb_entries")
                    if result.get("data", {}).get("result"):
                        value = result["data"]["result"][0].get("value", [0, "0"])[1]
                        metrics.append(f"  - kb_entries: {value}")
                except Exception:
                    pass

                # Try to get health check count
                try:
                    result = await source.query_instant("gaius_gaius_health_checks_total")
                    if result.get("data", {}).get("result"):
                        value = result["data"]["result"][0].get("value", [0, "0"])[1]
                        metrics.append(f"  - health_checks: {value}")
                except Exception:
                    pass

                if metrics:
                    summary = "OTel Metrics Summary:\n" + "\n".join(metrics)
                    opinion = Opinion(belief=0.6, disbelief=0.0, uncertainty=0.4)
                else:
                    summary = "OTel Metrics Summary:\n  No Gaius metrics found in Prometheus"
                    opinion = Opinion(belief=0.3, disbelief=0.2, uncertainty=0.5)

            elif query_type == "query":
                if not promql:
                    return ToolResult(
                        tool_name="query_metrics",
                        arguments={"query_type": query_type, "promql": promql},
                        output="PromQL query required when query_type='query'",
                        opinion=Opinion.vacuous(),
                        success=False,
                        error="promql parameter required",
                    )

                result = await source.query_instant(promql)

                if result.get("status") == "success":
                    data = result.get("data", {})
                    results = data.get("result", [])

                    if results:
                        lines = [f"PromQL: {promql}"]
                        for r in results[:10]:
                            metric = r.get("metric", {})
                            value = r.get("value", [0, "0"])[1]
                            labels = ", ".join(f"{k}={v}" for k, v in list(metric.items())[:3])
                            lines.append(f"  {{{labels}}}: {value}")
                        if len(results) > 10:
                            lines.append(f"  ... and {len(results) - 10} more")
                        summary = "\n".join(lines)
                        opinion = Opinion(belief=0.7, disbelief=0.0, uncertainty=0.3)
                    else:
                        summary = f"PromQL: {promql}\n  No results returned"
                        opinion = Opinion(belief=0.3, disbelief=0.2, uncertainty=0.5)
                else:
                    error_msg = result.get("error", "Unknown error")
                    return ToolResult(
                        tool_name="query_metrics",
                        arguments={"query_type": query_type, "promql": promql},
                        output=f"PromQL query failed: {error_msg}",
                        opinion=Opinion.vacuous(),
                        success=False,
                        error=error_msg,
                    )

            else:
                return ToolResult(
                    tool_name="query_metrics",
                    arguments={"query_type": query_type, "promql": promql},
                    output=f"Unknown query_type: {query_type}. Use: health, summary, query",
                    opinion=Opinion.vacuous(),
                    success=False,
                    error=f"Unknown query_type: {query_type}",
                )

            return ToolResult(
                tool_name="query_metrics",
                arguments={"query_type": query_type, "promql": promql},
                output=summary,
                opinion=opinion,
                success=True,
            )

        except Exception as e:
            logger.error(f"Metrics query failed: {e}")
            return ToolResult(
                tool_name="query_metrics",
                arguments={"query_type": query_type, "promql": promql},
                output=f"Metrics query error: {e}",
                opinion=Opinion.vacuous(),
                success=False,
                error=str(e),
            )


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

AGENTIC_JUDGE_PROMPT = """You are the final arbiter synthesizing the debate between analyst and skeptic.

You have access to tools that let you verify claims before making your final verdict:
- verify_gpu_state: Check actual GPU health to verify claims about GPU status
- verify_endpoint_health: Check if a specific endpoint is actually healthy/unhealthy
- search_precedent: Search KB heuristics for similar past incidents
- verify_recommendation: Use RASE to validate recommendation quality
- query_metabase: Query Metabase for dashboards, models, and questions (observability artifacts)
- query_metaflow: Query Metaflow for pipeline run history, success rates, and failures
- query_metrics: Query Prometheus/OTel metrics to verify performance claims

**Your workflow:**
1. First, analyze the debate transcript to identify claims that need verification
2. Use tools to verify key claims (especially about system state or recommendations)
3. After gathering tool evidence, synthesize your final verdict

**When to use tools:**
- A finding claims GPU is overloaded → call verify_gpu_state
- A finding claims an endpoint is unhealthy → call verify_endpoint_health
- The debate mentions a similar past incident → call search_precedent
- A recommendation includes a command → call verify_recommendation
- A finding mentions observability gaps or dashboards → call query_metabase
- A finding mentions pipeline failures or slow flows → call query_metaflow
- A finding makes claims about system performance → call query_metrics

**Maximum tool calls:** 5 (be selective, verify the most impactful claims)

After verification, output your verdict in this format:

## Tool Verification Summary
[Summary of what tools verified and the evidence gathered]

## Final Verdict

### Confirmed Findings (High Confidence)
[Findings that survived critique AND tool verification]
- Finding: [title]
  - Original Confidence: X.X
  - Final Confidence: X.X
  - Tool Evidence: [what verification showed]
  - Reasoning: [why it survived critique]

### Qualified Findings (Medium Confidence)
[Findings with valid concerns that warrant caution]
- Finding: [title]
  - Original Confidence: X.X
  - Final Confidence: X.X
  - Caveats: [what the skeptic raised or tools showed]

### Dismissed Findings
[Findings that skeptic or tools successfully challenged]
- Finding: [title]
  - Reason for Dismissal: [what critique or tool evidence was fatal]

### Prioritized Recommendations
1. [Most actionable + highest impact] - Commands: [...] - RASE Verified: [yes/no/skipped]
2. [Second priority] - Commands: [...] - RASE Verified: [yes/no/skipped]

### Overall Assessment
[Summary paragraph of system health and key actions needed]

### Epistemic State
[Your overall confidence after tool verification, expressed as:
 Belief: X.X (evidence supports verdict)
 Disbelief: X.X (evidence contradicts)
 Uncertainty: X.X (insufficient evidence)]
"""

# Maximum tool calls allowed in agentic judge phase
MAX_AGENTIC_JUDGE_TOOL_CALLS = 5


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
            max_tokens=EXTERNAL_MAX_TOKENS,
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
            max_tokens=EXTERNAL_MAX_TOKENS,
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
            max_tokens=EXTERNAL_MAX_TOKENS,
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
        """Phase 5: Agentic Judge synthesis with MCP tool access and RASE verification.

        This phase transforms from a single LLM call into an agentic loop where
        the Judge can verify claims via tools before rendering a final verdict.

        The agentic loop:
        1. Initial synthesis request (with tools available)
        2. If LLM requests tool calls, execute them and accumulate opinions
        3. Continue loop until LLM produces final verdict (no tool calls)
        4. Fuse all opinions and include in final result

        Args:
            findings: Initial analysis from Phase 2
            critique: Skeptic critique from Phase 3
            actionability: Actionability assessment from Phase 4

        Returns:
            Complete DebateResult with parsed findings, recommendations, and fused opinion
        """
        combined_input = f"""## Initial Findings (Phase 2)
{findings or 'No initial findings generated.'}

## Skeptic Critique (Phase 3)
{critique or 'Skeptic phase skipped or failed.'}

## Actionability Assessment (Phase 4)
{actionability or 'Actionability phase skipped or failed.'}
"""
        router = self._get_router()
        tool_handler = AgenticJudgeToolHandler(pool=self._pool)

        # Build conversation for agentic loop
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENTIC_JUDGE_PROMPT},
            {"role": "user", "content": combined_input},
        ]

        # Track tool opinions for fusion
        collected_opinions: list[Opinion] = []
        tool_results_log: list[str] = []
        tool_call_count = 0

        # Agentic loop - continue until LLM gives final verdict (no tool calls)
        while tool_call_count < MAX_AGENTIC_JUDGE_TOOL_CALLS:
            response = await router.complete(
                messages=messages,
                provider="xai",  # Always XAI for judge (Quality-First)
                max_tokens=EXTERNAL_MAX_TOKENS,
                temperature=0.4,
                tools=AGENTIC_JUDGE_TOOLS,
                source_context=self._get_source_context(
                    agent_alias="metaagent_agentic_judge",
                    task_type="judge_synthesis",
                ),
            )

            if response.error:
                logger.error(
                    f"Agentic Judge synthesis failed: {response.error}\n"
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
                    error=f"Agentic Judge synthesis failed: {response.error}",
                )

            self._track_exchange(response)

            # Check if LLM requested tool calls (ExternalResponse.tool_calls is Optional[list[ToolCall]])
            tool_calls = response.tool_calls

            if not tool_calls:
                # No tool calls - LLM has produced final verdict
                logger.info(
                    f"Agentic Judge completed with {tool_call_count} tool calls"
                )
                break

            # Process tool calls (ToolCall dataclass has id, name, arguments attributes)
            for tool_call in tool_calls:
                tool_call_count += 1
                if tool_call_count > MAX_AGENTIC_JUDGE_TOOL_CALLS:
                    logger.warning(
                        f"Agentic Judge exceeded max tool calls ({MAX_AGENTIC_JUDGE_TOOL_CALLS})"
                    )
                    break

                # Extract tool call info from ToolCall dataclass
                tool_name = tool_call.name
                tool_args_str = tool_call.arguments
                tool_call_id = tool_call.id or f"call_{tool_call_count}"

                try:
                    tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Agentic Judge tool call: {tool_name}({tool_args})")

                # Execute tool
                tool_result = await tool_handler.handle_tool_call(tool_name, tool_args)

                # Collect opinion for fusion
                collected_opinions.append(tool_result.opinion)
                tool_results_log.append(
                    f"[{tool_name}] {tool_result.output[:200]}..."
                    if len(tool_result.output) > 200
                    else f"[{tool_name}] {tool_result.output}"
                )

                # Add assistant's tool call to messages
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call],
                })

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result.to_message(),
                })

        # Fuse all collected opinions
        fused_opinion = cumulative_fusion(collected_opinions) if collected_opinions else None

        # Build final verdict content
        final_content = response.content or ""
        if tool_results_log:
            # Prepend tool verification log if tools were used
            tool_log = "\n\n## Tool Verification Log\n" + "\n".join(tool_results_log)
            final_content = tool_log + "\n\n" + final_content

        self._transcript.judge_synthesis = final_content

        # Parse judge output into structured result
        parsed_findings, parsed_recommendations = self._parse_judge_output(response.content or "")

        return DebateResult(
            findings=parsed_findings,
            recommendations=parsed_recommendations,
            transcript=self._transcript,
            verdict_summary=final_content,
            total_llm_calls=self._total_calls,
            total_tokens=self._total_tokens,
            fused_opinion=fused_opinion,
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
