"""Aperture admission for buffer axes: 512-token windows, unique MaxSim.

Admitted iff MaxSim affinity is strong for **exactly one** topic-domain
point (score >= tau, no second point also >= tau). Ambiguous or empty
windows are not synthesized. Persistent starve is a signal for GEPA on C.

Guru: #SDG.00000006.STARVE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from gaius.engine.services.sdg_aperture import SdgAperture
from gaius.flows.prospects.windows import TokenWindow, scan_windows

OffsetFn = Callable[[str], list[tuple[int, int]]]


@dataclass
class AdmitStats:
    scanned: int = 0
    admitted: int = 0
    none: int = 0
    ambiguous: int = 0

    def starved(self) -> bool:
        return self.scanned > 0 and self.admitted == 0


def unique_topic(
    ranked: list[tuple[str, float]],
    tau: float,
) -> tuple[str, float, str]:
    """Exactly-one topic above tau. reason: admitted | none | ambiguous."""
    above = [(c, s) for c, s in ranked if c and s >= tau]
    if not above:
        top = ranked[0][1] if ranked else 0.0
        return "", top, "none"
    if len(above) > 1:
        return "", above[0][1], "ambiguous"
    return above[0][0], above[0][1], "admitted"


def try_prepare(
    text: str,
    *,
    stats: AdmitStats,
    clt: Any | None = None,
    encode_offsets: OffsetFn | None = None,
) -> dict[str, Any] | None:
    aperture = SdgAperture.load()
    return prepare_axis_item(
        text,
        aperture=aperture,
        stats=stats,
        maxsim=lambda chunk: unique_maxsim(chunk, aperture=aperture),
        clt=clt,
        encode_offsets=encode_offsets,
    )


def unique_maxsim(
    chunk: str,
    *,
    aperture: SdgAperture | None = None,
) -> tuple[str, float, str]:
    """Top-2 MaxSim; admit only a unique domain point."""
    from gaius.engine.services.clt_skos_aperture import unique_maxsim_window

    return unique_maxsim_window(chunk, aperture=aperture)


def admit_unique_windows(
    text: str,
    *,
    aperture: SdgAperture,
    maxsim: Callable[[str], tuple[str, float, str]] | None,
    encode_offsets: OffsetFn | None = None,
    stats: AdmitStats | None = None,
) -> list[TokenWindow]:
    stats = stats or AdmitStats()

    def _as_pair(chunk: str) -> tuple[str, float]:
        if maxsim is None:
            return "", 0.0
        code, score, reason = maxsim(chunk)
        stats.scanned += 1
        if reason == "admitted":
            stats.admitted += 1
            return code, score
        if reason == "ambiguous":
            stats.ambiguous += 1
        else:
            stats.none += 1
        return "", score

    kept = admit_via_scan(
        text,
        aperture=aperture,
        pair_maxsim=_as_pair if maxsim is not None else None,
        encode_offsets=encode_offsets,
    )
    return kept


def admit_via_scan(
    text: str,
    *,
    aperture: SdgAperture,
    pair_maxsim: Callable[[str], tuple[str, float]] | None,
    encode_offsets: OffsetFn | None = None,
) -> list[TokenWindow]:
    scan = scan_windows(
        text,
        size=aperture.colbert_token_limit,
        maxsim=pair_maxsim,
        tau=aperture.tau,
        encode_offsets=encode_offsets,
    )
    return [w for w in scan.windows if w.admitted]


def prepare_axis_item(
    text: str,
    *,
    aperture: SdgAperture,
    stats: AdmitStats,
    maxsim: Callable[[str], tuple[str, float, str]] | None,
    clt: Any | None = None,
    encode_offsets: OffsetFn | None = None,
) -> dict[str, Any] | None:
    windows = admit_unique_windows(
        text,
        aperture=aperture,
        maxsim=maxsim,
        encode_offsets=encode_offsets,
        stats=stats,
    )
    packed = pack_admitted(windows)
    if not packed:
        return None
    clt_meta: list[dict[str, Any]] = []
    if clt is not None:
        try:
            state = clt.extract_features(packed[:4000], "user")
            clt_meta = clt_activation_preview(state)
        except Exception:
            clt_meta = []
    return {
        "text": packed,
        "topic": windows[0].code,
        "margin": windows[0].margin,
        "clt": clt_meta,
    }


def admitted_spans(
    content: str,
    *,
    entry_id: str = "",
    axis: str = "",
    aperture: SdgAperture | None = None,
    maxsim: Callable[[str], tuple[str, float, str]] | None = None,
    stats: AdmitStats | None = None,
    encode_offsets: OffsetFn | None = None,
) -> list[dict[str, Any]]:
    """Sliding windows over one buffer entry. Offsets into that entry's text."""
    aperture = aperture or SdgAperture.load()
    ms = maxsim or (lambda chunk: unique_maxsim(chunk, aperture=aperture))
    windows = admit_unique_windows(
        content,
        aperture=aperture,
        maxsim=ms,
        encode_offsets=encode_offsets,
        stats=stats,
    )
    out: list[dict[str, Any]] = []
    for w in windows:
        out.append(
            {
                "axis": axis,
                "entry_id": entry_id,
                "start": w.start,
                "end": w.end,
                "topic": w.code,
                "margin": w.margin,
                "content": content[w.start : w.end],
            }
        )
    return out


def pack_admitted(windows: list[TokenWindow], *, limit_chars: int = 4000) -> str:
    parts: list[str] = []
    n = 0
    for w in windows:
        chunk = w.text.strip()
        if not chunk:
            continue
        if n + len(chunk) > limit_chars:
            break
        parts.append(f"[{w.code} {w.margin:.3f}] {chunk}")
        n += len(chunk)
    return "\n\n".join(parts)


def clt_activation_preview(state: Any, *, top_k: int = 8) -> list[dict[str, Any]]:
    feats = getattr(state, "features", None) or []
    out: list[dict[str, Any]] = []
    for f in feats[:top_k]:
        out.append(
            {
                "layer": getattr(f, "layer", None),
                "idx": getattr(f, "feature_idx", getattr(f, "index", None)),
                "act": float(getattr(f, "activation", 0.0) or 0.0),
            }
        )
    return out
