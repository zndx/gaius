"""Aegir-grain sliding windows for SEC extracts (512 tokens, stride 256).

Uses the ColBERT-Zero tokenizer so the same scheme as
``gaius_kb_colbert_zero`` / Aegir ``token_windows``. MaxSim against
``gaius_prospects_aperture`` is optional: when the collection is missing
every window is a candidate (compact still sees the full span set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

WINDOW_SIZE = 512
WINDOW_STRIDE = 256
DEFAULT_MAX_WINDOWS = 64
APERTURE_COLLECTION = "gaius_prospects_aperture"

OffsetFn = Callable[[str], list[tuple[int, int]]]


@dataclass
class TokenWindow:
    start: int
    end: int
    text: str
    admitted: bool = True
    code: str = ""
    margin: float = 0.0


@dataclass
class WindowScan:
    windows: list[TokenWindow] = field(default_factory=list)
    aperture: str = APERTURE_COLLECTION
    aperture_used: bool = False


def token_windows(
    text: str,
    *,
    stride: int = WINDOW_STRIDE,
    size: int = WINDOW_SIZE,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    encode_offsets: OffsetFn | None = None,
) -> list[tuple[int, int]]:
    """Char spans of ≤size-token windows at stride tokens."""
    if not text:
        return []
    offs_fn = encode_offsets or colbert_offsets
    offs = [o for o in offs_fn(text) if o[1] > o[0]]
    if not offs:
        return [(0, len(text))]
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(offs) and len(out) < max_windows:
        j = min(i + size, len(offs))
        out.append((offs[i][0], offs[j - 1][1]))
        if j >= len(offs):
            break
        i += stride
    return out


def colbert_offsets(text: str) -> list[tuple[int, int]]:
    """Offsets from the ColBERT-Zero tokenizer (fail-fast if pylate missing)."""
    from gaius.inference.search.colbert import ColBERTZeroEmbedder

    enc = ColBERTZeroEmbedder()
    tok = enc.model.tokenizer
    encoded = tok(
        text,
        truncation=False,
        return_offsets_mapping=True,
        add_special_tokens=False,
    )
    return list(encoded["offset_mapping"])


def scan_windows(
    text: str,
    *,
    stride: int = WINDOW_STRIDE,
    size: int = WINDOW_SIZE,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    encode_offsets: OffsetFn | None = None,
    maxsim: Callable[[str], tuple[str, float]] | None = None,
    tau: float = 0.10,
) -> WindowScan:
    """Slice text and optionally admit via MaxSim (Aegir item_scan shape)."""
    spans = token_windows(
        text,
        stride=stride,
        size=size,
        max_windows=max_windows,
        encode_offsets=encode_offsets,
    )
    result = WindowScan()
    for start, end in spans:
        chunk = text[start:end]
        admitted = True
        code = ""
        margin = 0.0
        if maxsim is not None:
            result.aperture_used = True
            code, margin = maxsim(chunk)
            admitted = bool(code) and margin >= tau
        result.windows.append(
            TokenWindow(
                start=start,
                end=end,
                text=chunk,
                admitted=admitted,
                code=code,
                margin=margin,
            )
        )
    if maxsim is not None:
        kept: list[TokenWindow] = []
        for w in sorted(
            [w for w in result.windows if w.admitted],
            key=lambda x: -x.margin,
        ):
            if any(not (w.end <= k.start or w.start >= k.end) for k in kept):
                w.admitted = False
                continue
            kept.append(w)
    return result


def admitted_text(scan: WindowScan) -> str:
    parts = [w.text for w in scan.windows if w.admitted]
    return "\n\n".join(parts) if parts else ""
