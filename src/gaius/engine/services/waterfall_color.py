"""Strip colors: DkCyan2 (biscale) for steady state + red/blue motion.

gpu-n packs power + util. Hue/chroma come from Joshua Stevens' DkCyan2
3×3 (biscale ``DkCyan2``). Sharp Δ overlays ColorBrewer red / blue.
Same formulas as discover.js — keep in lockstep.

https://cran.r-project.org/web/packages/biscale/vignettes/bivariate_palettes.html
"""

from __future__ import annotations

import math

# packed: 0 = absent; present in [1, 2.0001]
_PACK_BASE = 1.0
_PACK_P = 1.0e-4

# biscale DkCyan2 dim=3, x=power, y=util (QGIS / Stevens layout).
# Rows = power ix 0..2, cols = util iy 0..2.
DKCYAN2 = (
    ((0xD3, 0xD3, 0xD3), (0x9E, 0xB9, 0xA4), (0x69, 0x9E, 0x74)),
    ((0x9A, 0xA5, 0xBB), (0x73, 0x90, 0x91), (0x4C, 0x7C, 0x67)),
    ((0x62, 0x77, 0xA5), (0x4A, 0x68, 0x80), (0x31, 0x59, 0x5B)),
)
# ColorBrewer Reds/Blues 5, skip the near-white stops so both themes read.
RAMP_POS = (
    (252, 187, 161),
    (252, 146, 114),
    (251, 106, 74),
    (222, 45, 38),
    (165, 15, 21),
)
RAMP_NEG = (
    (158, 202, 225),
    (107, 174, 214),
    (66, 146, 198),
    (33, 113, 181),
    (8, 69, 148),
)
FLASH_POS = RAMP_POS[-1]
FLASH_NEG = RAMP_NEG[-1]


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _clip11(x: float) -> float:
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return x


def pack_gpu(power: float, util: float) -> float:
    """Pack signed power [-1,1] and util [0,1]. 0 is reserved for absent.

    util is quantized to the 1e-4 grid (unpack recovers it with the same
    floor). Without this, a util that is not already a clean multiple of 1e-4 —
    e.g. mem-N's VRAM ratio fb_used/(fb_used+fb_free) = 0.885060… — spills its
    sub-1e-4 digits into the power/bandwidth residual and corrupts it. gpu-N's
    util is int/100 so it was unaffected; mem-N exposed the assumption.
    """
    p01 = (_clip11(power) + 1.0) * 0.5
    u01 = math.floor(_clip01(util) * 10000.0) / 10000.0
    return _PACK_BASE + u01 + p01 * _PACK_P


def unpack_gpu(x: float) -> tuple[float, float, bool]:
    """Return (power, util, present)."""
    if x < 0.5:
        return 0.0, 0.0, False
    t = float(x) - _PACK_BASE
    if t < 0.0:
        t = 0.0
    u = math.floor(t * 10000.0 + 1e-9) / 10000.0
    if u > 1.0:
        u = 1.0
    p01 = (t - u) / _PACK_P
    if p01 < 0.0:
        p01 = 0.0
    if p01 > 1.0:
        p01 = 1.0
    return p01 * 2.0 - 1.0, u, True


def dkcyan2(power: float, util: float) -> tuple[int, int, int]:
    """Bilinear sample of DkCyan2. x=power load 0..1, y=util 0..1."""
    x = _clip01(power) * 2.0
    y = _clip01(util) * 2.0
    i0 = min(1, int(x))
    j0 = min(1, int(y))
    i1 = i0 + 1
    j1 = j0 + 1
    tx = x - i0
    ty = y - j0
    c00 = DKCYAN2[i0][j0]
    c10 = DKCYAN2[i1][j0]
    c01 = DKCYAN2[i0][j1]
    c11 = DKCYAN2[i1][j1]
    out = [0, 0, 0]
    for k in range(3):
        a = c00[k] * (1.0 - tx) + c10[k] * tx
        b = c01[k] * (1.0 - tx) + c11[k] * tx
        out[k] = int(round(a * (1.0 - ty) + b * ty))
    return out[0], out[1], out[2]


def onset_field(values: list[float]) -> list[float]:
    """Signed onset from v' and v'' of the actual series.

    Each sample-to-sample change (v') is the peak. v'' (change of v')
    sets how much of that event blends onto the previous column (attack)
    and the next (decay): sharp corners stay narrow, slower ramps spread.
    """
    n = len(values)
    if n == 0:
        return []
    e = [0.0] * n
    prev_dv = 0.0
    for i in range(1, n):
        dv = float(values[i]) - float(values[i - 1])
        d2 = dv - prev_dv
        prev_dv = dv
        sharp = _clip01(abs(d2))
        peak = abs(dv) * (1.0 + 0.55 * sharp)
        # |v''| large → less spread, more mass at the peak.
        spread = abs(dv) * 1.05 * (1.0 - 0.4 * sharp)
        sign = 1.0 if dv >= 0.0 else -1.0

        def acc(j: int, mag: float) -> None:
            s = sign * mag
            cur = e[j]
            if cur * s >= 0.0:
                e[j] = cur + s if abs(s) >= abs(cur) else cur + 0.35 * s
            else:
                e[j] = s if abs(s) >= abs(cur) else cur

        acc(i, peak)
        acc(i - 1, spread)
        if i + 1 < n:
            acc(i + 1, spread)
    return e


def _lerp_rgb(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    t = _clip01(t)
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def highpass(values: list[float], alpha: float = 0.12) -> list[float]:
    """Causal EMA high-pass so gpu-n walks the palette like util-n."""
    if not values:
        return []
    ema = float(values[0])
    out: list[float] = []
    for v in values:
        x = float(v)
        ema = ema + alpha * (x - ema)
        out.append(x - ema)
    return out


def flash_rgb(energy: float) -> tuple[int, int, int]:
    """Graded red (Δ+) or blue (Δ−); t maps the whole ramp, not one solid."""
    a = max(0.0, abs(float(energy)) - 0.02)
    t = _clip01(a / 1.15)
    stops = RAMP_POS if energy >= 0.0 else RAMP_NEG
    x = t * (len(stops) - 1)
    i = min(len(stops) - 2, int(x))
    f = x - i
    return _lerp_rgb(stops[i], stops[i + 1], f)


def motion_mix(energy: float) -> float:
    """How hard to mix flash over DkCyan2. Shoulders mid-ramp, peak deep."""
    a = max(0.0, abs(float(energy)) - 0.025)
    return _clip01(1.0 - math.exp(-1.65 * a))


def overlay_motion(
    rgb: tuple[int, int, int], delta: float
) -> tuple[int, int, int]:
    """Mix toward a graded red/blue stop (not a single solid)."""
    a = motion_mix(delta)
    if a <= 0.0:
        return rgb
    return _lerp_rgb(rgb, flash_rgb(delta), a)


def gpu_rgb(
    power: float,
    util: float,
    prev_power: float | None = None,
    prev_util: float | None = None,
) -> tuple[int, int, int]:
    """Steady DkCyan2(power, util); optional pairwise Δ for unit tests."""
    p = _clip01(float(power))
    u = _clip01(float(util))
    base = dkcyan2(p, u)
    if prev_power is None or prev_util is None:
        return base
    dp = float(power) - float(prev_power)
    du = float(util) - float(prev_util)
    d = dp if abs(dp) >= abs(du) else du
    return overlay_motion(base, d)


def signed_rgb(
    v: float, prev: float | None = None
) -> tuple[int, int, int]:
    """Univariate DkCyan2 diagonal for |v|; overlay uses v (or Δ)."""
    mag = _clip01(abs(float(v)))
    base = dkcyan2(mag, mag)
    d = float(v) if prev is None else float(v) - float(prev)
    return overlay_motion(base, d)


def rgb_raster(
    matrix: list[list[float]], channel_names: tuple[str, ...] | list[str]
) -> list[list[tuple[int, int, int]]]:
    """Row-major RGB. Onset field from v'/v'' of the whole row."""
    out: list[list[tuple[int, int, int]]] = []
    for y, name in enumerate(channel_names):
        row = [float(v) for v in (matrix[y] if y < len(matrix) else [])]
        colored: list[tuple[int, int, int]] = []
        if name.startswith("gpu-"):
            powers: list[float] = []
            utils: list[float] = []
            for val in row:
                p, u, on = unpack_gpu(val)
                powers.append(p if on else 0.0)
                utils.append(u if on else 0.0)
            ep = onset_field(powers)
            eu = onset_field(utils)
            hp_p = highpass(powers)
            hp_u = highpass(utils)
            for i, val in enumerate(row):
                p, u, on = unpack_gpu(val)
                if not on:
                    colored.append(dkcyan2(0.0, 0.0))
                    continue
                p_vis = _clip01(0.45 * _clip01(p) + 0.9 * abs(hp_p[i]))
                u_vis = _clip01(0.45 * _clip01(u) + 0.9 * abs(hp_u[i]))
                base = dkcyan2(p_vis, u_vis)
                e = ep[i] if abs(ep[i]) >= abs(eu[i]) else eu[i]
                colored.append(overlay_motion(base, e))
        else:
            e = onset_field(row)
            for i, val in enumerate(row):
                mag = _clip01(abs(val))
                base = dkcyan2(mag, mag)
                colored.append(overlay_motion(base, e[i] if i < len(e) else 0.0))
        out.append(colored)
    return out
