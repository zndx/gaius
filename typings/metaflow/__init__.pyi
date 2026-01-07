"""Type stubs for metaflow workflow framework.

Metaflow uses dynamic attributes heavily, so this provides minimal stubs
to make ty happy while preserving the dynamic nature of the framework.
"""

from typing import Any, Callable, TypeVar

F = TypeVar('F', bound=Callable[..., Any])

# Flow decorators
def step(f: F) -> F: ...
def card(f: F) -> F: ...
def kubernetes(f: F) -> F: ...
def retry(times: int = 3, **kwargs: Any) -> Callable[[F], F]: ...
def catch(**kwargs: Any) -> Callable[[F], F]: ...
def batch(**kwargs: Any) -> Callable[[F], F]: ...
def resources(**kwargs: Any) -> Callable[[F], F]: ...
def environment(**kwargs: Any) -> Callable[[F], F]: ...
def timeout(seconds: int) -> Callable[[F], F]: ...
def schedule(cron: str) -> Callable[[F], F]: ...
def project(**kwargs: Any) -> Callable[[F], F]: ...

# Flow base class
class FlowSpec:
    next: Callable[..., None]
    def __init__(self) -> None: ...

# Parameter decorators
class Parameter:
    def __init__(
        self,
        name: str = "",
        default: Any = None,
        help: str = "",
        required: bool = False,
        **kwargs: Any,
    ) -> None: ...
    def __get__(self, obj: Any, objtype: type | None = None) -> Any: ...

# Current context - has dynamic attributes from decorators
class Current:
    run_id: str
    flow_name: str
    step_name: str
    task_id: str
    pathspec: str
    origin_run_id: str | None
    namespace: str | None
    username: str

    # Card support (added by @card decorator)
    card: Any

    # Allow any attribute access (metaflow is highly dynamic)
    def __getattr__(self, name: str) -> Any: ...

current: Current
