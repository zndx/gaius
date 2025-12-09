"""Remediation system for health check failures.

Provides infrastructure for diagnosing and fixing unhealthy services.
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

logger = logging.getLogger(__name__)


class SafetyLevel(str, Enum):
    """Safety classification for remediation actions."""

    SAFE = "safe"  # Can execute without confirmation (start stopped service)
    CAUTION = "caution"  # Execute by default but warn (restart running service)
    DESTRUCTIVE = "destructive"  # Requires --force flag (kill processes, clear data)


@dataclass
class RemediationAction:
    """A single remediation action to execute."""

    name: str
    description: str
    command: str | None = None  # Shell command to execute
    code: str | None = None  # Python code to execute
    safety: SafetyLevel = SafetyLevel.SAFE
    timeout: int = 30  # Seconds

    def __str__(self) -> str:
        if self.command:
            return f"{self.name}: `{self.command}`"
        return f"{self.name}: [python code]"


@dataclass
class RemediationPlan:
    """A plan for remediating a service."""

    service: str
    actions: list[RemediationAction] = field(default_factory=list)
    heuristic_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def max_safety(self) -> SafetyLevel:
        """Return the highest safety level in the plan."""
        if not self.actions:
            return SafetyLevel.SAFE
        levels = [a.safety for a in self.actions]
        if SafetyLevel.DESTRUCTIVE in levels:
            return SafetyLevel.DESTRUCTIVE
        if SafetyLevel.CAUTION in levels:
            return SafetyLevel.CAUTION
        return SafetyLevel.SAFE

    def requires_force(self) -> bool:
        """Check if plan requires --force flag."""
        return self.max_safety == SafetyLevel.DESTRUCTIVE


@dataclass
class ActionResult:
    """Result of executing a single action."""

    action: RemediationAction
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class RemediationResult:
    """Result of executing a remediation plan."""

    plan: RemediationPlan
    success: bool
    action_results: list[ActionResult] = field(default_factory=list)
    before_status: dict | None = None
    after_status: dict | None = None
    dry_run: bool = False
    duration_ms: int = 0

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if self.dry_run:
            return f"Dry run: {len(self.plan.actions)} actions would be executed"

        passed = sum(1 for r in self.action_results if r.success)
        total = len(self.action_results)

        if self.success:
            return f"Success: {passed}/{total} actions completed"
        return f"Failed: {passed}/{total} actions completed"


class RemediationExecutor:
    """Executes remediation plans with safety controls."""

    def __init__(self):
        self._execution_history: list[RemediationResult] = []

    async def execute(
        self,
        plan: RemediationPlan,
        dry_run: bool = False,
        force: bool = False,
    ) -> RemediationResult:
        """Execute a remediation plan.

        Args:
            plan: The remediation plan to execute
            dry_run: If True, show actions without executing
            force: If True, allow destructive actions

        Returns:
            RemediationResult with execution details
        """
        start = datetime.now()

        # Safety check
        if plan.requires_force() and not force:
            return RemediationResult(
                plan=plan,
                success=False,
                dry_run=dry_run,
                action_results=[
                    ActionResult(
                        action=plan.actions[0] if plan.actions else RemediationAction(
                            name="blocked",
                            description="Plan requires --force flag",
                        ),
                        success=False,
                        error="Destructive actions require --force flag",
                    )
                ],
            )

        if dry_run:
            return RemediationResult(
                plan=plan,
                success=True,
                dry_run=True,
                action_results=[
                    ActionResult(
                        action=action,
                        success=True,
                        output=f"Would execute: {action}",
                    )
                    for action in plan.actions
                ],
            )

        # Execute actions
        action_results = []
        all_success = True

        for action in plan.actions:
            result = await self._execute_action(action)
            action_results.append(result)

            if not result.success:
                all_success = False
                logger.warning(f"Action failed: {action.name} - {result.error}")
                # Continue with remaining actions (best effort)

        duration = int((datetime.now() - start).total_seconds() * 1000)

        result = RemediationResult(
            plan=plan,
            success=all_success,
            action_results=action_results,
            dry_run=False,
            duration_ms=duration,
        )

        self._execution_history.append(result)
        return result

    async def _execute_action(self, action: RemediationAction) -> ActionResult:
        """Execute a single action."""
        start = datetime.now()

        try:
            if action.command:
                return await self._run_shell(action, action.command)
            elif action.code:
                return await self._run_python(action, action.code)
            else:
                return ActionResult(
                    action=action,
                    success=False,
                    error="No command or code specified",
                )
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ActionResult(
                action=action,
                success=False,
                error=str(e),
                duration_ms=duration,
            )

    async def _run_shell(
        self, action: RemediationAction, command: str
    ) -> ActionResult:
        """Execute a shell command."""
        start = datetime.now()

        try:
            # Run in subprocess with timeout
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=action.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ActionResult(
                    action=action,
                    success=False,
                    error=f"Command timed out after {action.timeout}s",
                    duration_ms=action.timeout * 1000,
                )

            duration = int((datetime.now() - start).total_seconds() * 1000)

            return ActionResult(
                action=action,
                success=proc.returncode == 0,
                output=stdout.decode() if stdout else "",
                error=stderr.decode() if stderr else "",
                duration_ms=duration,
            )

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ActionResult(
                action=action,
                success=False,
                error=str(e),
                duration_ms=duration,
            )

    async def _run_python(
        self, action: RemediationAction, code: str
    ) -> ActionResult:
        """Execute Python code in a semi-restricted context.

        For remediation code, we allow imports from gaius modules
        since the code comes from trusted heuristics in the KB.
        """
        start = datetime.now()

        try:
            # Create globals that allow necessary imports
            # Note: Remediation code is trusted (from KB heuristics)
            import builtins

            restricted_globals = {
                "__builtins__": builtins,  # Full builtins for import support
            }

            # Pre-import commonly needed modules
            allowed_imports = {
                "socket": __import__("socket"),
                "subprocess": __import__("subprocess"),
                "os": __import__("os"),
                "asyncio": __import__("asyncio"),
            }
            restricted_globals.update(allowed_imports)

            # Execute with timeout
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: exec(code, restricted_globals),
                ),
                timeout=action.timeout,
            )

            duration = int((datetime.now() - start).total_seconds() * 1000)

            return ActionResult(
                action=action,
                success=True,
                output=str(result) if result else "Code executed successfully",
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            return ActionResult(
                action=action,
                success=False,
                error=f"Code execution timed out after {action.timeout}s",
                duration_ms=action.timeout * 1000,
            )
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ActionResult(
                action=action,
                success=False,
                error=str(e),
                duration_ms=duration,
            )

    @property
    def history(self) -> list[RemediationResult]:
        """Get execution history."""
        return self._execution_history.copy()


class RemediationPlanner:
    """Creates remediation plans from health check results and heuristics."""

    def __init__(self, heuristic_loader=None):
        """Initialize planner.

        Args:
            heuristic_loader: Optional HeuristicLoader instance
        """
        self.heuristic_loader = heuristic_loader
        self._service_strategies: dict[str, "ServiceFixStrategy"] = {}

    def register_strategy(self, service: str, strategy: "ServiceFixStrategy"):
        """Register a fix strategy for a service."""
        self._service_strategies[service] = strategy

    def create_plan(
        self,
        service: str,
        check_result: dict | None = None,
        heuristic_id: str | None = None,
    ) -> RemediationPlan:
        """Create a remediation plan for a service.

        Args:
            service: Service name (engine, postgres, qdrant, etc.)
            check_result: Optional health check result dict
            heuristic_id: Optional heuristic ID to use

        Returns:
            RemediationPlan with actions to execute
        """
        plan = RemediationPlan(service=service, heuristic_id=heuristic_id)

        # Try service-specific strategy first
        if service in self._service_strategies:
            strategy = self._service_strategies[service]
            actions = strategy.create_fix_actions(check_result)
            plan.actions.extend(actions)
            return plan

        # Fall back to heuristic-based plan
        if heuristic_id and self.heuristic_loader:
            heuristic = self.heuristic_loader.get(heuristic_id)
            if heuristic and heuristic.fix_code:
                # Parse solution section for commands/code
                actions = self._parse_heuristic_solution(heuristic)
                plan.actions.extend(actions)
                return plan

        # No strategy found
        logger.warning(f"No fix strategy found for service: {service}")
        return plan

    def _parse_heuristic_solution(self, heuristic) -> list[RemediationAction]:
        """Parse a heuristic's solution section into actions."""
        actions = []

        # Extract shell commands (```bash blocks)
        import re

        bash_pattern = r"```bash\n(.*?)```"
        for match in re.finditer(bash_pattern, heuristic.solution, re.DOTALL):
            cmd = match.group(1).strip()
            # Skip comments-only blocks
            if cmd and not cmd.startswith("#"):
                actions.append(
                    RemediationAction(
                        name=f"Shell: {cmd.split()[0] if cmd.split() else 'command'}",
                        description=f"From heuristic {heuristic.id}",
                        command=cmd,
                        safety=SafetyLevel.SAFE
                        if heuristic.solution_level == "A"
                        else SafetyLevel.CAUTION,
                    )
                )

        # Extract Python code (```python blocks)
        python_pattern = r"```python\n(.*?)```"
        for match in re.finditer(python_pattern, heuristic.solution, re.DOTALL):
            code = match.group(1).strip()
            if code:
                actions.append(
                    RemediationAction(
                        name="Python code",
                        description=f"From heuristic {heuristic.id}",
                        code=code,
                        safety=SafetyLevel.SAFE
                        if heuristic.solution_level == "A"
                        else SafetyLevel.CAUTION,
                    )
                )

        return actions


class ServiceFixStrategy:
    """Base class for service-specific fix strategies."""

    def __init__(self, service_name: str):
        self.service_name = service_name

    def create_fix_actions(
        self, check_result: dict | None = None
    ) -> list[RemediationAction]:
        """Create fix actions for this service.

        Override in subclasses.
        """
        raise NotImplementedError
