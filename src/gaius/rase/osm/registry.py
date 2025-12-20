"""Step Registry for OSM.

Provides a registry for step definitions with decorator-based registration,
similar to Behave or pytest-bdd but integrated with the RASE metamodel.

Example usage:
    from gaius.rase.osm import given, when, then

    @given("NiFi is running at {base_url}")
    async def nifi_running(context, base_url: str):
        context.nifi = await NiFiClient.connect(base_url)

    @when("I create a processor group named {name}")
    async def create_group(context, name: str):
        await context.nifi.create_process_group(name)

    @then("the group {name} should exist")
    async def verify_group(context, name: str):
        group = await context.nifi.get_group(name)
        assert group is not None

The registry maintains a mapping from patterns to StepDefs, enabling:
1. Step matching during scenario execution
2. Contract extraction for VM requirement generation
3. Documentation generation
"""

from __future__ import annotations

import re
import functools
from typing import Any, Callable, TypeVar, ParamSpec

from gaius.rase.traceability import TraceableId, IdScheme
from .scenario import StepType, StepDef, StepUsage, StepAction


P = ParamSpec('P')
T = TypeVar('T')


class StepRegistry:
    """Registry of step definitions.

    Maintains a mapping from step patterns to StepDef instances,
    enabling step matching and execution.

    Thread-safe through immutable operations and atomic dictionary updates.
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._steps: dict[str, StepDef] = {}
        self._pattern_cache: dict[str, re.Pattern] = {}

    def register(
        self,
        step_type: StepType,
        pattern: str,
        action: StepAction | None = None,
        description: str = "",
    ) -> StepDef:
        """Register a step definition.

        Args:
            step_type: Given/When/Then
            pattern: Text pattern with {param} placeholders
            action: Async function to execute for this step
            description: Documentation for the step

        Returns:
            The registered StepDef
        """
        # Extract parameter names from pattern
        param_names = re.findall(r'\{(\w+)\}', pattern)
        parameters = {name: str for name in param_names}

        step_def = StepDef(
            id=TraceableId.from_bdd_step_hash("registry", pattern),
            step_type=step_type,
            pattern=pattern,
            description=description,
            parameters=parameters,
        )

        if action:
            step_def = step_def.with_action(action)

        # Store by pattern for matching
        key = f"{step_type.value}:{pattern}"
        self._steps[key] = step_def

        # Pre-compile regex
        self._pattern_cache[key] = re.compile(step_def.pattern_regex, re.IGNORECASE)

        return step_def

    def match(self, step: StepUsage) -> tuple[StepDef, dict[str, str]] | None:
        """Find a matching StepDef for a step usage.

        Tries to match against all registered patterns of the same type.

        Args:
            step: The step usage to match

        Returns:
            Tuple of (StepDef, captured parameters) or None
        """
        canonical_type = step.step_type.canonical()

        # Try exact type first
        for key, step_def in self._steps.items():
            def_type, _ = key.split(":", 1)
            if def_type != canonical_type.value:
                continue

            pattern = self._pattern_cache[key]
            match = pattern.match(step.text)
            if match:
                return (step_def, match.groupdict())

        return None

    def get(self, step_type: StepType, pattern: str) -> StepDef | None:
        """Get a step definition by type and pattern."""
        key = f"{step_type.value}:{pattern}"
        return self._steps.get(key)

    def all_steps(self) -> list[StepDef]:
        """Get all registered step definitions."""
        return list(self._steps.values())

    def steps_by_type(self, step_type: StepType) -> list[StepDef]:
        """Get step definitions of a specific type."""
        return [
            s for s in self._steps.values()
            if s.step_type == step_type
        ]

    def clear(self) -> None:
        """Clear all registered steps."""
        self._steps.clear()
        self._pattern_cache.clear()


# Global default registry
_default_registry = StepRegistry("global")


def get_default_registry() -> StepRegistry:
    """Get the global default step registry."""
    return _default_registry


def step_def(
    step_type: StepType,
    pattern: str,
    registry: StepRegistry | None = None,
    description: str = "",
) -> Callable[[StepAction], StepAction]:
    """Decorator for registering step definitions.

    Args:
        step_type: Given/When/Then
        pattern: Text pattern with {param} placeholders
        registry: Registry to use (default: global registry)
        description: Documentation for the step

    Example:
        @step_def(StepType.GIVEN, "NiFi is running")
        async def nifi_running(context):
            pass
    """
    reg = registry or _default_registry

    def decorator(func: StepAction) -> StepAction:
        reg.register(
            step_type=step_type,
            pattern=pattern,
            action=func,
            description=description or func.__doc__ or "",
        )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def given(
    pattern: str,
    registry: StepRegistry | None = None,
    description: str = "",
) -> Callable[[StepAction], StepAction]:
    """Decorator for Given steps.

    Example:
        @given("NiFi is running at {base_url}")
        async def nifi_running(context, base_url: str):
            context.nifi = await NiFiClient.connect(base_url)
    """
    return step_def(StepType.GIVEN, pattern, registry, description)


def when(
    pattern: str,
    registry: StepRegistry | None = None,
    description: str = "",
) -> Callable[[StepAction], StepAction]:
    """Decorator for When steps.

    Example:
        @when("I create a processor group named {name}")
        async def create_group(context, name: str):
            await context.nifi.create_process_group(name)
    """
    return step_def(StepType.WHEN, pattern, registry, description)


def then(
    pattern: str,
    registry: StepRegistry | None = None,
    description: str = "",
) -> Callable[[StepAction], StepAction]:
    """Decorator for Then steps.

    Example:
        @then("the group {name} should exist")
        async def verify_group(context, name: str):
            group = await context.nifi.get_group(name)
            assert group is not None
    """
    return step_def(StepType.THEN, pattern, registry, description)


__all__ = [
    "StepRegistry",
    "get_default_registry",
    "step_def",
    "given",
    "when",
    "then",
]
