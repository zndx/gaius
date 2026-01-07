"""Type stubs for metaflow.metaflow_config module."""

from typing import Any

# Configuration variables
DATASTORE_SYSROOT_S3: str
METAFLOW_DEFAULT_METADATA: str
METAFLOW_SERVICE_URL: str | None
METAFLOW_SERVICE_INTERNAL_URL: str | None

def get_config() -> dict[str, Any]: ...
