"""Type stubs for behave BDD framework.

These stubs define the behave step decorators so ty can properly type-check
BDD step definitions in features/*.py files.
"""

from typing import Callable, TypeVar, Any

F = TypeVar('F', bound=Callable[..., None])

# Step decorators - pattern is a string that behave matches at runtime
def given(pattern: str) -> Callable[[F], F]: ...
def when(pattern: str) -> Callable[[F], F]: ...
def then(pattern: str) -> Callable[[F], F]: ...

# Aliases
step = given  # Generic step decorator

# Context object passed to step functions
class Context:
    """Behave context object passed to each step function."""
    table: Any
    text: str | None
    feature: Any
    scenario: Any
    config: Any
    # User-defined attributes are dynamically added
    def __getattr__(self, name: str) -> Any: ...
    def __setattr__(self, name: str, value: Any) -> None: ...
