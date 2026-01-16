"""Agent-driven model addition using Orchestrator-8B.

Uses a ReAct-style agent loop where Orchestrator-8B coordinates the entire
model addition workflow through tool calls.

Architecture:
    ┌─────────────────────────────────────────────────┐
    │           Orchestrator Model (8B)               │
    │  - Receives: model_id to add                    │
    │  - Plans: workflow stages                       │
    │  - Executes: via tool calls to subsystems       │
    │  - Ensures: cleanup on success or failure       │
    └─────────────────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
    ┌─────────┐     ┌──────────┐    ┌───────────┐
    │  GPU    │     │  Coding  │    │   HF API  │
    │ Mgmt    │     │  Model   │    │  Fetch    │
    └─────────┘     └──────────┘    └───────────┘

Usage:
    orchestrator = ModelAddOrchestrator()
    result = await orchestrator.run("mistralai/Mistral-7B-Instruct-v0.3")
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .prompts import ORCHESTRATOR_SYSTEM_PROMPT, MODELSPEC_SYSTEM_PROMPT
from .sandbox import validate_modelspec_code, ValidationResult
from .tools import (
    HFModelData,
    fetch_hf_model_data,
    generate_modelspec_code,
    check_coding_endpoint,
    critique_modelspec_code,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Parsed tool call from orchestrator."""

    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    """Result of tool execution."""

    success: bool
    data: dict[str, Any]
    error: str | None = None


@dataclass
class WorkflowState:
    """Current state of the model add workflow."""

    model_id: str
    started_at: datetime = field(default_factory=datetime.now)
    hf_data: HFModelData | None = None
    generated_code: str | None = None
    validation: ValidationResult | None = None
    critique: dict | None = None
    coding_endpoint_launched: bool = False
    iteration: int = 0
    generation_attempts: int = 0
    tool_history: list[dict] = field(default_factory=list)
    final_status: str = "pending"
    # Fallback state - track when local stack fails and XAI permission granted
    local_coding_failed: bool = False
    xai_fallback_approved: bool = False
    # Hardware context for validation - populated by gpu_health tool
    hardware_context: dict | None = None
    # Feasibility check result - None means not checked yet
    feasibility: dict | None = None  # {feasible: bool, reason: str, requirements: dict}
    # KB entry path if model info was saved (for infeasible models)
    kb_entry_path: str | None = None


class ModelAddOrchestrator:
    """ReAct agent loop for model addition.

    Uses Orchestrator-8B to coordinate the workflow by:
    1. Observing the current state
    2. Calling tools to advance the workflow
    3. Handling errors and retries
    4. Ensuring cleanup on completion
    """

    def __init__(
        self,
        orchestrator_endpoint: str = "orchestrator",
        max_iterations: int = 10,
        max_generation_retries: int = 2,
    ):
        """Initialize the orchestrator.

        Args:
            orchestrator_endpoint: Name of orchestrator endpoint in config
            max_iterations: Maximum tool calls before forcing completion
            max_generation_retries: Maximum code generation attempts
        """
        self.orchestrator_endpoint = orchestrator_endpoint
        self.max_iterations = max_iterations
        self.max_generation_retries = max_generation_retries

        # Tool registry
        self._tools: dict[str, Callable] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Register available tools for the orchestrator."""
        self._tools = {
            "gpu_health": self._tool_gpu_health,
            "model_launch_coding": self._tool_launch_coding,
            "model_stop_coding": self._tool_stop_coding,
            "model_fetch_hf": self._tool_fetch_hf,
            "check_feasibility": self._tool_check_feasibility,
            "save_model_info_to_kb": self._tool_save_model_info_to_kb,
            "model_generate_code": self._tool_generate_code,
            "model_validate_code": self._tool_validate_code,
            "model_xai_critique": self._tool_xai_critique,
            "model_save_pending": self._tool_save_pending,
            "request_xai_permission": self._tool_request_xai_permission,
        }

    async def run(self, model_id: str) -> dict:
        """Execute the full model add workflow.

        Args:
            model_id: HuggingFace model ID to add

        Returns:
            Dict with status, code, validation, and other results
        """
        state = WorkflowState(model_id=model_id)

        try:
            # Run the ReAct loop
            result = await self._react_loop(state)
            return result

        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            return {
                "status": "failed",
                "model_id": model_id,
                "error": str(e),
                "tool_history": state.tool_history,
            }

        finally:
            # Ensure cleanup - stop coding endpoint if we launched it
            if state.coding_endpoint_launched:
                try:
                    await self._tool_stop_coding(state, {})
                except Exception as e:
                    logger.warning(f"Failed to stop coding endpoint: {e}")

    async def _react_loop(self, state: WorkflowState) -> dict:
        """Main ReAct agent loop.

        THOUGHT -> ACTION -> OBSERVATION -> repeat until done
        """
        while state.iteration < self.max_iterations:
            state.iteration += 1

            # Get orchestrator decision
            tool_call = await self._consult_orchestrator(state)

            if tool_call is None:
                # Orchestrator signaled completion
                return self._finalize_result(state)

            # Check if this is a "done" signal
            if tool_call.name == "done":
                return self._parse_final_response(tool_call.args, state)

            # Execute the tool
            result = await self._execute_tool(tool_call, state)

            # Record in history
            state.tool_history.append({
                "iteration": state.iteration,
                "tool": tool_call.name,
                "args": tool_call.args,
                "result": result.data if result.success else {"error": result.error},
                "success": result.success,
            })

            logger.info(
                f"Iteration {state.iteration}: {tool_call.name} -> "
                f"{'success' if result.success else 'failed'}"
            )

        # Max iterations reached
        logger.warning(f"Max iterations ({self.max_iterations}) reached")
        return self._finalize_result(state, forced=True)

    async def _consult_orchestrator(self, state: WorkflowState) -> ToolCall | None:
        """Consult orchestrator model for next action.

        Engine Federation Architecture: uses engine scheduler for inference.
        """
        # Format state as prompt
        prompt = self._format_state_prompt(state)

        try:
            from ...client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                # Engine not available - fail-fast
                logger.error(
                    "Engine not available (#GR.00000001.ENGINEOFF). "
                    "Model add orchestrator requires engine gRPC. "
                    "Start engine: devenv up gaius-engine"
                )
                return self._fallback_next_action(state)

            scheduler = await get_scheduler_proxy()

            # Format as single prompt (scheduler uses prompt, not messages)
            full_prompt = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{prompt}"

            result = await scheduler.complete(
                prompt=full_prompt,
                agent=self.orchestrator_endpoint,
                max_tokens=1000,
                temperature=0.3,
            )

            response = result.content if result else ""

            # Check for empty response
            if not response or not response.strip():
                logger.warning("Orchestrator returned empty response")
                return self._fallback_next_action(state)

            tool_call = self._parse_tool_call(response)

            # If we can't parse a tool call, use fallback
            if tool_call is None:
                logger.warning(f"Could not parse tool call from response: {response[:100]}...")
                return self._fallback_next_action(state)

            return tool_call

        except Exception as e:
            logger.warning(f"Orchestrator consultation failed: {e}")
            # Fallback to simple heuristic
            return self._fallback_next_action(state)

    def _format_state_prompt(self, state: WorkflowState) -> str:
        """Format current state as prompt for orchestrator."""
        lines = [
            f"## Task: Add model '{state.model_id}' to the registry",
            "",
            f"Iteration: {state.iteration}/{self.max_iterations}",
            f"Generation attempts: {state.generation_attempts}/{self.max_generation_retries}",
            "",
            "### Current State:",
        ]

        if state.hf_data:
            lines.append(f"  - HuggingFace data: ✓ fetched")
            lines.append(f"    Name: {state.hf_data.model_id.split('/')[-1]}")
            context = state.hf_data.config.get("max_position_embeddings", "unknown")
            lines.append(f"    Context: {context}")
        else:
            lines.append(f"  - HuggingFace data: ✗ not fetched")

        if state.generated_code:
            lines.append(f"  - Generated code: ✓ ({len(state.generated_code)} chars)")
        else:
            lines.append(f"  - Generated code: ✗ not generated")

        if state.validation:
            v = state.validation
            status = "✓ valid" if v.is_valid else "✗ invalid"
            lines.append(f"  - Validation: {status}")
            if not v.syntax:
                lines.append(f"    Syntax: FAILED")
            if not v.imports:
                lines.append(f"    Imports: FAILED")
            if not v.serve_cmd:
                lines.append(f"    serve_command: FAILED")
            if v.warnings:
                for w in v.warnings[:3]:
                    lines.append(f"    Warning: {w[:100]}")
        else:
            lines.append(f"  - Validation: not run")

        if state.critique:
            score = state.critique.get("score", 0)
            approved = state.critique.get("approved", False)
            lines.append(f"  - Critique: score={score:.2f}, approved={approved}")
        else:
            lines.append(f"  - Critique: not run")

        lines.append(f"  - Coding endpoint: {'✓ running' if state.coding_endpoint_launched else '✗ not running'}")

        if state.tool_history:
            lines.extend(["", "### Recent Tool Calls:"])
            for h in state.tool_history[-5:]:
                status = "✓" if h["success"] else "✗"
                lines.append(f"  {status} {h['tool']}({', '.join(f'{k}={v!r}' for k, v in h['args'].items())})")

        lines.extend(["", "What tool should we call next?"])

        return "\n".join(lines)

    def _parse_tool_call(self, response: str) -> ToolCall | None:
        """Parse tool call from orchestrator response."""
        try:
            # Find JSON in response
            start = response.find("{")
            if start == -1:
                return None

            # Find matching closing brace
            brace_count = 0
            end = start
            for i, c in enumerate(response[start:], start):
                if c == "{":
                    brace_count += 1
                elif c == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break

            json_str = response[start:end]
            data = json.loads(json_str)

            # Check if this is a final response
            if data.get("done"):
                return ToolCall(name="done", args=data)

            tool_name = data.get("tool")
            if not tool_name:
                return None

            return ToolCall(
                name=tool_name,
                args=data.get("args", {}),
            )

        except Exception as e:
            logger.debug(f"Failed to parse tool call: {e}")
            return None

    def _fallback_next_action(self, state: WorkflowState) -> ToolCall:
        """Simple heuristic when orchestrator unavailable.

        Uses observation → heuristic → remediation pattern:
        - Observes: current state, tool history (including failures)
        - Applies heuristics: detects patterns like OOM, connection errors
        - Remediates: skips problematic tools, uses fallbacks
        """
        import os

        # Step 0: Get hardware context early for validation/critique
        if not state.hardware_context:
            # Check if we already tried and failed
            already_tried = any(
                h["tool"] == "gpu_health" for h in state.tool_history
            )
            if not already_tried:
                return ToolCall(name="gpu_health", args={})

        # Step 1: Fetch HuggingFace data
        if not state.hf_data:
            return ToolCall(name="model_fetch_hf", args={"model_id": state.model_id})

        # Step 2: Check feasibility - can this model run on our hardware?
        if state.feasibility is None and state.hardware_context and state.hf_data:
            return ToolCall(name="check_feasibility", args={})

        # Step 3: If infeasible, save info to KB and exit gracefully
        if state.feasibility and not state.feasibility.get("feasible", True):
            # Check if we already saved to KB
            if not state.kb_entry_path:
                return ToolCall(name="save_model_info_to_kb", args={})
            # Already saved - signal done
            return ToolCall(name="done", args={
                "status": "infeasible",
                "message": state.feasibility.get("reason", "Model cannot run on available hardware"),
                "kb_entry": state.kb_entry_path,
                "requirements": state.feasibility.get("requirements", {}),
                "cleanup_complete": True,
            })

        # HEURISTIC: Check if coding launch has failed before
        coding_launch_failed = any(
            h["tool"] == "model_launch_coding" and not h["success"]
            for h in state.tool_history
        )

        # Mark local failure state for later use
        if coding_launch_failed and not state.local_coding_failed:
            state.local_coding_failed = True

        # HEURISTIC: Check if we have XAI API available as fallback
        has_xai_fallback = bool(os.getenv("XAI_API_KEY"))

        if not state.coding_endpoint_launched:
            # REMEDIATION: If coding launch failed, need to handle fallback
            if state.local_coding_failed:
                if has_xai_fallback and state.xai_fallback_approved:
                    # User approved XAI fallback - mark as ready for generation
                    logger.info("Heuristic: XAI fallback approved - proceeding to generate")
                    state.coding_endpoint_launched = True  # Mark as "ready" via XAI
                elif has_xai_fallback:
                    # Check if we already asked for permission
                    already_asked = any(
                        h["tool"] == "request_xai_permission"
                        for h in state.tool_history
                    )
                    if already_asked:
                        # User was asked and declined (or error)
                        logger.warning("Heuristic: User declined XAI fallback")
                        return ToolCall(name="done", args={
                            "status": "failed",
                            "message": "Local coding model failed and user declined XAI fallback",
                            "cleanup_complete": True,
                        })
                    else:
                        # Need user permission - signal this via special tool call
                        logger.info("Heuristic: Local coding failed, requesting XAI permission")
                        return ToolCall(
                            name="request_xai_permission",
                            args={"reason": "Local coding model failed to launch"},
                        )
                else:
                    # No XAI available and local failed - workflow must fail
                    logger.warning("Heuristic: Local coding failed, no XAI available")
                    return ToolCall(name="done", args={
                        "status": "failed",
                        "message": "Local coding model failed and no XAI API key available",
                        "cleanup_complete": True,
                    })
            else:
                # Still try to launch coding endpoint
                return ToolCall(name="model_launch_coding", args={"gpus": "0,1", "timeout": 120})

        if not state.generated_code:
            return ToolCall(
                name="model_generate_code",
                args={
                    "model_id": state.model_id,
                    "hf_data_json": json.dumps({
                        "model_id": state.hf_data.model_id,
                        "api_info": state.hf_data.api_info,
                        "config": state.hf_data.config,
                        "readme": state.hf_data.readme[:2000] if state.hf_data.readme else None,
                    }),
                },
            )

        if not state.validation:
            return ToolCall(
                name="model_validate_code",
                args={"code": state.generated_code, "use_devenv": False},
            )

        # If validation passed, save pending (if not already saved)
        if state.validation.is_valid:
            # HEURISTIC: Check if we already saved successfully
            already_saved = any(
                h["tool"] == "model_save_pending" and h["success"]
                for h in state.tool_history
            )
            if already_saved:
                # Signal done - workflow complete
                logger.info("Heuristic: Save already succeeded - signaling done")
                return ToolCall(name="done", args={
                    "status": "pending_review",
                    "message": "Model saved for review",
                    "cleanup_complete": True,
                })

            return ToolCall(
                name="model_save_pending",
                args={
                    "model_id": state.model_id,
                    "code": state.generated_code,
                    "validation_json": json.dumps({
                        "syntax": state.validation.syntax,
                        "imports": state.validation.imports,
                        "serve_cmd": state.validation.serve_cmd,
                        "variable_name": state.validation.variable_name,
                        "warnings": state.validation.warnings,
                    }),
                },
            )

        # Validation failed - retry if under limit
        if state.generation_attempts < self.max_generation_retries:
            feedback = "; ".join(state.validation.warnings[:3])
            return ToolCall(
                name="model_generate_code",
                args={
                    "model_id": state.model_id,
                    "hf_data_json": json.dumps({
                        "model_id": state.hf_data.model_id,
                        "api_info": state.hf_data.api_info,
                        "config": state.hf_data.config,
                        "readme": state.hf_data.readme[:2000] if state.hf_data.readme else None,
                    }),
                    "critic_feedback": feedback,
                },
            )

        # Out of retries - signal done
        return ToolCall(name="done", args={"status": "failed", "reason": "max_retries"})

    async def _execute_tool(self, tool_call: ToolCall, state: WorkflowState) -> ToolResult:
        """Execute a tool call."""
        tool_fn = self._tools.get(tool_call.name)
        if not tool_fn:
            return ToolResult(
                success=False,
                data={},
                error=f"Unknown tool: {tool_call.name}",
            )

        try:
            result = await tool_fn(state, tool_call.args)

            # Check if the result indicates failure (e.g., status: "failed", "timeout", etc.)
            is_failure = result.get("status") in (
                "failed", "timeout", "oom_error", "process_exited", "declined"
            ) if isinstance(result, dict) else False

            return ToolResult(success=not is_failure, data=result)
        except Exception as e:
            logger.error(f"Tool {tool_call.name} failed: {e}")
            return ToolResult(success=False, data={}, error=str(e))

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def _tool_gpu_health(self, state: WorkflowState, args: dict) -> dict:
        """Check GPU health and store hardware context for later validation."""
        result = {"gpus": [], "count": 0}

        try:
            from ...inference.health import get_health_monitor

            monitor = get_health_monitor()
            gpus = []
            for gpu in monitor.get_all_gpu_health():
                gpus.append({
                    "index": gpu.gpu_id,
                    "utilization": gpu.gpu_utilization_percent,
                    "memory_used_mb": int(gpu.vram_used_gb * 1024),
                    "memory_total_mb": int(gpu.vram_total_gb * 1024),
                    "temperature": gpu.temperature_c,
                })
            result = {"gpus": gpus, "count": len(gpus)}
        except Exception as e:
            # Fallback to nvidia-smi
            import subprocess

            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                gpus = []
                for line in proc.stdout.strip().split("\n"):
                    parts = line.split(", ")
                    if len(parts) >= 5:
                        gpus.append({
                            "index": int(parts[0]),
                            "name": parts[1].strip(),
                            "memory_used_mb": int(parts[2]),
                            "memory_total_mb": int(parts[3]),
                            "utilization": int(parts[4]),
                        })
                result = {"gpus": gpus, "count": len(gpus)}
            else:
                result = {"error": str(e), "gpus": [], "count": 0}

        # Store hardware context for use during validation/critique
        # Extract gpus list with proper typing for type checker
        gpus_list: list[dict[str, object]] = result.get("gpus", [])  # type: ignore[assignment] - Runtime dict has list of GPU dicts
        if gpus_list:
            # Sum memory safely - values could be None or missing
            total_vram = 0
            for g in gpus_list:
                mem = g.get("memory_total_mb")
                if isinstance(mem, int):
                    total_vram += mem
            state.hardware_context = {
                "gpu_count": result["count"],
                "gpus": gpus_list,
                "total_vram_mb": total_vram,
                "gpu_model": str(gpus_list[0].get("name", "unknown")) if gpus_list else "unknown",
            }

        return result

    async def _tool_launch_coding(self, state: WorkflowState, args: dict) -> dict:
        """Launch coding model endpoint via engine.

        Uses the engine's ensure_endpoint which checks resource availability
        before attempting to start.

        Observes OOM and other failures, returns structured error info
        for heuristic remediation by fallback logic.
        """
        timeout = args.get("timeout", 120)

        # First check if already running
        check = await check_coding_endpoint(8082)
        if check.get("healthy"):
            state.coding_endpoint_launched = True
            return {"status": "already_running", "model_id": check.get("model_id")}

        # Use engine client for proper resource management
        try:
            from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Check if engine is available
            if not use_engine_proxy():
                # Engine not running - fail fast
                state.local_coding_failed = True
                return {
                    "status": "failed",
                    "error_type": "engine_not_running",
                    "message": "Gaius engine not running. Start with: gaius-engine start",
                    "remediation": "Start the gaius-engine daemon first",
                }

            orch = await get_orchestrator_proxy()

            # Use ensure_endpoint - checks resources before starting
            result = await orch.ensure_endpoint("coding")

            if result.get("healthy"):
                state.coding_endpoint_launched = True
                return {
                    "status": "started",
                    "model_id": result.get("model"),
                    "port": result.get("port"),
                    "gpu_ids": result.get("gpu_ids", []),
                }

            # Check specific failure reasons
            status = result.get("status", "unknown")

            if status == "insufficient_resources":
                state.local_coding_failed = True
                return {
                    "status": "insufficient_resources",
                    "error_type": "gpu_unavailable",
                    "message": result.get("message", "Not enough GPUs available"),
                    "remediation": "Stop other endpoints or use XAI API fallback",
                }

            if status == "no_contiguous_gpus":
                state.local_coding_failed = True
                return {
                    "status": "no_contiguous_gpus",
                    "error_type": "gpu_fragmentation",
                    "message": result.get("message", "Need contiguous GPUs for tensor parallel"),
                    "remediation": "Restart engine or use XAI API fallback",
                }

            # Generic failure
            state.local_coding_failed = True
            return {
                "status": "failed",
                "error_type": "startup_failed",
                "message": result.get("message", f"Endpoint status: {status}"),
                "remediation": "Check engine logs or use XAI API fallback",
            }

        except ConnectionError as e:
            state.local_coding_failed = True
            return {
                "status": "failed",
                "error_type": "engine_not_running",
                "message": f"Cannot connect to engine: {e}",
                "remediation": "Start the gaius-engine daemon",
            }
        except Exception as e:
            state.local_coding_failed = True
            return {"status": "failed", "error": str(e)}

    async def _tool_stop_coding(self, state: WorkflowState, args: dict) -> dict:
        """Stop coding model endpoint via engine."""
        try:
            from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            if not use_engine_proxy():
                # Engine not running - nothing to stop
                state.coding_endpoint_launched = False
                return {"status": "skipped", "reason": "Engine not running"}

            orch = await get_orchestrator_proxy()
            success = await orch.stop_endpoint("coding")
            state.coding_endpoint_launched = False
            return {"status": "stopped" if success else "failed"}
        except Exception as e:
            state.coding_endpoint_launched = False  # Mark as not running either way
            return {"status": "failed", "error": str(e)}

    async def _tool_fetch_hf(self, state: WorkflowState, args: dict) -> dict:
        """Fetch HuggingFace model data."""
        model_id = args.get("model_id", state.model_id)

        hf_data = await fetch_hf_model_data(model_id)
        state.hf_data = hf_data

        return {
            "model_id": hf_data.model_id,
            "has_api_info": bool(hf_data.api_info),
            "has_config": bool(hf_data.config),
            "has_readme": bool(hf_data.readme),
            "context_length": hf_data.config.get("max_position_embeddings"),
            "architectures": hf_data.config.get("architectures", []),
        }

    async def _tool_check_feasibility(self, state: WorkflowState, args: dict) -> dict:
        """Check if model can run on available hardware.

        Compares model requirements (params, VRAM) against hardware context.
        Fails fast for models that clearly cannot run locally.
        """
        if not state.hf_data:
            return {"error": "No HuggingFace data. Call model_fetch_hf first."}

        if not state.hardware_context:
            return {"error": "No hardware context. Call gpu_health first."}

        # Extract model size
        api_info = state.hf_data.api_info
        config = state.hf_data.config
        model_name = state.model_id.split("/")[-1]

        # Get parameter count
        safetensors = api_info.get("safetensors", {})
        if safetensors and safetensors.get("total"):
            params_b = safetensors["total"] / 1e9
        else:
            # Parse from name (e.g., "123B", "24B")
            import re
            match = re.search(r"(\d+(?:\.\d+)?)[Bb]", model_name)
            params_b = float(match.group(1)) if match else 7.0

        # Calculate VRAM requirements
        # BF16: ~2 bytes per param, plus ~20% overhead for KV cache, activations
        vram_required_gb = (params_b * 2 * 1.2)

        # Get available hardware
        hw = state.hardware_context
        total_vram_gb = hw.get("total_vram_mb", 0) / 1024
        gpu_count = hw.get("gpu_count", 0)
        gpu_model = hw.get("gpu_model", "unknown")
        per_gpu_vram_gb = total_vram_gb / gpu_count if gpu_count > 0 else 0

        # Determine minimum TP needed
        min_tp_needed = 1
        while min_tp_needed <= 8:
            if vram_required_gb / min_tp_needed <= per_gpu_vram_gb * 0.9:  # 90% threshold
                break
            min_tp_needed *= 2

        # Check feasibility
        feasible = True
        reasons = []

        if min_tp_needed > gpu_count:
            feasible = False
            reasons.append(
                f"Model requires TP={min_tp_needed} but only {gpu_count} GPUs available"
            )

        if vram_required_gb > total_vram_gb:
            feasible = False
            reasons.append(
                f"Model requires ~{vram_required_gb:.0f}GB VRAM but only {total_vram_gb:.0f}GB available"
            )

        # Build requirements summary
        requirements = {
            "params_b": round(params_b, 1),
            "vram_required_gb": round(vram_required_gb, 1),
            "min_tensor_parallel": min_tp_needed,
            "min_gpus_needed": min_tp_needed,
            "context_length": config.get("max_position_embeddings", "unknown"),
        }

        state.feasibility = {
            "feasible": feasible,
            "reason": "; ".join(reasons) if reasons else "Model can run on available hardware",
            "requirements": requirements,
            "hardware": {
                "gpu_count": gpu_count,
                "gpu_model": gpu_model,
                "total_vram_gb": round(total_vram_gb, 1),
                "per_gpu_vram_gb": round(per_gpu_vram_gb, 1),
            },
        }

        return state.feasibility

    async def _tool_save_model_info_to_kb(self, state: WorkflowState, args: dict) -> dict:
        """Save model information to KB for reference (used for infeasible models).

        Creates a zettelkasten note with model specs and requirements,
        even though the model can't be added to the registry.
        """
        if not state.hf_data:
            return {"error": "No HuggingFace data available"}

        from datetime import datetime

        # Build markdown content
        hf = state.hf_data
        feasibility = state.feasibility or {}
        requirements = feasibility.get("requirements", {})
        hardware = feasibility.get("hardware", {})

        model_name = state.model_id.split("/")[-1]
        tags = hf.api_info.get("tags", [])[:10]

        content = f"""# {model_name}

---
created: {datetime.now().strftime('%Y-%m-%d')}
type: model-reference
status: infeasible
model_id: {state.model_id}
---

## Overview

**Model ID**: `{state.model_id}`
**Parameters**: {requirements.get('params_b', 'unknown')}B
**Context Length**: {requirements.get('context_length', 'unknown')}
**Architecture**: {', '.join(hf.config.get('architectures', ['unknown']))}
**Tags**: {', '.join(tags)}

## Hardware Requirements

| Requirement | Value |
|-------------|-------|
| VRAM Required | ~{requirements.get('vram_required_gb', '?')}GB |
| Min Tensor Parallel | {requirements.get('min_tensor_parallel', '?')} |
| Min GPUs | {requirements.get('min_gpus_needed', '?')} |

## Local Hardware

| Resource | Available |
|----------|-----------|
| GPUs | {hardware.get('gpu_count', '?')}x {hardware.get('gpu_model', 'unknown')} |
| Total VRAM | {hardware.get('total_vram_gb', '?')}GB |
| Per-GPU VRAM | {hardware.get('per_gpu_vram_gb', '?')}GB |

## Feasibility

**Status**: [FAIL] Cannot run locally
**Reason**: {feasibility.get('reason', 'Unknown')}

## Links

- [HuggingFace]({f'https://huggingface.co/{state.model_id}'})
"""

        # Add cloud suggestions from Lambda Labs
        vram_required = requirements.get('vram_required_gb', 0)
        # For cloud, use TP=8 as max (8-GPU instances available)
        min_tp_cloud = min(requirements.get('min_tensor_parallel', 8), 8)

        best_instance_info = None
        try:
            from ...providers.lambdalabs import LambdaLabsClient
            client = LambdaLabsClient()

            # Find best available instance (we're already in async context)
            best = await client.find_best_available_instance(vram_required, min_tp_cloud)

            if best:
                inst, regions, cost = best
                best_instance_info = {
                    "instance_type": inst.name,
                    "gpu_model": inst.gpu_model,
                    "gpu_count": inst.gpu_count,
                    "total_vram_gb": inst.total_vram_gb,
                    "cost_per_hour": cost,
                    "regions": regions,
                }

                content += f"""
## Recommended Cloud Instance

**Best Available**: `{inst.name}`
- **GPUs**: {inst.gpu_count}x {inst.gpu_model}
- **VRAM**: {inst.total_vram_gb}GB total
- **Cost**: ${cost:.2f}/hr
- **Regions**: {', '.join(regions[:3])}{' (+more)' if len(regions) > 3 else ''}

"""

            # Also add the full options table
            cloud_section = client.format_suggestions_markdown(vram_required, min_tp_cloud)
            if "No Lambda Labs instances" not in cloud_section:
                content += f"{cloud_section}\n"

        except Exception as e:
            logger.debug(f"Lambda Labs lookup failed: {e}")
            content += """
## Future Options

- Distributed inference across multiple nodes
- Federated engine with remote execution
- Quantized versions (GPTQ, AWQ, GGUF)
- Cloud GPU providers (Lambda Labs, etc.)
"""

        # Check for Cerebras hosted inference option
        try:
            from ...providers.cerebras import CerebrasClient
            cerebras_client = CerebrasClient()

            # Get GPU cost for comparison (use best instance if found)
            gpu_cost_raw = best_instance_info.get("cost_per_hour") if best_instance_info else None
            gpu_cost: float | None = None
            if gpu_cost_raw is not None and isinstance(gpu_cost_raw, (int, float, str)):
                try:
                    gpu_cost = float(gpu_cost_raw)
                except (ValueError, TypeError):
                    pass

            cerebras_section = cerebras_client.format_options_markdown(
                state.model_id,
                gpu_cost_per_hour=gpu_cost,
            )
            if cerebras_section:
                content += f"\n{cerebras_section}\n"
        except Exception as e:
            logger.debug(f"Cerebras lookup failed: {e}")

        # Append README excerpt if available
        if hf.readme:
            content += f"\n## Model Card (excerpt)\n\n{hf.readme[:1500]}...\n"

        # Save to KB scratch directory
        from pathlib import Path

        today = datetime.now().strftime("%Y-%m-%d")
        time_prefix = datetime.now().strftime("%H%M%S")
        slug = model_name.lower().replace("-", "_").replace(".", "_")[:30]

        # Try to get KB root from config
        try:
            from ...core.config import get_config
            config = get_config()
            kb_root = Path(config.kb.root)
        except Exception:
            kb_root = Path("build/dev")

        output_dir = kb_root / "scratch" / today / "models"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{time_prefix}_{slug}.md"
        output_path.write_text(content)

        state.kb_entry_path = str(output_path)

        result = {
            "status": "saved",
            "path": str(output_path),
            "model_id": state.model_id,
        }

        # Include best available instance if found
        if best_instance_info:
            result["best_cloud_instance"] = best_instance_info

        return result

    async def _tool_generate_code(self, state: WorkflowState, args: dict) -> dict:
        """Generate ModelSpec code."""
        model_id = args.get("model_id", state.model_id)
        hf_data_json = args.get("hf_data_json", "")
        critic_feedback = args.get("critic_feedback", "")

        # Parse HF data if provided as JSON
        if hf_data_json and not state.hf_data:
            data = json.loads(hf_data_json)
            state.hf_data = HFModelData(
                model_id=data.get("model_id", model_id),
                api_info=data.get("api_info", {}),
                config=data.get("config", {}),
                readme=data.get("readme"),
            )

        if not state.hf_data:
            return {"error": "No HuggingFace data available. Call model_fetch_hf first."}

        # Get coding endpoint
        check = await check_coding_endpoint(8082)
        if check.get("healthy"):
            endpoint_url = "http://localhost:8082/v1"
            coding_model = check.get("model_id", "unknown")
        else:
            # Try XAI fallback
            import os
            if os.getenv("XAI_API_KEY"):
                endpoint_url = "https://api.x.ai/v1"
                coding_model = "grok-2-latest"
            else:
                return {"error": "No coding endpoint available and XAI_API_KEY not set"}

        state.generation_attempts += 1

        result = await generate_modelspec_code(
            hf_data=state.hf_data,
            endpoint_url=endpoint_url,
            model_id=coding_model,
            system_prompt=MODELSPEC_SYSTEM_PROMPT,
            critic_feedback=critic_feedback or None,
        )

        state.generated_code = result.code
        state.validation = None  # Reset validation on new code

        return {
            "code_length": len(result.code),
            "model_used": result.model_used,
            "endpoint_used": result.endpoint_used,
            "attempt": state.generation_attempts,
        }

    async def _tool_validate_code(self, state: WorkflowState, args: dict) -> dict:
        """Validate generated code."""
        code = args.get("code", state.generated_code)
        use_devenv = args.get("use_devenv", False)

        if not code:
            return {"error": "No code to validate"}

        result = validate_modelspec_code(code, use_devenv=use_devenv)
        state.validation = result

        return {
            "valid": result.is_valid,
            "syntax": result.syntax,
            "imports": result.imports,
            "serve_cmd": result.serve_cmd,
            "variable_name": result.variable_name,
            "warnings": result.warnings,
        }

    async def _tool_xai_critique(self, state: WorkflowState, args: dict) -> dict:
        """Get XAI critique of generated code with hardware context."""
        code = args.get("code", state.generated_code)
        model_id = args.get("model_id", state.model_id)

        if not code:
            return {"error": "No code to critique"}

        if not state.hf_data:
            return {"error": "No HuggingFace data for context"}

        # Pass hardware context if available for validation
        result = await critique_modelspec_code(
            code,
            state.hf_data,
            hardware_context=state.hardware_context,
        )
        state.critique = {
            "score": result.score,
            "issues": result.issues,
            "suggestions": result.suggestions,
            "approved": result.approved,
            "model_used": result.model_used,
        }

        return state.critique

    async def _tool_save_pending(self, state: WorkflowState, args: dict) -> dict:
        """Save generated code for user confirmation."""
        model_id = args.get("model_id", state.model_id)
        code = args.get("code", state.generated_code)
        validation_json = args.get("validation_json", "")
        critique_json = args.get("critique_json", "")

        if not code:
            return {"error": "No code to save"}

        # Parse validation
        if validation_json:
            validation = json.loads(validation_json)
        elif state.validation:
            validation = {
                "syntax": state.validation.syntax,
                "imports": state.validation.imports,
                "serve_cmd": state.validation.serve_cmd,
                "variable_name": state.validation.variable_name,
                "warnings": state.validation.warnings,
            }
        else:
            validation = {}

        # Parse critique
        if critique_json:
            critique = json.loads(critique_json)
        elif state.critique:
            critique = state.critique
        else:
            critique = {}

        # Save to file
        pending_data = {
            "model_id": model_id,
            "code": code,
            "validation": validation,
            "critique": critique,
            "generated_at": datetime.now().isoformat(),
        }

        # Get KB root from config
        try:
            from ...core.config import get_config
            config = get_config()
            pending_path = Path(config.kb.root) / ".pending_model_add.json"
        except Exception:
            pending_path = Path("build/dev/.pending_model_add.json")

        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(json.dumps(pending_data, indent=2))

        state.final_status = "pending_review"

        return {
            "status": "saved",
            "path": str(pending_path),
            "model_id": model_id,
            "variable_name": validation.get("variable_name"),
        }

    async def _tool_request_xai_permission(self, state: WorkflowState, args: dict) -> dict:
        """Request user permission to use XAI frontier API as fallback.

        This is called when the local coding model fails and XAI_API_KEY is available.
        Prompts the user for consent before making external API calls.
        """
        reason = args.get("reason", "Local model unavailable")

        # Prompt user via console
        print(f"\n[!] Local coding model failed: {reason}")
        print("   XAI API key is available as fallback.")
        print("   This will use the XAI Grok API for code generation.")
        print()

        try:
            response = input("Use XAI API for code generation? [y/N]: ").strip().lower()
            approved = response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            # Non-interactive mode or user cancelled
            approved = False

        state.xai_fallback_approved = approved

        if approved:
            logger.info("User approved XAI fallback")
            return {
                "status": "approved",
                "message": "XAI API fallback approved by user",
            }
        else:
            logger.info("User declined XAI fallback")
            return {
                "status": "declined",
                "message": "User declined XAI API fallback",
            }

    # =========================================================================
    # Result Finalization
    # =========================================================================

    def _finalize_result(self, state: WorkflowState, forced: bool = False) -> dict:
        """Finalize the workflow result."""
        # Determine status
        if state.final_status != "pending":
            status = state.final_status
        elif state.feasibility and not state.feasibility.get("feasible", True):
            status = "infeasible"
        elif state.validation and state.validation.is_valid:
            status = "pending_review"
        else:
            status = "failed"

        result = {
            "status": status,
            "model_id": state.model_id,
            "iterations": state.iteration,
            "forced_completion": forced,
            "tool_history": state.tool_history,
        }

        # Add feasibility info if model couldn't run locally
        if state.feasibility:
            result["feasibility"] = state.feasibility
            if state.kb_entry_path:
                result["kb_entry"] = state.kb_entry_path

        # Add code generation info if we got that far
        if state.generated_code:
            result["generated_code"] = state.generated_code
            result["generation_attempts"] = state.generation_attempts

        if state.validation:
            result["validation"] = {
                "syntax": state.validation.syntax,
                "imports": state.validation.imports,
                "serve_cmd": state.validation.serve_cmd,
                "variable_name": state.validation.variable_name,
                "warnings": state.validation.warnings,
            }

        if state.critique:
            result["critique"] = state.critique

        # Add next steps based on status
        if status == "pending_review":
            result["next_steps"] = [
                "/model add-confirm  - Write to registry",
                "/model add-cancel   - Discard",
            ]
        elif status == "infeasible":
            result["next_steps"] = [
                f"View model info: cat {state.kb_entry_path}" if state.kb_entry_path else "Model info saved to KB",
            ]

        return result

    def _parse_final_response(self, args: dict, state: WorkflowState) -> dict:
        """Parse final response from orchestrator."""
        status = args.get("status", "failed")
        state.final_status = status

        result = self._finalize_result(state)
        result["message"] = args.get("message", "")
        result["cleanup_complete"] = args.get("cleanup_complete", False)

        return result
