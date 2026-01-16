"""Type stubs for metaflow.metadata_provider.heartbeat module."""

from typing import Any, Callable

class HeartBeat:
    """Heartbeat for task monitoring."""

    def __init__(
        self,
        flow_id: str,
        run_id: str,
        step_name: str,
        task_id: str,
        **kwargs: Any,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...

def start_heartbeat(
    flow_id: str,
    run_id: str,
    step_name: str,
    task_id: str,
    **kwargs: Any,
) -> HeartBeat: ...
