"""Map CLT token positions to char spans inside an admitted 512-item."""

from __future__ import annotations


GURU_LEN = (
    "CLT position is outside tokenizer offsets.\n"
    "  Guru: #CLT.00000010.OFFMISMATCH\n"
    "  The extract seq_len must match offset_mapping length."
)


class GroundError(ValueError):
    """Fail-fast span alignment error."""


def spans_for_features(
    features: list[dict],
    offsets: list[tuple[int, int]],
) -> list[tuple[str, int, int, int, int, int, float]]:
    """Return (model, layer, feat, pos, span_start, span_end, act).

    Special-token positions with empty spans are dropped.
    """
    if not offsets:
        raise GroundError(GURU_LEN)
    n = len(offsets)
    out: list[tuple[str, int, int, int, int, int, float]] = []
    for f in features:
        pos = int(f["position"])
        if pos < 0 or pos >= n:
            raise GroundError(f"{GURU_LEN}\n  position={pos} n_offsets={n}")
        start, end = offsets[pos]
        if end <= start:
            continue
        out.append(
            (
                str(f.get("model") or "clt"),
                int(f["layer_idx"]),
                int(f["feature_idx"]),
                pos,
                int(start),
                int(end),
                float(f["activation"]),
            )
        )
    return out
