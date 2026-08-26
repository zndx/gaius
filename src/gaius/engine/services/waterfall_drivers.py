"""Named 10 Hz waterfall drivers. Each sample is a real measure in [-1, 1].

Missing sources return present=False (flatline) so CLT/SAE/heavy absence
is visible. New drivers: ``register(driver)``.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from gaius.engine.services.waterfall_color import pack_gpu

logger = logging.getLogger(__name__)

_PROM_LABELED = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([-+0-9.eE]+)"
)
_PROM_PLAIN = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([-+0-9.eE]+)\s*$")
# Power-load normalization band for the gpu-N bivariate color/onset. Set to the
# real 4090 operating envelope, not the 450 W TDP: idle ~14-25 W, and vLLM decode
# lives at ~95-135 W. The old 22..350 mapped that whole decode swing into a
# ~0.10-wide slice, so the power axis of the DkCyan2 palette barely moved and
# power's per-second derivative stayed under the onset threshold — power looked
# dead. 10..200 centers decode near mid-palette (~0.45-0.65) where the bivariate
# color has the most contrast and a 95->135 W move clears the red/blue threshold,
# while leaving headroom for prefill/training bursts (which saturate to max, as a
# burst should). Tune these to the hardware's real band, not its TDP.
_IDLE_W = 10.0
_BUSY_W = 200.0
_N_GPU = 6  # tinybox green: six 4090s; 0-3 thinking, 4 CLT, 5 spare
_RICCI_N = 12
_RICCI_K = 5
_RICCI_GAIN = 8.0
_CLT_HEARTBEAT = 0.08
# AC-couple the strip: DC occupancy is a dim residual; transients (d/dt
# of real measures) are the visible onset. Absent stays exactly 0.
_DC_GAIN = 0.12
_HP_GAIN = 5.0
_LP_ALPHA = 0.06  # ~1.6 s at 10 Hz — EEG-style coupling, measured decay

# Kumo salience overlay — not raw GPU util (watts/util already have series).
ONSET_NAMES = frozenset({"ricci-d", "clt", "sae", "gen-tps", "prefill"})

KB_COLLECTIONS = (
    os.getenv("QDRANT_COLLECTION", "gaius_kb_colnomic"),
    "gaius_kb_colnomic",
    "gaius_kb_colbert_zero",
    "gaius_kb",
)
BUF_COLLECTIONS = (
    os.getenv("GAIUS_LATENT_COLLECTION", "gaius_latent_thoughts"),
    "gaius_clt_latent_thoughts",
)


@dataclass(frozen=True)
class Sample:
    name: str
    value: float
    present: bool = True


class Driver(Protocol):
    name: str
    cadence_s: float

    def channel_names(self) -> tuple[str, ...]: ...

    def sample(self, ctx: dict[str, Any]) -> list[Sample]: ...


def _clip(x: float) -> float:
    if x > 1.0:
        return 1.0
    if x < -1.0:
        return -1.0
    return x


def parse_prom_text_raw(text: str) -> list[tuple[str, dict[str, str], str]]:
    """Prometheus text as (metric, labels, value TEXT). The warehouse ingest
    types each series itself (INT stays INT, float becomes DECIMAL); handing it
    a float here would widen integers before they are ever seen."""
    out: list[tuple[str, dict[str, str], str]] = []
    for metric, labels, val in _parse_prom_lines(text):
        out.append((metric, labels, val))
    return out


def _parse_prom_lines(text: str) -> list[tuple[str, dict[str, str], str]]:
    out: list[tuple[str, dict[str, str], str]] = []
    for raw in (text or "").splitlines():
        if not raw or raw.startswith("#"):
            continue
        m = _PROM_LABELED.match(raw)
        if m:
            labels: dict[str, str] = {}
            for part in m.group(2).split(","):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
            out.append((m.group(1), labels, m.group(3)))
            continue
        p = _PROM_PLAIN.match(raw)
        if not p:
            continue
        out.append((p.group(1), {}, p.group(2)))
    return out


def parse_prom_text(text: str) -> list[tuple[str, dict[str, str], float]]:
    """Drivers render floats; the warehouse ingest uses parse_prom_text_raw."""
    out: list[tuple[str, dict[str, str], float]] = []
    for metric, labels, val in _parse_prom_lines(text):
        try:
            out.append((metric, labels, float(val)))
        except ValueError:
            continue
    return out


def _gpu_index(labels: dict[str, str]) -> int | None:
    for key in ("gpu", "GPU", "gpu_id", "GPU_I_ID"):
        raw = labels.get(key)
        if raw is not None and raw.isdigit():
            return int(raw)
    return None


def _http_get(url: str, timeout: float = 0.15) -> str | None:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return None
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def _power_signed(watts: float) -> float:
    """Idle ~0, load → +1. Matches tinybox display lighting up."""
    return _clip((float(watts) - _IDLE_W) / (_BUSY_W - _IDLE_W))


def _metric_base(name: str) -> str:
    return name.replace("vllm_", "vllm:").split("{", 1)[0]


class HardwareDriver:
    """DCGM exporter :9400 (federation DaemonSet) — power / util."""

    name = "hardware"
    cadence_s = 0.1
    url = "http://127.0.0.1:9400/metrics"

    def channel_names(self) -> tuple[str, ...]:
        # gpu-N is bivariate — util drives the color's y axis, power the x —
        # so a standalone util-N row is redundant (dropped). The freed real
        # estate now carries GPU-workload signals from the same DCGM source:
        #   vram-N : per-GPU framebuffer occupancy — OOM headroom for training,
        #            fine-tuning, weights merging (rising toward the ceiling
        #            reads as a red onset).
        #   membw  : worst-GPU memory-copy utilization — the compute-vs-memory-
        #            bandwidth tell when gpu-util is pegged.
        return (
            tuple(f"gpu-{i}" for i in range(_N_GPU))
            + tuple(f"vram-{i}" for i in range(_N_GPU))
            + ("membw",)
        )

    def sample(self, ctx: dict[str, Any]) -> list[Sample]:
        text = _http_get(self.url, timeout=1.0)
        if not text:
            return [Sample(n, 0.0, present=False) for n in self.channel_names()]
        power: list[float | None] = [None] * _N_GPU
        util: list[float | None] = [None] * _N_GPU
        fb_used: list[float | None] = [None] * _N_GPU
        fb_free: list[float | None] = [None] * _N_GPU
        mem_copy: list[float | None] = [None] * _N_GPU
        for metric, labels, val in parse_prom_text(text):
            i = _gpu_index(labels)
            if i is None or i >= _N_GPU:
                continue
            if metric == "DCGM_FI_DEV_POWER_USAGE":
                power[i] = val
            elif metric == "DCGM_FI_DEV_GPU_UTIL":
                util[i] = val
            elif metric == "DCGM_FI_DEV_FB_USED":
                fb_used[i] = val
            elif metric == "DCGM_FI_DEV_FB_FREE":
                fb_free[i] = val
            elif metric == "DCGM_FI_DEV_MEM_COPY_UTIL":
                mem_copy[i] = val
        out: list[Sample] = []
        for i in range(_N_GPU):
            if power[i] is None:
                out.append(Sample(f"gpu-{i}", 0.0, present=False))
            else:
                u = 0.0 if util[i] is None else _clip(float(util[i]) / 100.0)
                if u < 0.0:
                    u = 0.0
                out.append(
                    Sample(f"gpu-{i}", pack_gpu(_power_signed(power[i]), u), present=True)
                )
        # vram-N: framebuffer occupancy fraction (used / (used + free)).
        for i in range(_N_GPU):
            if fb_used[i] is None or fb_free[i] is None:
                out.append(Sample(f"vram-{i}", 0.0, present=False))
            else:
                total = float(fb_used[i]) + float(fb_free[i])
                frac = float(fb_used[i]) / total if total > 0 else 0.0
                out.append(Sample(f"vram-{i}", _clip(frac), present=True))
        # membw: worst-GPU memory-copy utilization (fraction).
        mvals = [float(m) for m in mem_copy if m is not None]
        out.append(
            Sample("membw", _clip(max(mvals) / 100.0), present=True)
            if mvals
            else Sample("membw", 0.0, present=False)
        )
        _record_hardware(power, util)
        return out


class VllmDriver:
    """Thinking vLLM /metrics — port from the live endpoint (8080–8095)."""

    name = "vllm"
    cadence_s = 0.1

    def _url(self) -> str:
        env = os.getenv("GAIUS_VLLM_METRICS_URL")
        if env:
            return env
        port = os.getenv("GAIUS_THINKING_PORT")
        if port and port.isdigit():
            return f"http://127.0.0.1:{port}/metrics"
        return "http://127.0.0.1:8081/metrics"

    def __init__(self) -> None:
        self._prev: dict[str, tuple[float, float]] = {}

    def channel_names(self) -> tuple[str, ...]:
        return ("kv", "run", "gen-tps", "prefill", "wait", "preempt")

    def sample(self, ctx: dict[str, Any]) -> list[Sample]:
        text = _http_get(self._url())
        now = time.monotonic()
        if not text:
            return [Sample(n, 0.0, present=False) for n in self.channel_names()]
        kv = run = None
        gen = pre = None
        wait = preempt = None
        for metric, _labels, val in parse_prom_text(text):
            base = _metric_base(metric)
            if base in ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"):
                kv = val
            elif base == "vllm:num_requests_running":
                run = val
            elif base == "vllm:num_requests_waiting":
                wait = val
            elif base == "vllm:generation_tokens_total":
                gen = val
            elif base == "vllm:prompt_tokens_total":
                pre = val
            elif base == "vllm:num_preemptions_total":
                preempt = val
        gen_tps = self._rate("gen", gen, now)
        pre_tps = self._rate("pre", pre, now)
        # Preemptions are a monotonic counter; the strip wants the event rate, so
        # a burst reads as a spike (rising -> red) rather than an ever-rising line.
        preempt_rate = self._rate("preempt", preempt, now)
        return [
            Sample("kv", _clip(kv if kv is not None else 0.0), kv is not None),
            Sample("run", _clip(1.0 if (run or 0) > 0 else 0.0), run is not None),
            Sample(
                "gen-tps",
                _clip(math.log1p(gen_tps) / math.log1p(80.0)),
                gen is not None,
            ),
            Sample(
                "prefill",
                _clip(math.log1p(pre_tps) / math.log1p(200.0)),
                pre is not None,
            ),
            # Queue depth (log-scaled so a queue of a few is already visible) and
            # preemption rate — the two congestion signals for vLLM serving.
            Sample(
                "wait",
                _clip(math.log1p(wait or 0.0) / math.log1p(64.0)),
                wait is not None,
            ),
            Sample(
                "preempt",
                _clip(math.log1p(preempt_rate) / math.log1p(20.0)),
                preempt is not None,
            ),
        ]

    def _rate(self, key: str, counter: float | None, now: float) -> float:
        if counter is None:
            return 0.0
        prev = self._prev.get(key)
        self._prev[key] = (counter, now)
        if not prev:
            return 0.0
        dt = now - prev[1]
        if dt <= 0:
            return 0.0
        return max(0.0, (counter - prev[0]) / dt)


class CltDriver:
    """CLT presence: loaded heartbeat + recent feature_tape. SAE reserved absent."""

    name = "clt"
    cadence_s = 0.1

    def channel_names(self) -> tuple[str, ...]:
        return ("clt", "sae")

    def sample(self, ctx: dict[str, Any]) -> list[Sample]:
        n = int(ctx.get("tape_n") or 0)
        peak = float(ctx.get("tape_peak") or 0.0)
        loaded = bool(ctx.get("clt_loaded"))
        sae = bool(ctx.get("sae_loaded"))
        if n > 0:
            energy = _clip(min(1.0, n / 8.0 + peak / 4.0))
            clt = Sample("clt", energy, present=True)
        elif loaded:
            clt = Sample("clt", _CLT_HEARTBEAT, present=True)
        else:
            clt = Sample("clt", 0.0, present=False)
        if sae:
            sae_s = Sample("sae", _CLT_HEARTBEAT, present=True)
        else:
            sae_s = Sample("sae", 0.0, present=False)
        return [clt, sae_s]


def _as_mat(vecs: Any) -> Any:
    import numpy as np

    if vecs is None:
        return None
    arr = np.asarray(vecs, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 1 or arr.shape[1] < 2:
        return None
    return arr


def _vec_from_point(point: Any) -> list[float] | None:
    raw = getattr(point, "vector", None)
    if raw is None:
        return None
    if isinstance(raw, dict):
        picked = raw.get("agg")
        if picked is None and raw:
            picked = next(iter(raw.values()))
        raw = picked
    if raw is None:
        return None
    try:
        out = [float(x) for x in raw]
    except (TypeError, ValueError):
        return None
    if len(out) < 2:
        return None
    return out


_SCROLL_CACHE: dict[str, tuple[float, int, Any]] = {}
_SCROLL_TTL_S = 30.0


def _scroll_collection(name: str, limit: int = _RICCI_N) -> Any:
    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6339"))
    client = QdrantClient(host=host, port=port, timeout=0.4)
    if not client.collection_exists(name):
        return None
    info = client.get_collection(name)
    count = int(getattr(info, "points_count", 0) or 0)
    now = time.monotonic()
    hit = _SCROLL_CACHE.get(name)
    if hit is not None and hit[1] == count and now - hit[0] < _SCROLL_TTL_S:
        return hit[2]
    try:
        points, _ = client.scroll(
            collection_name=name,
            limit=limit,
            with_vectors=["agg"],
            with_payload=False,
        )
    except Exception:
        points, _ = client.scroll(
            collection_name=name,
            limit=limit,
            with_vectors=True,
            with_payload=False,
        )
    rows = []
    for pt in points or []:
        vec = _vec_from_point(pt)
        if vec is not None:
            rows.append(vec)
    if len(rows) < 4:
        return None
    import numpy as np

    arr = np.asarray(rows, dtype=float)
    _SCROLL_CACHE[name] = (now, count, arr)
    return arr


def _first_scroll(names: tuple[str, ...]) -> Any:
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            arr = _scroll_collection(name)
        except Exception as e:
            logger.debug("qdrant scroll %s: %s", name, e)
            continue
        if arr is not None:
            return arr
    return None


def ollivier_mean(vecs: Any) -> float | None:
    """Mean Ollivier–Ricci curvature on a k-NN graph. None if library missing."""
    import numpy as np

    arr = _as_mat(vecs)
    if arr is None or arr.shape[0] < 4:
        return None
    if arr.shape[0] > _RICCI_N:
        arr = arr[-_RICCI_N:]
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms
    n = int(arr.shape[0])
    k = min(_RICCI_K, n - 1)
    sim = arr @ arr.T
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    for i in range(n):
        row = sim[i]
        idx = np.argpartition(-row, k + 1)[: k + 1]
        for j in idx:
            j = int(j)
            if j == i:
                continue
            dist = float(max(1e-6, 1.0 - row[j]))
            graph.add_edge(i, j, weight=dist)
    try:
        from GraphRicciCurvature.OllivierRicci import OllivierRicci
    except ImportError:
        return None
    orc = OllivierRicci(graph, alpha=0.5, method="OTD", verbose="ERROR")
    orc.compute_ricci_curvature()
    vals: list[float] = []
    for node in graph.nodes():
        cs = [
            float(orc.G[node][nb].get("ricciCurvature", 0.0))
            for nb in graph.neighbors(node)
        ]
        if cs:
            vals.append(float(np.mean(cs)))
    if not vals:
        return None
    return float(np.mean(vals))


_ORC_PROC: Any = None
_ORC_LOCK = threading.Lock()


def ricci_worker_main() -> None:
    """stdin: JSON matrix; stdout: JSON float. No CUDA, no gRPC."""
    import sys

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        import json

        mean = ollivier_mean(json.loads(line))
        sys.stdout.write(json.dumps(mean) + "\n")
        sys.stdout.flush()


def _orc_child() -> Any:
    """GPU-free child so OTD cannot hang the CUDA engine process."""
    global _ORC_PROC
    with _ORC_LOCK:
        if _ORC_PROC is not None and _ORC_PROC.poll() is None:
            return _ORC_PROC
        import subprocess
        import sys

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ""
        _ORC_PROC = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from gaius.engine.services.waterfall_drivers import ricci_worker_main; "
                "ricci_worker_main()",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
        )
        return _ORC_PROC


def compute_ollivier(vecs: Any) -> float | None:
    if _TESTING:
        return ollivier_mean(vecs)
    try:
        import json
        import select

        import numpy as np

        arr = np.ascontiguousarray(vecs, dtype=np.float64)
        proc = _orc_child()
        if proc.stdin is None or proc.stdout is None:
            return None
        proc.stdin.write(json.dumps(arr.tolist()) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 5.0)
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            return None
        val = json.loads(line)
        return float(val) if val is not None else None
    except Exception as e:
        logger.warning("ollivier worker: %s", e)
        return None


def _digest(arr: Any) -> bytes:
    import numpy as np

    return hashlib.sha1(np.ascontiguousarray(arr, dtype=np.float32).tobytes()).digest()


class RicciDriver:
    """Ollivier–Ricci mean and Δmean on KB + buffer embeddings (salience onset)."""

    name = "ricci"
    cadence_s = 2.0

    def __init__(self) -> None:
        self._mean = 0.0
        self._prev = 0.0
        self._at = 0.0
        self._digest = b""
        self._have = False

    def channel_names(self) -> tuple[str, ...]:
        return ("ricci", "ricci-d")

    def sample(self, ctx: dict[str, Any]) -> list[Sample]:
        now = time.monotonic()
        if self._have and now - self._at < self.cadence_s:
            return self._emit()
        mats = self._manifolds(ctx)
        if not mats:
            if self._have:
                return self._emit()
            return [Sample("ricci", 0.0, present=False), Sample("ricci-d", 0.0, present=False)]
        try:
            self._recompute(mats)
            self._at = now
        except Exception as e:
            logger.warning("ricci recompute skipped: %s", e)
        if not self._have:
            return [Sample("ricci", 0.0, present=False), Sample("ricci-d", 0.0, present=False)]
        return self._emit()

    def _emit(self) -> list[Sample]:
        d = _clip(_RICCI_GAIN * (self._mean - self._prev)) if self._have else 0.0
        return [
            Sample("ricci", _clip(self._mean), present=self._have),
            Sample("ricci-d", d, present=self._have),
        ]

    def _manifolds(self, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        live = _as_mat(ctx.get("embeddings"))
        kb = _as_mat(ctx.get("embeddings_kb"))
        buf = _as_mat(ctx.get("embeddings_buf"))
        if not _TESTING:
            if kb is None:
                kb = _first_scroll(KB_COLLECTIONS)
            if buf is None:
                buf = _first_scroll(BUF_COLLECTIONS)
        # Prefer live CLT/buffer vectors; fill from KB so Δ tracks arrivals.
        if live is not None and kb is not None and live.shape[1] == kb.shape[1]:
            import numpy as np

            n_live = min(8, live.shape[0])
            n_kb = min(_RICCI_N - n_live, kb.shape[0])
            out.append(np.vstack([live[-n_live:], kb[-n_kb:]]))
        else:
            if live is not None:
                out.append(live)
            if kb is not None:
                out.append(kb)
        if buf is not None:
            out.append(buf)
        return out

    def _recompute(self, mats: list[Any]) -> None:
        import numpy as np

        means: list[float] = []
        dig_parts: list[bytes] = []
        for mat in mats:
            dig_parts.append(_digest(mat))
            m = compute_ollivier(mat)
            if m is not None:
                means.append(m)
        digest = hashlib.sha1(b"".join(dig_parts)).digest()
        if digest == self._digest and self._have:
            self._prev = self._mean
            return
        if not means:
            return
        new_mean = float(np.mean(means))
        if self._have:
            self._prev = self._mean
            self._mean = new_mean
        else:
            self._mean = new_mean
            self._prev = new_mean
        self._digest = digest
        self._have = True


DRIVERS: list[Driver] = []
_CACHE: dict[str, list[Sample]] = {}
_CTX: dict[str, Any] = {}
_CTX_LOCK = threading.Lock()
_POLLS: list[threading.Thread] = []
_POLL_STOP = False
_TESTING = False
_LP: dict[str, float] = {}
_KUMO: dict[int, dict[str, float]] = {}
_KUMO_LOCK = threading.Lock()


def _as_transient(name: str, value: float, present: bool) -> float:
    """High-pass real measures so the strip shows onsets, not DC bars."""
    if name.startswith("gpu-"):
        # Packed power+util; AC-coupling would destroy the pair.
        return float(value) if present else 0.0
    if not present:
        _LP.pop(name, None)
        return 0.0
    x = float(value)
    lp = _LP.get(name)
    if lp is None:
        _LP[name] = x
        return _clip(_DC_GAIN * x)
    lp = lp + _LP_ALPHA * (x - lp)
    _LP[name] = lp
    return _clip(_DC_GAIN * x + _HP_GAIN * (x - lp))


def _transients(samples: list[Sample]) -> list[Sample]:
    return [
        Sample(s.name, _as_transient(s.name, s.value, s.present), s.present)
        for s in samples
    ]


def _record_hardware(
    power: list[float | None], util: list[float | None]
) -> None:
    watts = [p for p in power[:4] if p is not None]
    utils = [u for u in util[:4] if u is not None]
    if not watts:
        return
    minute = int(time.time()) // 60
    with _KUMO_LOCK:
        rec = _KUMO.setdefault(
            minute, {"watts": 0.0, "util": 0.0, "salience": 0.0, "n": 0.0}
        )
        n = rec["n"]
        rec["watts"] = (rec["watts"] * n + float(sum(watts))) / (n + 1.0)
        if utils:
            rec["util"] = (rec["util"] * n + float(sum(utils)) / len(utils)) / (
                n + 1.0
            )
        rec["n"] = n + 1.0
        cutoff = minute - 90
        for old in [k for k in _KUMO if k < cutoff]:
            _KUMO.pop(old, None)


def _record_salience(energy: float) -> None:
    minute = int(time.time()) // 60
    with _KUMO_LOCK:
        rec = _KUMO.setdefault(
            minute, {"watts": 0.0, "util": 0.0, "salience": 0.0, "n": 0.0}
        )
        rec["salience"] = max(rec["salience"], float(energy))


def kumo_minutes() -> dict[datetime, tuple[float, float, float]]:
    """Live 1h DCGM/onset minutes for Discover Kumo. (watts, util_pct, salience)."""
    from datetime import datetime, timezone

    out: dict[datetime, tuple[float, float, float]] = {}
    with _KUMO_LOCK:
        for m, rec in _KUMO.items():
            ts = datetime.fromtimestamp(m * 60, tz=timezone.utc).replace(
                second=0, microsecond=0
            )
            out[ts] = (float(rec["watts"]), float(rec["util"]), float(rec["salience"]))
    return out


def register(driver: Driver) -> None:
    """Replace a driver of the same name, or append. Channel order follows registry."""
    global DRIVERS
    names = [d.name for d in DRIVERS]
    if driver.name in names:
        DRIVERS = [driver if d.name == driver.name else d for d in DRIVERS]
    else:
        DRIVERS.append(driver)
    _CACHE.pop(driver.name, None)


def reset_for_tests() -> None:
    global _TESTING, _POLL_STOP
    _TESTING = True
    _POLL_STOP = True
    _CACHE.clear()
    _LP.clear()
    with _CTX_LOCK:
        _CTX.clear()
    with _KUMO_LOCK:
        _KUMO.clear()


def _seed_drivers() -> None:
    if DRIVERS:
        return
    register(HardwareDriver())
    register(VllmDriver())
    register(CltDriver())
    register(RicciDriver())


_seed_drivers()


# HardwareDriver's channels are the GPU strip and already land in
# gpu_metrics. Everything else is cognition and belongs in cognition_metrics.
HARDWARE_DRIVER_NAME = "hardware"


def cognition_channel_names() -> tuple[str, ...]:
    """Channel names the warehouse carries in cognition_metrics."""
    names: list[str] = []
    for d in DRIVERS:
        if d.name == HARDWARE_DRIVER_NAME:
            continue
        names.extend(d.channel_names())
    return tuple(names)


def cognition_samples() -> list[Sample]:
    """Latest cached cognition samples, for the warehouse writer.

    Reads the poller's cache rather than re-sampling: RicciDriver runs an
    Ollivier curvature pass that must not be driven at ingest cadence.
    Channels the poller has not filled yet come back ``present=False`` so a
    gap is recorded as a gap, not as zero.
    """
    out: list[Sample] = []
    for d in DRIVERS:
        if d.name == HARDWARE_DRIVER_NAME:
            continue
        cached = _CACHE.get(d.name)
        if cached:
            out.extend(cached)
        else:
            out.extend(Sample(n, 0.0, present=False) for n in d.channel_names())
    return out


def all_channel_names() -> tuple[str, ...]:
    names: list[str] = []
    for d in DRIVERS:
        names.extend(d.channel_names())
    return tuple(names)


def onset_envelope(samples: list[Sample]) -> float:
    peak = 0.0
    for s in samples:
        if s.name not in ONSET_NAMES:
            continue
        if not s.present:
            continue
        a = abs(float(s.value))
        if a > peak:
            peak = a
    return peak


def _poll_loop(slow: bool) -> None:
    last: dict[str, float] = {}
    while not _POLL_STOP:
        now = time.monotonic()
        with _CTX_LOCK:
            ctx = dict(_CTX)
        for d in list(DRIVERS):
            cadence = float(getattr(d, "cadence_s", 0.1) or 0.1)
            is_slow = cadence >= 1.0
            if is_slow != slow:
                continue
            if now - last.get(d.name, 0.0) < cadence:
                continue
            try:
                raw = d.sample(ctx)
            except Exception as e:
                logger.warning("waterfall driver %s: %s", d.name, e)
                raw = [Sample(n, 0.0, present=False) for n in d.channel_names()]
            _record_salience(onset_envelope(raw))
            _CACHE[d.name] = _transients(raw)
            last[d.name] = now
        if not slow:
            try:
                from gaius.engine.services.cognition_waterfall import ingest_fast_column

                ingest_fast_column()
            except Exception:
                pass
        time.sleep(0.25 if slow else 0.1)


def ensure_poller() -> None:
    """HTTP / Ricci off the gRPC thread so 10 Hz ticks stay cheap."""
    global _POLLS, _POLL_STOP
    if _TESTING:
        return
    alive = [t for t in _POLLS if t.is_alive()]
    if len(alive) >= 2:
        _POLLS = alive
        return
    _POLL_STOP = False
    _POLLS = alive
    for slow, name in ((False, "wf-fast"), (True, "wf-slow")):
        if any(t.name == name and t.is_alive() for t in _POLLS):
            continue
        t = threading.Thread(target=_poll_loop, args=(slow,), name=name, daemon=True)
        t.start()
        _POLLS.append(t)


def sample_column(ctx: dict[str, Any]) -> list[Sample]:
    with _CTX_LOCK:
        _CTX.update(ctx or {})
        snap = dict(_CTX)
    if _TESTING:
        col: list[Sample] = []
        for d in DRIVERS:
            try:
                col.extend(_transients(d.sample(snap)))
            except Exception as e:
                logger.debug("driver %s failed: %s", getattr(d, "name", d), e)
                col.extend(Sample(n, 0.0, present=False) for n in d.channel_names())
        return col
    ensure_poller()
    col = []
    for d in DRIVERS:
        cached = _CACHE.get(d.name)
        if cached is not None:
            col.extend(cached)
        else:
            col.extend(Sample(n, 0.0, present=False) for n in d.channel_names())
    return col
