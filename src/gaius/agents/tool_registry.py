"""Tool registry for orchestrator-coordinated agents.

Provides a standardized way to define, register, and execute tools
following the NVIDIA ToolOrchestra pattern.

This registry enables:
- Tool schema definition (JSON Schema format)
- Tool implementation binding
- Execution metrics tracking
- Cost accounting per tool

Example usage:
    registry = ToolRegistry("prospects")

    @registry.tool(
        name="generate_base",
        description="Generate Obsidian .base YAML",
        backend="cerebras",
        model="zai-glm-4.7",
        cost_per_call=0.0001,
    )
    async def generate_base(state: OrchestrationState, args: dict) -> dict:
        ...

    # Execute a tool
    result = await registry.execute("generate_base", state, {"symbol": "MTN"})

References:
- https://huggingface.co/nvidia/Orchestrator-8B
- https://developer.nvidia.com/blog/train-small-orchestration-agents-to-solve-big-problems/
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, TypeVar

logger = logging.getLogger(__name__)


# Type for tool implementations
S = TypeVar("S")  # State type
ToolFn = Callable[[S, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ToolDefinition:
    """Definition of a tool available to the orchestrator."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    backend: str = "local"
    model: str | None = None
    cost_per_call: float = 0.0
    implementation: ToolFn | None = None


@dataclass
class ToolExecutionResult:
    """Result of executing a tool."""

    success: bool
    data: dict[str, Any]
    error: str | None = None
    latency_ms: int = 0
    cost_usd: float = 0.0


@dataclass
class ToolMetrics:
    """Metrics for tool usage."""

    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: int = 0
    total_cost_usd: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.calls if self.calls > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.calls if self.calls > 0 else 0.0


class ToolRegistry:
    """Registry for orchestrator tools.

    Manages tool definitions, implementations, and execution metrics.
    """

    def __init__(self, namespace: str):
        """Initialize a tool registry.

        Args:
            namespace: Namespace for this registry (e.g., "prospects", "modeladd")
        """
        self.namespace = namespace
        self._tools: dict[str, ToolDefinition] = {}
        self._metrics: dict[str, ToolMetrics] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        backend: str = "local",
        model: str | None = None,
        cost_per_call: float = 0.0,
        implementation: ToolFn | None = None,
    ) -> None:
        """Register a tool definition.

        Args:
            name: Tool name (must be unique within registry)
            description: Tool description for the orchestrator
            parameters: JSON Schema for parameters
            backend: Backend to use (cerebras, xai, local)
            model: Model to use (if applicable)
            cost_per_call: Estimated cost per call in USD
            implementation: Async function implementing the tool
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            backend=backend,
            model=model,
            cost_per_call=cost_per_call,
            implementation=implementation,
        )
        self._metrics[name] = ToolMetrics()
        logger.debug(f"Registered tool: {self.namespace}.{name}")

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        backend: str = "local",
        model: str | None = None,
        cost_per_call: float = 0.0,
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorator to register a tool implementation.

        Example:
            @registry.tool(
                name="generate_base",
                description="Generate YAML",
                backend="cerebras",
            )
            async def generate_base(state, args):
                ...
        """

        def decorator(fn: ToolFn) -> ToolFn:
            self.register(
                name=name,
                description=description,
                parameters=parameters,
                backend=backend,
                model=model,
                cost_per_call=cost_per_call,
                implementation=fn,
            )
            return fn

        return decorator

    def bind(self, name: str, implementation: ToolFn) -> None:
        """Bind an implementation to an existing tool definition.

        Args:
            name: Tool name
            implementation: Async function implementing the tool
        """
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        self._tools[name].implementation = implementation

    async def execute(
        self,
        name: str,
        state: Any,
        args: dict[str, Any],
    ) -> ToolExecutionResult:
        """Execute a tool.

        Args:
            name: Tool name
            state: Current orchestration state
            args: Tool arguments

        Returns:
            ToolExecutionResult with success status and data
        """
        if name not in self._tools:
            return ToolExecutionResult(
                success=False,
                data={},
                error=f"Unknown tool: {name}",
            )

        tool = self._tools[name]
        if tool.implementation is None:
            return ToolExecutionResult(
                success=False,
                data={},
                error=f"Tool not implemented: {name}",
            )

        metrics = self._metrics[name]
        start_time = time.time()

        try:
            result = await tool.implementation(state, args)
            latency_ms = int((time.time() - start_time) * 1000)

            # Check if result indicates failure
            is_failure = result.get("status") in (
                "failed",
                "timeout",
                "error",
            ) if isinstance(result, dict) else False

            # Update metrics
            metrics.calls += 1
            metrics.total_latency_ms += latency_ms
            metrics.total_cost_usd += tool.cost_per_call

            if is_failure:
                metrics.failures += 1
            else:
                metrics.successes += 1

            return ToolExecutionResult(
                success=not is_failure,
                data=result,
                latency_ms=latency_ms,
                cost_usd=tool.cost_per_call,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            metrics.calls += 1
            metrics.failures += 1
            metrics.total_latency_ms += latency_ms

            logger.error(f"Tool {name} failed: {e}")
            return ToolExecutionResult(
                success=False,
                data={},
                error=str(e),
                latency_ms=latency_ms,
            )

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_metrics(self, name: str) -> ToolMetrics | None:
        """Get metrics for a specific tool."""
        return self._metrics.get(name)

    def get_all_metrics(self) -> dict[str, ToolMetrics]:
        """Get metrics for all tools."""
        return dict(self._metrics)

    def to_schema(self) -> list[dict[str, Any]]:
        """Export tools as JSON Schema for orchestrator prompt.

        Returns list of tool definitions in ToolOrchestra format.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "backend": tool.backend,
                "model": tool.model,
                "cost_per_call": tool.cost_per_call,
            }
            for tool in self._tools.values()
        ]

    def format_for_prompt(self) -> str:
        """Format tools for inclusion in system prompt.

        Returns a formatted string listing available tools.
        """
        lines = ["## Available Tools\n"]
        for i, tool in enumerate(self._tools.values(), 1):
            lines.append(f"{i}. **{tool.name}** - {tool.description}")
            if tool.backend != "local":
                lines.append(f"   Backend: {tool.backend}")
            if tool.model:
                lines.append(f"   Model: {tool.model}")
            if tool.cost_per_call > 0:
                lines.append(f"   Cost: ~${tool.cost_per_call:.4f}/call")
            lines.append("")
        return "\n".join(lines)

    def get_total_cost(self) -> float:
        """Get total cost across all tools."""
        return sum(m.total_cost_usd for m in self._metrics.values())

    def reset_metrics(self) -> None:
        """Reset all metrics (useful between runs)."""
        for name in self._metrics:
            self._metrics[name] = ToolMetrics()


# =============================================================================
# Pre-built registries for common orchestrators
# =============================================================================


def create_prospects_registry() -> ToolRegistry:
    """Create tool registry for prospects .base generation.

    Returns a registry with tools for:
    - generate_base: GLM-4.7 via Cerebras
    - diagnose_error: Grok-4.1 fast via XAI
    - use_fallback: Local template fallback
    """
    registry = ToolRegistry("prospects")

    registry.register(
        name="generate_base",
        description="Generate Obsidian .base YAML file for prospect views using Cerebras GLM-4.7",
        parameters={
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
        backend="cerebras",
        model="zai-glm-4.7",
        cost_per_call=0.0001,
    )

    registry.register(
        name="diagnose_error",
        description="Analyze YAML validation errors using XAI Grok-4.1 fast to identify root cause and suggest fixes",
        parameters={
            "type": "object",
            "properties": {
                "yaml_content": {
                    "type": "string",
                    "description": "The generated YAML that failed validation",
                },
                "validation_errors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of validation error messages",
                },
            },
            "required": ["yaml_content", "validation_errors"],
        },
        backend="xai",
        model="grok-4-1-fast",
        cost_per_call=0.001,
    )

    registry.register(
        name="use_fallback",
        description="Use minimal template when LLM generation fails repeatedly",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock symbol"},
            },
            "required": ["symbol"],
        },
        backend="local",
        model=None,
        cost_per_call=0.0,
    )

    return registry
