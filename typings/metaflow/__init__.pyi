"""Type stubs for metaflow workflow framework.

Metaflow uses dynamic attributes heavily, so this provides minimal stubs
to make ty happy while preserving the dynamic nature of the framework.
"""

from typing import Any, AsyncIterator, Callable, TypeVar

F = TypeVar('F', bound=Callable[..., Any])

# Flow decorators
def step(f: F) -> F: ...
# @card can be used as @card or @card(type="blank", ...) - overloaded signatures
from typing import overload
@overload
def card(f: F) -> F: ...
@overload
def card(*, type: str = ..., **kwargs: Any) -> Callable[[F], F]: ...
def card(f: F | None = ..., *, type: str = ..., **kwargs: Any) -> F | Callable[[F], F]: ...
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

# Runner API for programmatic flow execution
class Run:
    """A Metaflow run instance."""
    id: str
    successful: bool
    finished: bool
    def __getattr__(self, name: str) -> Any: ...

class ExecutingRun:
    """A currently executing Metaflow run."""
    run: Run
    status: str  # "running", "successful", "failed"

    async def wait(self) -> None: ...
    def stream_log(self, stream: str) -> AsyncIterator[tuple[Any, str]]: ...
    def __getattr__(self, name: str) -> Any: ...

class Runner:
    """Metaflow Runner for programmatic flow execution."""
    def __init__(
        self,
        flow_file: str,
        show_output: bool = True,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> None: ...

    def __enter__(self) -> "Runner": ...
    def __exit__(self, *args: Any) -> None: ...

    async def async_run(self, **kwargs: Any) -> ExecutingRun: ...
    def run(self, **kwargs: Any) -> Run: ...
