"""Orchestrator-managed evolution for complex adaptive self-improvement.

Uses the Orchestrator model (nvidia/Orchestrator-8B) as a meta-cognitive
coordinator for the evolution process. Instead of a simple state machine,
the orchestrator observes system state, diagnoses issues, and adapts
strategy in real-time.

Key capabilities:
- Diagnose failures (missing agents, stuck processes, resource issues)
- Adapt strategy based on outcomes
- Coordinate resources across multiple models/GPUs
- Maintain system health over long-running overnight sessions
- Learn from patterns in cycle history

Architecture:
    ┌─────────────────────────────────────────────────┐
    │           Orchestrator Model (8B)               │
    │  - Observes: GPU health, cycle history, agents  │
    │  - Diagnoses: failures, bottlenecks, patterns   │
    │  - Plans: next action, strategy adjustments     │
    │  - Executes: via tool calls to subsystems       │
    └─────────────────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
    ┌─────────┐     ┌──────────┐    ┌───────────┐
    │ GPU     │     │ Agent    │    │ Evolution │
    │ Health  │     │ Registry │    │ Optimizer │
    └─────────┘     └──────────┘    └───────────┘

Usage:
    orchestrated = OrchestratedEvolution()
    await orchestrated.start()

    # Orchestrator runs autonomously, making decisions about:
    # - Which agent to optimize next
    # - When to back off vs retry
    # - How to handle failures
    # - Resource allocation

    await orchestrated.stop()
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OrchestratorAction(Enum):
    """Actions the orchestrator can take."""
    OPTIMIZE_AGENT = "optimize_agent"
    SKIP_AGENT = "skip_agent"
    RESTART_ENDPOINT = "restart_endpoint"
    WAIT = "wait"
    DIAGNOSE = "diagnose"
    ADJUST_STRATEGY = "adjust_strategy"
    COLLECT_EXAMPLES = "collect_examples"
    REPORT_STATUS = "report_status"
    SHUTDOWN = "shutdown"


@dataclass
class SystemObservation:
    """Current system state observed by orchestrator."""
    timestamp: datetime

    # GPU state
    gpu_health: list[dict]  # Per-GPU utilization, memory, temp
    endpoints_running: dict[str, bool]  # endpoint -> running

    # Agent state
    available_agents: list[str]
    agent_example_counts: dict[str, int]  # agent -> training examples available
    agent_active_versions: dict[str, bool]  # agent -> has active version

    # Recent history
    recent_cycles: list[dict]  # Last N evolution cycles
    failure_streak: int  # Consecutive failures
    success_streak: int  # Consecutive successes

    # Current session
    session_start: datetime
    cycles_this_session: int
    improvements_this_session: float


@dataclass
class OrchestratorDecision:
    """Decision made by orchestrator."""
    action: OrchestratorAction
    target: str | None = None  # Agent ID, endpoint name, etc.
    parameters: dict = field(default_factory=dict)
    reasoning: str = ""  # Explanation for decision
    confidence: float = 1.0


class OrchestratedEvolution:
    """Orchestrator-managed evolution system.

    Uses an LLM orchestrator to make intelligent decisions about
    the evolution process, adapting to failures and optimizing
    resource usage.
    """

    ORCHESTRATOR_SYSTEM_PROMPT = """You are the Evolution Orchestrator for an AI agent improvement system.

Your role is to manage overnight self-improvement runs, making intelligent decisions about:
1. Which agent to optimize next
2. When to retry vs skip problematic agents
3. How to handle failures and stuck processes
4. When to back off and conserve resources

You receive observations about:
- GPU health (utilization, memory, temperature)
- Available agents and their training example counts
- Recent evolution cycle history (successes, failures, durations)
- Current session metrics

You respond with a JSON decision:
{
    "action": "optimize_agent|skip_agent|wait|diagnose|restart_endpoint|adjust_strategy|shutdown",
    "target": "agent_id or endpoint_name",
    "parameters": {},
    "reasoning": "Brief explanation",
    "confidence": 0.0-1.0
}

Guidelines:
- If an agent fails repeatedly (3+ times), skip it and move on
- If examples are insufficient (<5), skip that agent
- If GPU memory is >90%, wait before starting new cycles
- If all agents have been tried and failed, diagnose the issue
- After 10+ successful cycles, consider stopping to let humans review
- If stuck for >30 minutes with no progress, report status and wait

Be concise and decisive. The system should make steady progress without human intervention."""

    def __init__(
        self,
        orchestrator_endpoint: str = "orchestrator",
        max_consecutive_failures: int = 5,
        session_timeout_hours: float = 12.0,
    ):
        """Initialize orchestrated evolution.

        Args:
            orchestrator_endpoint: Endpoint name for orchestrator model
            max_consecutive_failures: Stop after this many failures in a row
            session_timeout_hours: Maximum session duration
        """
        self.orchestrator_endpoint = orchestrator_endpoint
        self.max_consecutive_failures = max_consecutive_failures
        self.session_timeout = timedelta(hours=session_timeout_hours)

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._session_start: datetime | None = None
        self._cycles_completed = 0
        self._total_improvement = 0.0
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_decision: OrchestratorDecision | None = None

        # History for pattern detection
        self._cycle_history: list[dict] = []
        self._decision_history: list[OrchestratorDecision] = []

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start orchestrated evolution."""
        if self._running:
            logger.warning("Orchestrated evolution already running")
            return

        self._running = True
        self._session_start = datetime.now()
        self._task = asyncio.create_task(self._orchestration_loop())
        logger.info("Orchestrated evolution started")

    async def stop(self) -> None:
        """Stop orchestrated evolution gracefully."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(
            f"Orchestrated evolution stopped. "
            f"Cycles: {self._cycles_completed}, "
            f"Improvement: {self._total_improvement:.1f}%"
        )

    def get_status(self) -> dict:
        """Get current status."""
        return {
            "running": self._running,
            "session_start": self._session_start.isoformat() if self._session_start else None,
            "cycles_completed": self._cycles_completed,
            "total_improvement": self._total_improvement,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "last_decision": {
                "action": self._last_decision.action.value,
                "target": self._last_decision.target,
                "reasoning": self._last_decision.reasoning,
            } if self._last_decision else None,
        }

    async def _orchestration_loop(self) -> None:
        """Main orchestration loop."""
        logger.info("Orchestration loop started")

        while self._running:
            try:
                # Check session timeout
                if self._session_start:
                    elapsed = datetime.now() - self._session_start
                    if elapsed > self.session_timeout:
                        logger.info("Session timeout reached")
                        break

                # Check failure limit
                if self._consecutive_failures >= self.max_consecutive_failures:
                    logger.warning(
                        f"Max consecutive failures ({self.max_consecutive_failures}) reached, "
                        "pausing orchestration"
                    )
                    # Wait then reset counter to try again
                    await asyncio.sleep(300)  # 5 minute backoff
                    self._consecutive_failures = 0
                    continue

                # Gather observations
                observation = await self._gather_observation()

                # Consult orchestrator for decision
                decision = await self._consult_orchestrator(observation)
                self._last_decision = decision
                self._decision_history.append(decision)

                logger.info(
                    f"Orchestrator decision: {decision.action.value} "
                    f"target={decision.target} "
                    f"reason={decision.reasoning}"
                )

                # Execute decision
                result = await self._execute_decision(decision)

                # Update state based on result
                await self._update_state(decision, result)

                # Brief pause between cycles
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Orchestration loop error: {e}")
                self._consecutive_failures += 1
                await asyncio.sleep(30)  # Back off on errors

    async def _gather_observation(self) -> SystemObservation:
        """Gather current system state for orchestrator."""
        # GPU health
        gpu_health = []
        endpoints_running = {}

        try:
            from ...inference.health import get_health_monitor
            monitor = get_health_monitor()

            for gpu in monitor.get_all_gpu_health():
                gpu_health.append({
                    "index": gpu.gpu_id,
                    "utilization": gpu.gpu_utilization_percent,
                    "memory_used": gpu.vram_used_gb * 1024,  # Convert GB to MB
                    "memory_total": gpu.vram_total_gb * 1024,  # Convert GB to MB
                    "temperature": gpu.temperature_c,
                })
        except Exception as e:
            logger.debug(f"Failed to get GPU health: {e}")

        try:
            from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Engine Federation Architecture: endpoint status via engine gRPC
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                status = await orch._get_status_async()

                for name, info in status.get("endpoints", {}).items():
                    endpoints_running[name] = info.get("status") == "healthy"
            else:
                # Engine not available - cannot get authoritative endpoint status
                logger.warning(
                    "Engine not available (#GR.00000001.ENGINEOFF). "
                    "Cannot get endpoint status. Start engine: devenv up gaius-engine"
                )
        except Exception as e:
            logger.debug(f"Failed to get endpoint status: {e}")

        # Also probe endpoints via HTTP to detect externally running processes
        import httpx
        from ...inference.router import get_endpoint_router
        try:
            router = get_endpoint_router()
            for name, endpoint in router.config.endpoints.items():
                if name not in endpoints_running or not endpoints_running[name]:
                    try:
                        resp = httpx.get(f"{endpoint.url}/models", timeout=1.0)
                        endpoints_running[name] = resp.status_code == 200
                    except Exception:
                        if name not in endpoints_running:
                            endpoints_running[name] = False
        except Exception as e:
            logger.debug(f"Failed to probe endpoints via HTTP: {e}")

        # Agent state
        available_agents = []
        agent_example_counts = {}
        agent_active_versions = {}

        try:
            from ..roles import SWARM_ROLES
            # Convert AgentRole enum keys to their string values
            available_agents = [role.value.lower() for role in SWARM_ROLES.keys()]
        except Exception:
            available_agents = ["leader", "risk", "critic", "opportunity", "domain"]

        try:
            from .collector import get_training_collector
            collector = get_training_collector()

            for agent_id in available_agents:
                examples = await collector.collect_examples(agent_id, max_examples=100)
                agent_example_counts[agent_id] = len(examples)
        except Exception as e:
            logger.debug(f"Failed to get example counts: {e}")

        # Check for active versions
        try:
            from ...models.versioning import get_version_manager
            manager = get_version_manager()

            for agent_id in available_agents:
                version = await manager.get_active_version(agent_id)
                agent_active_versions[agent_id] = version is not None
        except Exception as e:
            logger.debug(f"Failed to check agent versions: {e}")

        # Recent cycles from DB
        recent_cycles = []
        try:
            import asyncpg
            import os

            from ...core.config import get_database_url
            url = get_database_url()
            conn = await asyncpg.connect(url)
            try:
                rows = await conn.fetch("""
                    SELECT agent_id, success, improvement_percent, duration_ms,
                           started_at, error
                    FROM evolution_cycles
                    ORDER BY started_at DESC
                    LIMIT 20
                """)

                for r in rows:
                    recent_cycles.append({
                        "agent_id": r["agent_id"],
                        "success": r["success"],
                        "improvement": r["improvement_percent"],
                        "duration_ms": r["duration_ms"],
                        "timestamp": r["started_at"].isoformat() if r["started_at"] else None,
                        "error": r["error"],
                    })
            finally:
                await conn.close()
        except Exception as e:
            logger.debug(f"Failed to get cycle history: {e}")

        return SystemObservation(
            timestamp=datetime.now(),
            gpu_health=gpu_health,
            endpoints_running=endpoints_running,
            available_agents=available_agents,
            agent_example_counts=agent_example_counts,
            agent_active_versions=agent_active_versions,
            recent_cycles=recent_cycles,
            failure_streak=self._consecutive_failures,
            success_streak=self._consecutive_successes,
            session_start=self._session_start or datetime.now(),
            cycles_this_session=self._cycles_completed,
            improvements_this_session=self._total_improvement,
        )

    async def _consult_orchestrator(
        self,
        observation: SystemObservation
    ) -> OrchestratorDecision:
        """Consult orchestrator model for next action."""
        # Format observation as prompt
        obs_text = self._format_observation(observation)

        try:
            from ...inference.router import get_endpoint_router

            router = get_endpoint_router()

            # Use chat completion format
            messages = [
                {"role": "system", "content": self.ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": obs_text},
            ]

            result = await router.complete(
                messages=messages,
                endpoint=self.orchestrator_endpoint,
                max_tokens=1500,  # Enough for thinking + JSON response
                temperature=0.3,  # More deterministic for operational decisions
            )

            # Extract response text
            response = result.content if hasattr(result, 'content') else str(result)

            # Parse JSON response
            decision = self._parse_decision(response)
            return decision

        except Exception as e:
            logger.warning(f"Orchestrator consultation failed: {e}")
            # Fallback to simple heuristic
            return self._fallback_decision(observation)

    def _format_observation(self, obs: SystemObservation) -> str:
        """Format observation as text for orchestrator."""
        lines = [
            "## Current System State",
            f"Timestamp: {obs.timestamp.isoformat()}",
            f"Session duration: {(obs.timestamp - obs.session_start).total_seconds() / 3600:.1f} hours",
            "",
            "### GPU Health",
        ]

        for gpu in obs.gpu_health:
            lines.append(
                f"  GPU {gpu['index']}: {gpu['utilization']:.0f}% util, "
                f"{gpu['memory_used']}/{gpu['memory_total']}MB, "
                f"{gpu['temperature']}°C"
            )

        lines.extend([
            "",
            "### Endpoints",
        ])
        for name, running in obs.endpoints_running.items():
            status = "✓ running" if running else "✗ stopped"
            lines.append(f"  {name}: {status}")

        lines.extend([
            "",
            "### Agents",
        ])
        for agent in obs.available_agents:
            examples = obs.agent_example_counts.get(agent, 0)
            has_version = obs.agent_active_versions.get(agent, False)
            version_status = "✓" if has_version else "✗ no version"
            lines.append(f"  {agent}: {examples} examples, {version_status}")

        lines.extend([
            "",
            "### Recent Cycles (newest first)",
        ])
        for cycle in obs.recent_cycles[:10]:
            status = "✓" if cycle["success"] else "✗"
            improvement = cycle.get("improvement", 0) or 0
            duration = (cycle.get("duration_ms") or 0) / 1000
            error = f" ({cycle['error'][:30]}...)" if cycle.get("error") else ""
            lines.append(
                f"  {status} {cycle['agent_id']}: {improvement:.1f}% in {duration:.1f}s{error}"
            )

        lines.extend([
            "",
            "### Session Metrics",
            f"  Cycles completed: {obs.cycles_this_session}",
            f"  Total improvement: {obs.improvements_this_session:.1f}%",
            f"  Failure streak: {obs.failure_streak}",
            f"  Success streak: {obs.success_streak}",
            "",
            "What action should we take next?",
        ])

        return "\n".join(lines)

    def _parse_decision(self, response: str) -> OrchestratorDecision:
        """Parse orchestrator response into decision."""
        try:
            # Extract JSON from response - find balanced braces
            # First try to find JSON by looking for opening brace after any thinking tags
            start_idx = response.find('{')
            if start_idx != -1:
                # Find matching closing brace (handle nested braces)
                brace_count = 0
                end_idx = start_idx
                for i, c in enumerate(response[start_idx:], start_idx):
                    if c == '{':
                        brace_count += 1
                    elif c == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break

                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)

                action = OrchestratorAction(data.get("action", "wait"))

                return OrchestratorDecision(
                    action=action,
                    target=data.get("target"),
                    parameters=data.get("parameters", {}),
                    reasoning=data.get("reasoning", ""),
                    confidence=data.get("confidence", 0.8),
                )
        except Exception as e:
            logger.debug(f"Failed to parse decision: {e}")

        # Default to wait
        return OrchestratorDecision(
            action=OrchestratorAction.WAIT,
            reasoning="Failed to parse orchestrator response",
            confidence=0.5,
        )

    def _fallback_decision(self, obs: SystemObservation) -> OrchestratorDecision:
        """Simple heuristic when orchestrator unavailable."""
        # Find agent with examples that hasn't failed recently
        # Note: we don't require active versions - the optimizer will create one
        recent_failures = {
            c["agent_id"] for c in obs.recent_cycles[:5]
            if not c["success"]
        }

        # First pass: agents with examples that haven't failed recently
        for agent in obs.available_agents:
            if agent in recent_failures:
                continue
            if obs.agent_example_counts.get(agent, 0) < 5:
                continue

            return OrchestratorDecision(
                action=OrchestratorAction.OPTIMIZE_AGENT,
                target=agent,
                reasoning="Fallback heuristic: first agent with sufficient examples",
                confidence=0.6,
            )

        # Second pass: any agent with examples (even if recently failed)
        # This allows retry after backoff
        for agent in obs.available_agents:
            if obs.agent_example_counts.get(agent, 0) >= 5:
                return OrchestratorDecision(
                    action=OrchestratorAction.OPTIMIZE_AGENT,
                    target=agent,
                    reasoning="Fallback heuristic: retry agent after backoff",
                    confidence=0.4,
                )

        # Third pass: any agent at all (bootstrap mode)
        if obs.available_agents:
            return OrchestratorDecision(
                action=OrchestratorAction.COLLECT_EXAMPLES,
                target=obs.available_agents[0],
                reasoning="Need more training examples before optimization",
                confidence=0.7,
            )

        return OrchestratorDecision(
            action=OrchestratorAction.WAIT,
            reasoning="No agents available",
            confidence=0.8,
        )

    async def _execute_decision(self, decision: OrchestratorDecision) -> dict:
        """Execute orchestrator decision."""
        result = {"success": False, "action": decision.action.value}

        try:
            if decision.action == OrchestratorAction.OPTIMIZE_AGENT:
                if decision.target is None:
                    result = {"success": False, "error": "No target agent specified"}
                else:
                    result = await self._execute_optimize(decision.target)

            elif decision.action == OrchestratorAction.SKIP_AGENT:
                result = {"success": True, "skipped": decision.target}

            elif decision.action == OrchestratorAction.WAIT:
                wait_seconds = decision.parameters.get("seconds", 60)
                await asyncio.sleep(wait_seconds)
                result = {"success": True, "waited": wait_seconds}

            elif decision.action == OrchestratorAction.RESTART_ENDPOINT:
                if decision.target is None:
                    result = {"success": False, "error": "No target endpoint specified"}
                else:
                    result = await self._execute_restart_endpoint(decision.target)

            elif decision.action == OrchestratorAction.DIAGNOSE:
                result = await self._execute_diagnose()

            elif decision.action == OrchestratorAction.SHUTDOWN:
                self._running = False
                result = {"success": True, "shutdown": True}

            elif decision.action == OrchestratorAction.COLLECT_EXAMPLES:
                if decision.target is None:
                    result = {"success": False, "error": "No target agent specified"}
                else:
                    result = await self._execute_collect_examples(decision.target)

            elif decision.action == OrchestratorAction.ADJUST_STRATEGY:
                # Strategy adjustment is handled by the orchestrator's reasoning
                result = {"success": True, "strategy_adjusted": True}

            elif decision.action == OrchestratorAction.REPORT_STATUS:
                result = {"success": True, "status": self.get_status()}

            else:
                result = {"success": True, "action": "no-op"}

        except Exception as e:
            result = {"success": False, "error": str(e)}

        return result

    async def _execute_optimize(self, agent_id: str) -> dict:
        """Execute agent optimization."""
        from .daemon import EvolutionDaemon, EvolutionConfig

        # Create a one-shot daemon for this cycle
        config = EvolutionConfig(
            agents=[agent_id],
            strategy="gepa",
            min_examples=5,
        )

        daemon = EvolutionDaemon(config)
        result = await daemon.force_evolution_cycle(agent_id)

        # Record to history
        self._cycle_history.append({
            "agent_id": agent_id,
            "success": result.success,
            "improvement": result.improvement_percent,
            "duration_ms": result.duration_ms,
            "timestamp": datetime.now().isoformat(),
        })

        return {
            "success": result.success,
            "improvement": result.improvement_percent,
            "agent_id": agent_id,
            "error": result.error,
        }

    async def _execute_restart_endpoint(self, endpoint: str) -> dict:
        """Restart a vLLM endpoint via engine.

        Engine Federation Architecture: endpoint restarts go through engine gRPC.
        """
        try:
            from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            if not use_engine_proxy():
                # Engine not available - fail-fast
                return {
                    "success": False,
                    "error": "Engine not available (#GR.00000001.ENGINEOFF)",
                    "remediation": "Start engine: devenv up gaius-engine",
                }

            orch = await get_orchestrator_proxy()
            success = await orch.restart_endpoint(endpoint)
            return {"success": success, "restarted": endpoint}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_diagnose(self) -> dict:
        """Run diagnostic checks."""
        issues = []

        # Check GPU memory
        try:
            from ...inference.health import get_health_monitor
            monitor = get_health_monitor()

            for gpu in monitor.get_all_gpu_health():
                if gpu.vram_percent > 95:
                    issues.append(f"GPU {gpu.gpu_id} memory critical")
                if gpu.temperature_c > 85:
                    issues.append(f"GPU {gpu.gpu_id} temperature high")
        except Exception as e:
            issues.append(f"GPU health check failed: {e}")

        # Check agent versions
        try:
            from ...models.versioning import get_version_manager
            manager = get_version_manager()

            for agent in ["leader", "risk", "critic", "opportunity", "domain"]:
                version = await manager.get_active_version(agent)
                if not version:
                    issues.append(f"Agent '{agent}' has no active version")
        except Exception as e:
            issues.append(f"Agent version check failed: {e}")

        return {
            "success": True,
            "issues": issues,
            "healthy": len(issues) == 0,
        }

    async def _execute_collect_examples(self, agent_id: str) -> dict:
        """Collect more training examples for an agent.

        This is used when an agent doesn't have enough examples for optimization.
        Uses the existing collector to gather examples from various sources
        (swarm runs, cognition thoughts, research outputs).
        """
        try:
            from .collector import get_training_collector

            collector = get_training_collector()

            # Collect examples from existing high-quality interactions
            examples = await collector.collect_examples(
                agent_id=agent_id,
                max_examples=10,
            )

            return {
                "success": len(examples) > 0,
                "agent_id": agent_id,
                "examples_collected": len(examples),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _update_state(
        self,
        decision: OrchestratorDecision,
        result: dict
    ) -> None:
        """Update internal state based on execution result."""
        if decision.action == OrchestratorAction.OPTIMIZE_AGENT:
            if result.get("success"):
                self._cycles_completed += 1
                self._total_improvement += result.get("improvement", 0)
                self._consecutive_failures = 0
                self._consecutive_successes += 1
            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0


# Singleton instance
_orchestrated_instance: OrchestratedEvolution | None = None


def get_orchestrated_evolution() -> OrchestratedEvolution:
    """Get singleton orchestrated evolution instance."""
    global _orchestrated_instance
    if _orchestrated_instance is None:
        _orchestrated_instance = OrchestratedEvolution()
    return _orchestrated_instance
