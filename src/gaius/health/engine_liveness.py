"""Out-of-band engine-liveness signals shared by the health surfaces.

The `gaius-engine-ready` watchdog (`scripts/engine-ready.sh`) is the out-of-band L0
detector + recovery for a dead or wedged engine — `:50051` down while devenv
process-compose still reports the process "ready" (the 2026-08-29 outage class). An
in-engine observer cannot detect that class itself: it runs inside the engine and
dies with it. When the watchdog's deterministic recycle budget is exhausted it
drops a breaker marker; this module is the single place that reads it, so:

  - the in-engine `HealthObserverService` reads it to escalate to ACP (L2 root-cause
    — the honest trigger is "deterministic recovery exhausted", not the RPN tier);
  - the client-side `/health` surface reads it to show the desync + point at
    `/health fix engine`.

Guru: #EN.00000017.SERVEDESYNC.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Written by scripts/engine-ready.sh on a breaker trip; cleared by it on sustained
# recovery. Overridable in lockstep with the watchdog's GAIUS_ENGINE_BREAKER.
ENGINE_BREAKER_MARKER = os.environ.get(
    "GAIUS_ENGINE_BREAKER", "/var/lib/gaius/engine-breaker-tripped"
)
# The watchdog clears the marker on sustained recovery; a marker older than this is
# treated as stale (defensive — the breaker should not be considered active forever
# if the watchdog somehow failed to clear it).
_FRESH_WINDOW_S = int(os.environ.get("GAIUS_ENGINE_BREAKER_FRESH_S", "7200"))

GURU_SERVEDESYNC = "#EN.00000017.SERVEDESYNC"
# The FMEA failure mode this signal maps to (kept in sync with fmea/loader.py +
# fmea/registry.py + db/migrations/*_add_engine_serving_failure_mode.sql).
ENGINE_SERVING_FMEA_ID = "INFRA_005"


def read_engine_breaker(marker: str | None = None) -> dict | None:
    """Return the tripped-breaker context iff the watchdog has an ACTIVE breaker.

    None in the healthy case (no marker) or when the marker is stale. The returned
    dict carries the watchdog's context (recycles_in_window, window_s, tripped_at)
    plus a computed ``marker_age_s`` and a guaranteed ``guru`` key.
    """
    path = Path(marker or ENGINE_BREAKER_MARKER)
    try:
        st = path.stat()
    except OSError:
        return None  # absent / unreadable → no active breaker
    age = time.time() - st.st_mtime
    if age > _FRESH_WINDOW_S:
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("guru", GURU_SERVEDESYNC)
    data["marker_age_s"] = round(age, 1)
    return data
