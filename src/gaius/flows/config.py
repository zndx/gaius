"""Flow configuration helpers.

Loads Metaflow configuration from config/metaflow/ and applies it
to the environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def get_config_path(mode: str = "local") -> Path:
    """Get path to Metaflow config file.

    Args:
        mode: Configuration mode ("local" or "k8s")

    Returns:
        Path to the config JSON file
    """
    # gaius/src/gaius/flows/config.py -> gaius/config/metaflow/
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / "config" / "metaflow" / f"{mode}.json"


def load_metaflow_config(mode: str = "local") -> dict:
    """Load Metaflow configuration from JSON.

    Args:
        mode: Configuration mode ("local" or "k8s")

    Returns:
        Dictionary of Metaflow configuration options
    """
    config_path = get_config_path(mode)
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        return json.load(f)


def apply_metaflow_config(mode: str = "local") -> None:
    """Apply Metaflow configuration to environment.

    This sets environment variables for Metaflow configuration.
    Call this before running flows.

    Args:
        mode: Configuration mode ("local" or "k8s")
    """
    config = load_metaflow_config(mode)
    for key, value in config.items():
        if key not in os.environ:  # Don't override existing env vars
            os.environ[key] = str(value)


def get_metaflow_profile() -> str:
    """Get Metaflow profile name.

    Returns "gaius-local" or "gaius-k8s" based on environment.
    """
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "gaius-k8s"
    return "gaius-local"
