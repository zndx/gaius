"""Orchestrator-coordinated .base file generation.

Uses NVIDIA ToolOrchestra pattern where a local Orchestrator-8B model
coordinates calls to specialist models:
- GLM-4.7 (Cerebras): Primary generator (open weights preference)
- Grok-4.1 fast (XAI): Diagnostic specialist for validation error analysis
- Fallback template: Last resort when LLM generation fails

The orchestrator decides which tool to call based on:
- Current state (attempts, errors, diagnosis)
- User preferences (open weights preferred)
- Multi-objective optimization (cost, accuracy, latency)

Engine-First Architecture:
All LLM calls route through the engine's gRPC API via SchedulerProxy,
which handles backend selection, budget tracking, and exchange capture.

References:
- https://huggingface.co/nvidia/Orchestrator-8B
- https://developer.nvidia.com/blog/train-small-orchestration-agents-to-solve-big-problems/
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from gaius.agents.tool_registry import ToolRegistry, create_prospects_registry
from gaius.engine.services.prospects_analysis import FilingAnalysis, PositionSynthesis
from gaius.kb.base_validator import validate_base, ValidationResult
from gaius.core.budgets import REASONING_MAX_TOKENS, LONG_FORM_MAX_TOKENS

logger = logging.getLogger(__name__)


# Global registry instance for prospects orchestration
_prospects_registry: ToolRegistry | None = None


def get_prospects_registry() -> ToolRegistry:
    """Get or create the prospects tool registry."""
    global _prospects_registry
    if _prospects_registry is None:
        _prospects_registry = create_prospects_registry()
    return _prospects_registry


# =============================================================================
# Tool Definitions (ToolOrchestra schema)
# =============================================================================

ORCHESTRATOR_TOOLS = [
    {
        "name": "generate_base",
        "description": "Generate Obsidian .base YAML file for prospect views using Cerebras GLM-4.7",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock symbol (e.g., MTN)"},
                "use_prior_diagnosis": {
                    "type": "boolean",
                    "description": "Whether to include Grok's diagnosis in the prompt",
                },
            },
            "required": ["symbol"],
        },
        "backend": "cerebras",
        "model": "zai-glm-4.7",
        "cost_per_call": 0.0001,
    },
    {
        "name": "diagnose_error",
        "description": "Analyze YAML validation errors using XAI Grok-4.1 fast to identify root cause and suggest fixes",
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_content": {"type": "string", "description": "The generated YAML that failed validation"},
                "validation_errors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of validation error messages",
                },
            },
            "required": ["yaml_content", "validation_errors"],
        },
        "backend": "xai",
        "model": "grok-4-1-fast",
        "cost_per_call": 0.001,
    },
    {
        "name": "use_fallback",
        "description": "Use minimal template when LLM generation fails repeatedly",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock symbol"},
            },
            "required": ["symbol"],
        },
        "backend": "local",
        "model": None,
        "cost_per_call": 0,
    },
]


# =============================================================================
# Orchestrator System Prompt
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the .base generation orchestrator for a financial KB system.

Your role is to coordinate tools to generate valid Obsidian .base YAML files.

## Available Tools

1. **generate_base** - Use Cerebras GLM-4.7 to generate YAML
   - Preferred because it uses open weights
   - Cost: ~$0.0001 per call
   - Use when: First attempt, or after receiving diagnosis

2. **diagnose_error** - Use XAI Grok-4.1 fast to analyze validation failures
   - Specialist at understanding YAML schema errors
   - Cost: ~$0.001 per call
   - Use when: GLM output fails validation

3. **use_fallback** - Use minimal template
   - No LLM call, always works
   - Cost: $0
   - Use when: 2+ failed attempts with diagnosis, or persistent structural issues

## User Preferences

- PREFER open weights models (GLM) over proprietary (Grok)
- ONLY escalate to Grok when GLM encounters validation errors
- Use fallback ONLY after 2+ failed generation attempts with diagnosis

## Decision Logic

1. Turn 0: Call generate_base (first attempt with GLM)
2. If validation fails: Call diagnose_error (get Grok's analysis)
3. Turn 2+: Call generate_base with diagnosis context
4. After 3+ failed attempts or persistent issues: Call use_fallback

## Response Format

Respond with a JSON object:
{
    "tool": "generate_base" | "diagnose_error" | "use_fallback",
    "reasoning": "Brief explanation of why this tool is selected",
    "use_prior_diagnosis": true | false  // Only for generate_base
}
"""


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class OrchestratorDecision:
    """Decision made by the orchestrator."""

    tool: Literal["generate_base", "diagnose_error", "use_fallback"]
    reasoning: str = ""
    use_prior_diagnosis: bool = False


@dataclass
class DiagnosisResult:
    """Result from Grok-4.1 fast error diagnosis."""

    root_cause: str
    fix_hints: list[str] = field(default_factory=list)
    confidence: float = 0.0
    cost_usd: float = 0.0


@dataclass
class ToolMetricsSummary:
    """Summary of tool usage metrics for a generation run."""

    generate_calls: int = 0
    generate_successes: int = 0
    diagnose_calls: int = 0
    diagnose_successes: int = 0
    fallback_used: bool = False
    total_latency_ms: int = 0


@dataclass
class OrchestrationState:
    """State tracked across orchestration turns."""

    symbol: str
    company_name: str
    filing_summaries: str
    synthesis_summary: str
    attempts: list[dict] = field(default_factory=list)
    current_yaml: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    diagnosis: DiagnosisResult | None = None
    total_cost_usd: float = 0.0
    # Metrics tracking
    metrics: ToolMetricsSummary = field(default_factory=ToolMetricsSummary)


@dataclass
class OrchestratedResult:
    """Final result from orchestrated .base generation."""

    success: bool
    content: str
    validation: ValidationResult
    attempts: int
    model_used: str = ""
    fallback_used: bool = False
    orchestrator_turns: int = 0
    total_cost_usd: float = 0.0
    diagnosis_used: bool = False
    metrics: ToolMetricsSummary | None = None


# =============================================================================
# Prompts
# =============================================================================

BASE_GENERATION_SYSTEM_PROMPT = """You are a YAML generator that produces Obsidian Bases .base files.

Obsidian Bases provide database-like views over markdown files. Output ONLY valid YAML.

.base file structure:
- name: Display name for the base
- description: Brief description
- sources: List of file/folder references
- filters: Property-based filters with operators
- formulas: Computed properties using expressions
- views: Named views with type, columns, sort

Valid operators: equals, not_equals, contains, starts_with, ends_with, before, after, greater_than, less_than, is_empty, is_not_empty
Valid view types: table, cards, gallery, list

Example:
```yaml
name: "Company Filings"
description: "SEC filing analysis views"

sources:
  - type: folder
    path: current/prospects/aapl/
    recursive: true

formulas:
  filing_age_days: 'dateDiff(now(), filing_date, "days")'
  is_recent: "filing_age_days < 90"

views:
  all_filings:
    type: table
    filter: "type == 'sec-filing'"
    columns:
      - property: "file.name"
      - property: "filing_type"
      - property: "filing_date"
    sort: [filing_date desc]

  financials:
    type: table
    filter: "filing_type contains '10-'"
    columns:
      - property: "file.name"
      - property: "revenue_yoy_change"
      - property: "gross_margin"
```

IMPORTANT: Output ONLY the YAML content. No markdown code fences, no explanations.
Respond in English."""


BASE_GENERATION_USER_TEMPLATE = """Generate an Obsidian .base file for {symbol} ({company_name}).

Symbol directory: current/prospects/{safe_symbol}/

Filing analyses available:
{filing_summaries}

Synthesis summary:
- Recommendation: {recommendation}
- Conviction: {conviction_score:.0%}
- Risk: {risk_level}

Generate a .base file with:
1. Sources pointing to the prospect directory
2. Views for: all_filings, recent (last 90 days), financials (10-K/10-Q), catalysts
3. Formulas for: filing_age_days, is_recent, has_financials
4. Use the filing properties from frontmatter: type, filing_type, filing_date, symbol

Output ONLY valid YAML, no code fences or explanations."""


BASE_GENERATION_WITH_DIAGNOSIS_TEMPLATE = """Generate an Obsidian .base file for {symbol} ({company_name}).

Symbol directory: current/prospects/{safe_symbol}/

Filing analyses available:
{filing_summaries}

Synthesis summary:
- Recommendation: {recommendation}
- Conviction: {conviction_score:.0%}
- Risk: {risk_level}

## IMPORTANT: Previous Attempt Failed

A diagnostic specialist analyzed the validation errors and identified:
- Root cause: {diagnosis_root_cause}
- Specific fixes needed:
{diagnosis_fix_hints}

Please apply these fixes when generating the YAML.

Generate a .base file with:
1. Sources pointing to the prospect directory
2. Views for: all_filings, recent (last 90 days), financials (10-K/10-Q), catalysts
3. Formulas for: filing_age_days, is_recent, has_financials
4. Use the filing properties from frontmatter: type, filing_type, filing_date, symbol

Output ONLY valid YAML, no code fences or explanations."""


DIAGNOSE_ERROR_PROMPT = """Analyze this Obsidian .base YAML validation failure.

## YAML Content (may be truncated)
```yaml
{yaml_content}
```

## Validation Errors
{validation_errors}

## Obsidian .base Schema Rules
- Valid view types: table, cards, gallery, list
- Valid operators: equals, not_equals, contains, starts_with, ends_with, before, after, greater_than, less_than, is_empty, is_not_empty
- Formula values must be quoted strings
- Sources must have type (file/folder) and path
- Columns must be a list of mappings with "property" key

## Your Task
1. Identify the root cause of each error
2. Provide specific, actionable fixes
3. Explain what the generator did wrong

Response format (JSON):
{{
    "root_cause": "Brief explanation of the main issue",
    "fix_hints": ["Specific fix 1", "Specific fix 2"],
    "confidence": 0.0-1.0
}}"""


# =============================================================================
# Helper Functions
# =============================================================================

def _format_filing_summaries(analyses: list[FilingAnalysis]) -> str:
    """Format filing analyses for the prompt."""
    summaries = []
    for a in analyses:
        highlights = a.key_highlights[:3] if a.key_highlights else []
        metrics_parts = []
        if a.revenue_yoy_change is not None:
            metrics_parts.append(f"revenue YoY: {a.revenue_yoy_change:.1%}")
        if a.gross_margin is not None:
            metrics_parts.append(f"margin: {a.gross_margin:.1%}")

        summary = f"- {a.filing_type} ({a.filing_date})"
        if metrics_parts:
            summary += f" | {', '.join(metrics_parts)}"
        if highlights:
            summary += f"\n  Highlights: {'; '.join(highlights[:2])}"
        summaries.append(summary)

    return "\n".join(summaries) if summaries else "No filing analyses available."


def _extract_yaml(response: str) -> str:
    """Extract YAML from LLM response, removing code fences if present."""
    content = response.strip()

    # Remove markdown code fences if present
    if content.startswith("```yaml"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def _get_fallback_template(symbol: str, safe_symbol: str) -> str:
    """Return a minimal valid .base template as fallback."""
    return f"""name: "{symbol} Prospects"
description: "Filing analysis for {symbol}"

sources:
  - type: folder
    path: current/prospects/{safe_symbol}/
    recursive: true

formulas:
  filing_age_days: 'dateDiff(now(), filing_date, "days")'
  is_recent: "filing_age_days < 90"

views:
  all_filings:
    type: table
    filter: "type == 'sec-filing'"
    columns:
      - property: "file.name"
      - property: "filing_type"
      - property: "filing_date"
    sort: [filing_date desc]

  overview:
    type: cards
    filter: "type == 'prospect-synthesis'"
    columns:
      - property: "file.name"
      - property: "conviction_score"
      - property: "recommendation"
"""


def _strip_thinking_tags(content: str) -> str:
    """Strip <think>...</think> tags from model output (Qwen3 thinking mode)."""
    import re
    # Remove thinking sections
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()


def _parse_orchestrator_decision(response: str) -> OrchestratorDecision:
    """Parse orchestrator response into a decision.

    Handles Qwen3 thinking mode output with <think> tags.
    """
    try:
        # Strip thinking tags if present (Qwen3 produces these)
        content = _strip_thinking_tags(response.strip())

        # Find JSON in response
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = content[start:end]
            data = json.loads(json_str)
            decision = OrchestratorDecision(
                tool=data.get("tool", "generate_base"),
                reasoning=data.get("reasoning", ""),
                use_prior_diagnosis=data.get("use_prior_diagnosis", False),
            )
            logger.info(f"Orchestrator decision: {decision.tool} - {decision.reasoning}")
            return decision
        else:
            logger.warning(f"No JSON found in orchestrator response: {content[:200]}...")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse orchestrator decision: {e}")
        logger.debug(f"Response was: {response[:500]}...")

    # Default to generate_base
    return OrchestratorDecision(
        tool="generate_base",
        reasoning="Failed to parse orchestrator response, defaulting to generation",
    )


# =============================================================================
# Tool Implementations
# =============================================================================

# Engine Federation Architecture:
# All LLM calls route through the engine's gRPC Scheduler service using agent
# aliases configured in config/agents.conf. This enables:
# - Capability-based routing (agent → model → backend)
# - Centralized budget tracking and metrics
# - Exchange capture for training data
# - Federation to remote nodes when needed
#
# Agent aliases used:
# - "thinking": Qwen3.8-27B for YAML generation, orchestration decisions,
#   and error diagnosis (external/dedicated models retired 2026-09-02 —
#   CLT/SAE capabilities are the only dedicated-model use cases)


async def _call_generate_base(
    state: OrchestrationState,
    use_prior_diagnosis: bool,
) -> tuple[str, ValidationResult, float]:
    """Call GLM-4.7 via engine gRPC to generate .base YAML.

    Uses the Engine Federation architecture with gRPC Scheduler routing.
    Agent alias "cerebras-glm" is configured in config/agents.conf.

    Returns:
        Tuple of (yaml_content, validation_result, cost_usd)
    """
    from gaius.client.engine_proxy import get_scheduler_proxy, use_engine_proxy

    safe_symbol = state.symbol.lower().replace(" ", "_")

    # Build user prompt
    if use_prior_diagnosis and state.diagnosis:
        user_prompt = BASE_GENERATION_WITH_DIAGNOSIS_TEMPLATE.format(
            symbol=state.symbol,
            company_name=state.company_name,
            safe_symbol=safe_symbol,
            filing_summaries=state.filing_summaries,
            recommendation=state.synthesis_summary.split("Recommendation: ")[1].split(",")[0] if "Recommendation:" in state.synthesis_summary else "hold",
            conviction_score=0.5,  # Will be formatted correctly
            risk_level="medium",
            diagnosis_root_cause=state.diagnosis.root_cause,
            diagnosis_fix_hints="\n".join(f"  - {hint}" for hint in state.diagnosis.fix_hints),
        )
    else:
        user_prompt = BASE_GENERATION_USER_TEMPLATE.format(
            symbol=state.symbol,
            company_name=state.company_name,
            safe_symbol=safe_symbol,
            filing_summaries=state.filing_summaries,
            recommendation="hold",
            conviction_score=0.5,
            risk_level="medium",
        )

    try:
        # Check if engine is available
        if not use_engine_proxy():
            raise RuntimeError(
                "Engine not available for .base generation (intended agent=thinking).\n"
                "  Try: just restart-clean"
            )

        # Get scheduler proxy for gRPC routing
        scheduler = await get_scheduler_proxy()

        # Qwen3.8-27B thinking is the go-to for workflow generation
        # (2026-09-02); cerebras-glm retired (zai-glm-4.7 archived
        # upstream) — dedicated models are reserved for CLT/SAE.
        response = await scheduler.complete(
            prompt=user_prompt,
            agent="thinking",
            system_prompt=BASE_GENERATION_SYSTEM_PROMPT,
            temperature=0.2,  # Low temperature for consistent YAML output
            max_tokens=LONG_FORM_MAX_TOKENS,
        )

        cost_usd = 0.0  # local thinking endpoint

        yaml_content = _extract_yaml(response.content)
        validation = validate_base(yaml_content)

        return yaml_content, validation, cost_usd

    except Exception as e:
        raise RuntimeError(
            f"Prospects .base Complete failed (intended agent=thinking).\n"
            f"  {e}"
        ) from e


async def _call_diagnose_error(
    yaml_content: str,
    validation_errors: list[str],
) -> DiagnosisResult:
    """Use Grok-4.1 fast via engine gRPC to diagnose validation errors.

    Uses the Engine Federation architecture with gRPC Scheduler routing.
    Agent alias "xai-grok-fast" is configured in config/agents.conf.
    """
    from gaius.client.engine_proxy import get_scheduler_proxy, use_engine_proxy

    prompt = DIAGNOSE_ERROR_PROMPT.format(
        yaml_content=yaml_content[:3000],  # Truncate for context window
        validation_errors="\n".join(f"- {e}" for e in validation_errors),
    )

    try:
        # Check if engine is available
        if not use_engine_proxy():
            logger.warning("Engine not available for error diagnosis")
            return DiagnosisResult(
                root_cause="Could not diagnose - Engine not available",
                fix_hints=[],
                confidence=0.0,
                cost_usd=0.0,
            )

        # Get scheduler proxy for gRPC routing
        scheduler = await get_scheduler_proxy()

        # Qwen3.8-27B thinking handles error diagnosis too (2026-09-02);
        # xai-grok-fast retired from this path — external models are not
        # part of workflow execution.
        response = await scheduler.complete(
            prompt=prompt,
            agent="thinking",
            temperature=0.1,
            max_tokens=REASONING_MAX_TOKENS,
        )

        cost_usd = 0.0  # local thinking endpoint

        # Parse JSON from response
        try:
            content = response.content
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                return DiagnosisResult(
                    root_cause=data.get("root_cause", "Unknown"),
                    fix_hints=data.get("fix_hints", []),
                    confidence=data.get("confidence", 0.5),
                    cost_usd=cost_usd,
                )
        except json.JSONDecodeError:
            pass

        return DiagnosisResult(
            root_cause="Could not parse diagnosis response",
            fix_hints=[],
            confidence=0.0,
            cost_usd=cost_usd,
        )

    except Exception as e:
        raise RuntimeError(f"Prospects diagnose Complete failed: {e}") from e


async def _consult_orchestrator(
    state: OrchestrationState,
    turn: int,
) -> OrchestratorDecision:
    """Ask Orchestrator-8B which tool to use next via engine scheduler.

    Uses the engine's gRPC scheduler service for dynamic scheduling
    rather than direct HTTP calls, ensuring proper resource management
    and consistency with the Engine Federation Architecture.

    Falls back to heuristic decision if engine unavailable.
    """
    # Build observation for orchestrator
    observation = f"""## Current State (Turn {turn + 1})

Symbol: {state.symbol}
Company: {state.company_name}

Attempts so far: {len(state.attempts)}

"""
    if state.attempts:
        observation += "### Attempt History\n"
        for attempt in state.attempts:
            observation += f"- Turn {attempt['turn'] + 1}: {attempt['tool']}"
            if "valid" in attempt:
                observation += f" -> {'Valid' if attempt['valid'] else 'INVALID'}"
                if attempt.get("errors"):
                    observation += f" ({len(attempt['errors'])} errors)"
            observation += "\n"

    if state.validation_errors:
        observation += f"\n### Current Validation Errors\n"
        for err in state.validation_errors[:5]:
            observation += f"- {err}\n"

    if state.diagnosis:
        observation += f"\n### Grok Diagnosis\n"
        observation += f"Root cause: {state.diagnosis.root_cause}\n"
        observation += f"Fix hints: {state.diagnosis.fix_hints}\n"
        observation += f"Confidence: {state.diagnosis.confidence:.0%}\n"

    observation += "\n### Decision Required\nWhich tool should we use next?"

    # Use engine scheduler proxy for dynamic scheduling
    try:
        from gaius.client.engine_proxy import get_scheduler_proxy, use_engine_proxy

        if not use_engine_proxy():
            raise RuntimeError(
                "Engine not available for orchestration Complete "
                "(intended agent=thinking). No heuristic fallback."
            )

        scheduler = await get_scheduler_proxy()

        # Build the full prompt with system context
        full_prompt = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{observation}"

        # Qwen3.8-27B thinking is the go-to for workflow orchestration
        # decisions (2026-09-02); Orchestrator-8B is retired from this
        # path — dedicated models are reserved for CLT/SAE capabilities.
        result = await scheduler.complete(
            prompt=full_prompt,
            agent="thinking",
            max_tokens=REASONING_MAX_TOKENS,
            temperature=0.2,
        )

        return _parse_orchestrator_decision(result.content)

    except Exception as e:
        raise RuntimeError(
            f"Orchestration Complete failed (intended agent=thinking): {e}"
        ) from e


def _heuristic_decision(state: OrchestrationState, turn: int) -> OrchestratorDecision:
    """Make a decision using simple heuristics when orchestrator unavailable."""

    # Count generation attempts
    gen_attempts = sum(1 for a in state.attempts if a["tool"] == "generate_base")

    # Turn 0: Always start with generation
    if turn == 0:
        return OrchestratorDecision(
            tool="generate_base",
            reasoning="First attempt - try GLM generation",
        )

    # If we have validation errors and no diagnosis, get one
    if state.validation_errors and not state.diagnosis:
        return OrchestratorDecision(
            tool="diagnose_error",
            reasoning="Validation failed, need Grok diagnosis",
        )

    # If we have diagnosis, try generation again
    if state.diagnosis and gen_attempts < 3:
        return OrchestratorDecision(
            tool="generate_base",
            reasoning="Have diagnosis, retry generation with hints",
            use_prior_diagnosis=True,
        )

    # Too many attempts, use fallback
    if gen_attempts >= 2:
        return OrchestratorDecision(
            tool="use_fallback",
            reasoning="Multiple attempts failed, using template",
        )

    # Default to generation
    return OrchestratorDecision(
        tool="generate_base",
        reasoning="Default to generation attempt",
    )


# =============================================================================
# Main Orchestration Loop
# =============================================================================

async def orchestrated_generate_base(
    symbol: str,
    company_name: str,
    analyses: list[FilingAnalysis],
    synthesis: PositionSynthesis | None = None,
) -> OrchestratedResult:
    """Generate .base file using orchestrator-coordinated tools.

    Uses the NVIDIA ToolOrchestra pattern:
    1. Orchestrator-8B (local) decides which tool to call
    2. GLM-4.7 (Cerebras) generates YAML via engine gRPC
    3. Grok-4.1 fast (XAI) diagnoses validation errors via engine gRPC
    4. Fallback template as last resort

    Engine-First Architecture:
    All LLM calls route through the engine's BackendRouter which handles:
    - Backend selection (Cerebras, XAI)
    - Budget tracking
    - Exchange capture for training data

    Args:
        symbol: Stock symbol (e.g., "MTN")
        company_name: Company name for context
        analyses: List of FilingAnalysis objects
        synthesis: Optional PositionSynthesis for context

    Returns:
        OrchestratedResult with content, validation info, and cost
    """
    from gaius.client.engine_proxy import use_engine_proxy

    safe_symbol = symbol.lower().replace(" ", "_")

    # Check if engine is available for LLM calls
    if not use_engine_proxy():
        logger.warning("Engine not available, using fallback template")
        fallback = _get_fallback_template(symbol, safe_symbol)
        validation = validate_base(fallback)
        return OrchestratedResult(
            success=validation.valid,
            content=fallback,
            validation=validation,
            attempts=0,
            fallback_used=True,
        )

    # Initialize state
    state = OrchestrationState(
        symbol=symbol,
        company_name=company_name or symbol,
        filing_summaries=_format_filing_summaries(analyses),
        synthesis_summary=f"Recommendation: {synthesis.recommendation if synthesis else 'hold'}, "
                         f"Conviction: {synthesis.conviction_score if synthesis else 0.5:.0%}, "
                         f"Risk: {synthesis.risk_level if synthesis else 'medium'}",
    )

    MAX_TURNS = 5  # Safety limit

    for turn in range(MAX_TURNS):
        # Orchestrator decides next action
        decision = await _consult_orchestrator(state, turn)

        logger.info(
            f"Turn {turn + 1}: orchestrator selects {decision.tool} - {decision.reasoning}"
        )

        if decision.tool == "generate_base":
            # Call GLM-4.7 to generate YAML via engine gRPC
            start_time = time.time()
            yaml_content, validation, cost = await _call_generate_base(
                state=state,
                use_prior_diagnosis=decision.use_prior_diagnosis,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            # Update metrics
            state.metrics.generate_calls += 1
            state.metrics.total_latency_ms += latency_ms
            if validation.valid:
                state.metrics.generate_successes += 1

            state.current_yaml = yaml_content
            state.total_cost_usd += cost
            state.attempts.append({
                "turn": turn,
                "tool": "generate_base",
                "valid": validation.valid,
                "errors": validation.errors,
                "cost_usd": cost,
                "latency_ms": latency_ms,
            })

            if validation.valid:
                logger.info(
                    f"Generated valid .base for {symbol} on turn {turn + 1} "
                    f"(${state.total_cost_usd:.6f})"
                )
                return OrchestratedResult(
                    success=True,
                    content=yaml_content,
                    validation=validation,
                    attempts=len(state.attempts),
                    model_used="zai-glm-4.7",
                    orchestrator_turns=turn + 1,
                    total_cost_usd=state.total_cost_usd,
                    diagnosis_used=state.diagnosis is not None,
                    metrics=state.metrics,
                )

            state.validation_errors = validation.errors

        elif decision.tool == "diagnose_error":
            # Call Grok-4.1 fast via engine gRPC to analyze errors
            if not state.current_yaml or not state.validation_errors:
                logger.warning("No YAML or errors to diagnose")
                continue

            start_time = time.time()
            diagnosis = await _call_diagnose_error(
                yaml_content=state.current_yaml,
                validation_errors=state.validation_errors,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            # Update metrics
            state.metrics.diagnose_calls += 1
            state.metrics.total_latency_ms += latency_ms
            if diagnosis.confidence > 0.5:
                state.metrics.diagnose_successes += 1

            state.diagnosis = diagnosis
            state.total_cost_usd += diagnosis.cost_usd
            state.attempts.append({
                "turn": turn,
                "tool": "diagnose_error",
                "diagnosis": {
                    "root_cause": diagnosis.root_cause,
                    "fix_hints": diagnosis.fix_hints,
                    "confidence": diagnosis.confidence,
                },
                "cost_usd": diagnosis.cost_usd,
                "latency_ms": latency_ms,
            })

            logger.info(
                f"Grok diagnosis: {diagnosis.root_cause} "
                f"(confidence: {diagnosis.confidence:.0%})"
            )

        elif decision.tool == "use_fallback":
            # Give up on LLM generation
            fallback_content = _get_fallback_template(symbol, safe_symbol)
            validation = validate_base(fallback_content)

            # Update metrics
            state.metrics.fallback_used = True

            logger.info(
                f"Using fallback template for {symbol} after {len(state.attempts)} attempts "
                f"(${state.total_cost_usd:.6f})"
            )

            return OrchestratedResult(
                success=validation.valid,
                content=fallback_content,
                validation=validation,
                attempts=len(state.attempts),
                fallback_used=True,
                orchestrator_turns=turn + 1,
                total_cost_usd=state.total_cost_usd,
                diagnosis_used=state.diagnosis is not None,
                metrics=state.metrics,
            )

    # Max turns reached - use fallback
    logger.warning(
        f"Max turns ({MAX_TURNS}) reached for {symbol}, using fallback"
    )
    fallback_content = _get_fallback_template(symbol, safe_symbol)
    validation = validate_base(fallback_content)
    state.metrics.fallback_used = True

    return OrchestratedResult(
        success=validation.valid,
        content=fallback_content,
        validation=validation,
        attempts=len(state.attempts),
        fallback_used=True,
        orchestrator_turns=MAX_TURNS,
        total_cost_usd=state.total_cost_usd,
        diagnosis_used=state.diagnosis is not None,
        metrics=state.metrics,
    )
