"""Ephemeral Signals DCGM snapshot.

One HTTP GET of the Signals ``kind=telemetry`` surface (OTLP JSON on
:9410). Nothing is written to disk. Nothing is queued. PROF/DCP fields
are skipped — GeForce 4090s do not have them.

Discover the URL from Signals Status.surfaces. Do not invent a host.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

GURU_NOTELEMETRY = (
    "Signals telemetry surface is not reachable.\n"
    "  Guru: #EP.00000017.NOTELEMETRY\n"
    "  Signals Status.surfaces must advertise kind=telemetry.\n"
    "  Try: SIGNALS_ENGINE_TARGET (gRPC) or SIGNALS_TELEMETRY_URL"
)

# 4090s have no profiler / DCP counters. Skip if they ever appear.
_SKIP_SUBSTR = ("prof", "_dcp", "dcgm_fi_prof", "dcgm_fi_dev_dcp")

_WANTED = frozenset(
    {
        "gpu.power.draw",
        "gpu.utilization",
        "gpu.energy.consumption",
        "gpu.memory.used",
        "gpu.memory.free",
        "gpu.temperature",
    }
)


class SignalsTelemetryError(RuntimeError):
    """Fail-fast scrape / discovery error."""


def _skip_metric(name: str) -> bool:
    n = (name or "").lower()
    return any(s in n for s in _SKIP_SUBSTR)


def _attr_map(attrs: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in attrs or []:
        key = str(a.get("key") or "")
        val = a.get("value") or {}
        if "stringValue" in val:
            out[key] = str(val["stringValue"])
        elif "intValue" in val:
            out[key] = str(val["intValue"])
    return out


def _point_value(pt: dict[str, Any]) -> float | None:
    if "asDouble" in pt:
        return float(pt["asDouble"])
    if "asInt" in pt:
        return float(pt["asInt"])
    return None


def parse_otlp_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Fold OTLP resourceMetrics into per-GPU rows. No I/O."""
    gpus: dict[int, dict[str, Any]] = {}
    for rm in payload.get("resourceMetrics") or []:
        for sm in rm.get("scopeMetrics") or []:
            for metric in sm.get("metrics") or []:
                name = str(metric.get("name") or "")
                if not name or _skip_metric(name) or name not in _WANTED:
                    continue
                body = metric.get("gauge") or metric.get("sum") or {}
                for pt in body.get("dataPoints") or []:
                    attrs = _attr_map(pt.get("attributes") or [])
                    raw_idx = attrs.get("gpu.index")
                    if raw_idx is None or not raw_idx.isdigit():
                        continue
                    idx = int(raw_idx)
                    row = gpus.setdefault(
                        idx,
                        {
                            "index": idx,
                            "uuid": attrs.get("gpu.uuid", ""),
                            "model": attrs.get("gpu.modelname", ""),
                        },
                    )
                    val = _point_value(pt)
                    if val is None:
                        continue
                    if name == "gpu.power.draw":
                        row["power_w"] = val
                    elif name == "gpu.utilization":
                        row["util"] = val
                    elif name == "gpu.energy.consumption":
                        row["energy_mj"] = val
                    elif name == "gpu.memory.used":
                        row["memory_used_mib"] = val
                    elif name == "gpu.memory.free":
                        row["memory_free_mib"] = val
                    elif name == "gpu.temperature":
                        row["temp_c"] = val

    rows = [gpus[i] for i in sorted(gpus)]
    total_w = sum(float(r.get("power_w") or 0.0) for r in rows)
    parked_w = sum(
        float(r.get("power_w") or 0.0)
        for r in rows
        if float(r.get("memory_used_mib") or 0.0) < 64.0
    )
    return {
        "gpus": rows,
        "total_w": total_w,
        "parked_w": parked_w,
        "inferring_w": total_w - parked_w,
    }


async def resolve_telemetry_url() -> str:
    """Signals Status.surfaces kind=telemetry, or SIGNALS_TELEMETRY_URL."""
    env = (os.environ.get("SIGNALS_TELEMETRY_URL") or "").strip()
    if env:
        return env
    target = (os.environ.get("SIGNALS_ENGINE_TARGET") or "").strip()
    if not target:
        raise SignalsTelemetryError(GURU_NOTELEMETRY)
    from gaius.engine.s2s import status_peer

    status = await status_peer(target)
    if status is None:
        raise SignalsTelemetryError(GURU_NOTELEMETRY)
    for surf in status.surfaces:
        if (surf.kind or "") == "telemetry" and (surf.url or "").strip():
            return surf.url.strip()
    raise SignalsTelemetryError(GURU_NOTELEMETRY)


async def scrape_snapshot() -> dict[str, Any]:
    """One GET. Fail-fast on 503 / connect / bad JSON."""
    import httpx

    url = await resolve_telemetry_url()
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise SignalsTelemetryError(f"{GURU_NOTELEMETRY}\n  http: {e}") from e
    if resp.status_code == 503:
        raise SignalsTelemetryError(
            f"{GURU_NOTELEMETRY}\n  503 from {url} (DCGM exporter down)"
        )
    if resp.status_code != 200:
        raise SignalsTelemetryError(
            f"{GURU_NOTELEMETRY}\n  HTTP {resp.status_code} from {url}"
        )
    try:
        payload = resp.json()
    except ValueError as e:
        raise SignalsTelemetryError(
            f"{GURU_NOTELEMETRY}\n  OTLP JSON parse failed: {e}"
        ) from e
    snap = parse_otlp_snapshot(payload)
    snap["source_url"] = url
    snap["scraped_at"] = datetime.now(timezone.utc).isoformat()
    snap["salience_per_watt"] = None  # FeatureTape not hydrated yet
    return snap
