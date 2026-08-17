"""Flow configuration helpers.

Loads Metaflow configuration from config/metaflow/ and applies it
to the environment. Default mode is resolved from Signals Engine/Status:
platform Metaflow when the lattice supplies scheduler/metaflow, else local.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path

from gaius.flows.platform_metaflow import (
    GURU_NOPROFILE,
    PlatformMetaflowError,
    resolve_metaflow_mode,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _signals_platform_path() -> Path:
    return (
        Path(
            os.environ.get(
                "SIGNALS_ROOT",
                str(Path.home() / "local/src/wxs/signals"),
            )
        )
        / "config"
        / "metaflow"
        / "platform.json"
    )


def get_config_path(mode: str = "local") -> Path:
    """Get path to Metaflow config file.

    ``platform`` prefers ``$SIGNALS_ROOT/config/metaflow/platform.json``
    when present; callers that need the merge should use ``load_metaflow_config``.
    """
    if mode == "platform":
        signals_profile = _signals_platform_path()
        if signals_profile.is_file():
            return signals_profile
    return _REPO_ROOT / "config" / "metaflow" / f"{mode}.json"


def _read_profile(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not str(k).startswith("_")}


def load_metaflow_config(mode: str = "local") -> dict:
    """Load Metaflow configuration from JSON.

    ``platform`` merges this tree's ``platform.json`` (lab RustFS keys) under
    the Signals pin when that file exists — Signals wins on overlapping keys.

    Args:
        mode: Configuration mode (``local``, ``k8s``, or ``platform``)

    Returns:
        Dictionary of Metaflow configuration options (``_`` keys stripped)
    """
    if mode != "platform":
        return _read_profile(get_config_path(mode))

    cfg = _read_profile(_REPO_ROOT / "config" / "metaflow" / "platform.json")
    cfg.update(_read_profile(_signals_platform_path()))
    return cfg


def apply_metaflow_config(mode: str | None = None) -> str:
    """Apply Metaflow configuration to this process environment.

    ``mode=None`` resolves via Signals Engine/Status. Platform mode
    overwrites Gaius-local MinIO/Tilt keys so they cannot win.

    Returns:
        The resolved mode string.
    """
    env = metaflow_child_env(os.environ, mode=mode)
    resolved = env.get("GAIUS_METAFLOW_MODE", mode or "local")
    os.environ.update(env)
    return resolved


def metaflow_child_env(
    base: Mapping[str, str] | None = None,
    *,
    mode: str | None = None,
) -> dict[str, str]:
    """Return a subprocess env with the resolved Metaflow profile applied."""
    env = dict(base or os.environ)
    if mode is None:
        decision = resolve_metaflow_mode(environ=env)
        resolved = decision.mode
        logger.info("Metaflow profile=%s (%s)", resolved, decision.reason)
    else:
        resolved = mode

    config = load_metaflow_config(resolved)
    if resolved == "platform" and not config:
        raise PlatformMetaflowError(
            GURU_NOPROFILE,
            "platform Metaflow selected but no platform.json found "
            "(set SIGNALS_ROOT or add config/metaflow/platform.json)",
        )

    force = resolved == "platform"
    for key, value in config.items():
        if force or key not in env:
            env[key] = str(value)
    env["GAIUS_METAFLOW_MODE"] = resolved
    if resolved == "platform":
        from gaius.flows.prospects.product_env import apply_product_env

        apply_product_env(env)
    return env


def get_metaflow_profile() -> str:
    """Get Metaflow profile name for the current process."""
    override = (os.environ.get("GAIUS_METAFLOW_MODE") or "").strip().lower()
    if override in ("platform", "local", "k8s"):
        return f"gaius-{override}" if override != "platform" else "platform"
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        # RKE2 Metaflow tasks use the Signals platform profile, not Tilt k8s.json
        return "platform"
    try:
        return resolve_metaflow_mode().mode
    except PlatformMetaflowError:
        raise
