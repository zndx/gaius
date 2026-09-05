"""Storage backend factory for dynamic backend selection.

Provides a registry pattern for pluggable storage backends, allowing
new backends to be registered at runtime (e.g., for Agent Studio integration).

Configuration via environment variables:
    GAIUS_KB_BACKEND=filesystem|rustfs|agent_studio
    GAIUS_KB_ROOT=build/dev  (or bucket name for rustfs)
    GAIUS_KB_ENDPOINT=localhost:9010  (for rustfs)
    GAIUS_KB_ACCESS_KEY=...
    GAIUS_KB_SECRET_KEY=...
    GAIUS_KB_SECURE=true|false
"""

import os
from typing import Callable, TypeAlias

from .protocol import StorageBackend, StorageConfig

# Type for backend factory functions
BackendFactory: TypeAlias = Callable[[StorageConfig], StorageBackend]

# Registry of backend factories
_backends: dict[str, BackendFactory] = {}

# Singleton instance
_storage_instance: StorageBackend | None = None


def register_backend(name: str, factory: BackendFactory) -> None:
    """Register a storage backend factory.

    This allows external packages (like agent-studio-sdk) to register
    their own backends without modifying this module.

    Args:
        name: Backend identifier (e.g., "agent_studio")
        factory: Function that takes StorageConfig and returns StorageBackend

    Example:
        # In agent_studio_sdk package
        from gaius.storage import register_backend
        from my_package import AgentStudioStorage

        register_backend("agent_studio", lambda config: AgentStudioStorage(config))
    """
    _backends[name] = factory


def _load_default_backends() -> None:
    """Load built-in backends on first use."""
    if "filesystem" not in _backends:
        from .filesystem import FilesystemStorage

        _backends["filesystem"] = lambda config: FilesystemStorage(config)

    if "rustfs" not in _backends:
        from .rustfs import RustFSStorage

        _backends["rustfs"] = lambda config: RustFSStorage(config)


def get_config_from_env() -> StorageConfig:
    """Build StorageConfig from environment variables.

    Environment variables:
        GAIUS_KB_BACKEND: Backend type (filesystem, rustfs, agent_studio)
        GAIUS_KB_ROOT: Root path or bucket name
        GAIUS_KB_ENDPOINT: Endpoint URL for remote backends
        GAIUS_KB_ACCESS_KEY: Access key for authenticated backends
        GAIUS_KB_SECRET_KEY: Secret key for authenticated backends
        GAIUS_KB_SECURE: Use HTTPS (true/false, default true)

    Returns:
        StorageConfig populated from environment
    """
    return StorageConfig(
        backend_type=os.getenv("GAIUS_KB_BACKEND", "filesystem"),
        root=os.getenv("GAIUS_KB_ROOT", "build/dev"),
        endpoint=os.getenv("GAIUS_KB_ENDPOINT", "localhost:9010"),
        access_key=os.getenv("GAIUS_KB_ACCESS_KEY", ""),
        secret_key=os.getenv("GAIUS_KB_SECRET_KEY", ""),
        region=os.getenv("GAIUS_KB_REGION", ""),
        secure=os.getenv("GAIUS_KB_SECURE", "true").lower() == "true",
    )


def get_storage_backend(
    config: StorageConfig | None = None,
    reset: bool = False,
) -> StorageBackend:
    """Get or create the storage backend singleton.

    Args:
        config: Optional explicit configuration. If None, reads from env vars.
        reset: If True, recreate the backend even if one exists.

    Returns:
        Configured StorageBackend instance

    Raises:
        ValueError: If requested backend type is not registered
    """
    global _storage_instance

    if _storage_instance is not None and not reset:
        return _storage_instance

    # Load built-in backends
    _load_default_backends()

    # Get config from env if not provided
    if config is None:
        config = get_config_from_env()

    # Look up factory
    backend_type = config.backend_type
    if backend_type not in _backends:
        available = ", ".join(_backends.keys())
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Available backends: {available}. "
            f"Use register_backend() to add custom backends."
        )

    # Create backend
    factory = _backends[backend_type]
    _storage_instance = factory(config)

    return _storage_instance


def reset_storage() -> None:
    """Reset the storage singleton (for testing)."""
    global _storage_instance
    _storage_instance = None
