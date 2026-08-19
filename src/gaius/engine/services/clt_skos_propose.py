"""Mint candidate CLT SKOS into sdg-corpora/contrib from observed activations."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from gaius.engine.services.sdg_catalog import DEFAULT_SDG_CORPORA

SCHEME_IRI = "https://signals.zndx.org/clt/qwen3-1.7b-20k/scheme"
CONCEPT_NS = "https://signals.zndx.org/clt/qwen3-1.7b-20k#"
CONTRIB = (
    Path(DEFAULT_SDG_CORPORA) / "contrib" / "clt" / "qwen3-1.7b-20k" / "clt.skos.ttl"
)
SNAP = Path(
    "/raid/cache/huggingface/models--bluelightai--clt-qwen3-1.7b-base-20k"
    "/snapshots/e94365594c94aa23f6d5e58c81a5485dfcb0a6d1/features"
)

_LAYER_BANDS = (
    (0, 7, "early", "Early-layer (lexical / local token) CLT activations"),
    (8, 18, "mid", "Mid-layer (argument / structure) CLT activations"),
    (19, 27, "late", "Late-layer (next-token / planning) CLT activations"),
)
_LOGIT_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,23}$")
_LOGIT_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "you",
        "are",
        "this",
        "that",
        "with",
        "from",
        "have",
        "was",
        "not",
    }
)
_IDX: dict[str, Any] | None = None


def _band(layer: int) -> tuple[str, str]:
    for lo, hi, slug, label in _LAYER_BANDS:
        if lo <= layer <= hi:
            return slug, label
    return "mid", "Mid-layer CLT activations"


def _ttl_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _index() -> dict[str, Any]:
    global _IDX
    if _IDX is None:
        idx_path = SNAP / "index.json.gz"
        if not idx_path.is_file():
            _IDX = {}
        else:
            _IDX = json.loads(gzip.decompress(idx_path.read_bytes()))
    return _IDX


def _read_logits(layer: int, feat: int) -> list[str]:
    meta = _index().get(str(layer))
    if not meta:
        return []
    offs = meta["offsets"]
    if feat < 0 or feat + 1 >= len(offs):
        return []
    raw = (SNAP / meta["filename"]).read_bytes()[offs[feat] : offs[feat + 1]]
    if raw[:2] != b"\x1f\x8b":
        raw = raw[4:]
    obj = json.loads(gzip.decompress(raw))
    return [str(t).strip() for t in (obj.get("top_logits") or []) if str(t).strip()][:5]


def readable_logit_tokens(logits: list[str], *, limit: int = 2) -> list[str]:
    """Keep decoder fragments that look like words; drop punctuation soup."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in logits:
        s = (
            str(raw)
            .replace("▁", "")
            .replace("Ġ", "")
            .replace("Ċ", "")
            .replace("⏎", "")
            .strip()
        )
        if not _LOGIT_WORD.fullmatch(s):
            continue
        if not any(c in "aeiouAEIOU" for c in s):
            continue
        if s.lower() in _LOGIT_STOP:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    out.sort(key=len, reverse=True)
    return out[:limit]


def feature_chip_label(
    layer: int, feat: int, logits: list[str] | None = None
) -> str:
    """Discover chip text: notation once, optional readable tokens."""
    notation = f"{layer}:{feat}"
    toks = readable_logit_tokens(
        logits if logits is not None else _read_logits(layer, feat)
    )
    if not toks:
        return notation
    return f"{notation} · " + " · ".join(toks)


def _pref_label(layer: int, feat: int, logits: list[str]) -> str:
    return feature_chip_label(layer, feat, logits)


def is_minted_pref_label(s: str | None) -> bool:
    """True when the label is a display phrase, not notation or logit chips."""
    if not s or not str(s).strip():
        return False
    t = str(s).strip()
    if re.match(r"^\d+:\d+", t):
        return False
    if re.match(r"^L\d+\s+F\d+", t, re.I):
        return False
    return True


def set_pref_label(
    notation: str, label: str, dest: Path | None = None
) -> Path:
    """Write skos:prefLabel for an existing (or new) CLT concept."""
    dest = dest or CONTRIB
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        layer, feat = (int(x) for x in notation.split(":", 1))
        write_candidate_ttl([(layer, feat, 1)], dest=dest)
    lines = dest.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    pending = False
    found = False
    for line in lines:
        if f'skos:notation "{notation}"' in line:
            pending = True
            out.append(line)
            continue
        if pending and "skos:prefLabel" in line:
            out.append(f'    skos:prefLabel "{_ttl_escape(label)}" ;')
            pending = False
            found = True
            continue
        if pending and (not line.strip() or line.startswith("<")):
            out.append(f'    skos:prefLabel "{_ttl_escape(label)}" ;')
            pending = False
            found = True
        out.append(line)
    if not found:
        layer, feat = (int(x) for x in notation.split(":", 1))
        slug, _ = _band(layer)
        iri = f"{CONCEPT_NS}L{layer}F{feat}"
        band_iri = f"{CONCEPT_NS}band_{slug}"
        out.extend(
            [
                "",
                f"<{iri}> a skos:Concept ;",
                f"    skos:inScheme <{SCHEME_IRI}> ;",
                f'    skos:notation "{notation}" ;',
                f'    skos:prefLabel "{_ttl_escape(label)}" ;',
                f"    skos:broader <{band_iri}> .",
            ]
        )
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dest


async def observed_features(pool: Any, *, min_items: int = 1) -> list[tuple[int, int, int]]:
    """(layer, feature_idx, n_items) from the grounded ledger, else the tape."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT layer, feature_idx, count(DISTINCT item_id)::int AS n
              FROM activation
             WHERE model = 'clt'
             GROUP BY 1, 2
             HAVING count(DISTINCT item_id) >= $1
             ORDER BY n DESC, layer, feature_idx
            """,
            min_items,
        )
        if rows:
            return [(int(r["layer"]), int(r["feature_idx"]), int(r["n"])) for r in rows]
        rows = await conn.fetch(
            """
            SELECT layer, feature_idx, count(DISTINCT event_id)::int AS n
              FROM feature_tape
             GROUP BY 1, 2
             HAVING count(DISTINCT event_id) >= $1
             ORDER BY n DESC, layer, feature_idx
             LIMIT 200
            """,
            min_items,
        )
    return [(int(r["layer"]), int(r["feature_idx"]), int(r["n"])) for r in rows]


def write_candidate_ttl(
    features: list[tuple[int, int, int]],
    dest: Path | None = None,
) -> Path:
    dest = dest or CONTRIB
    dest.parent.mkdir(parents=True, exist_ok=True)
    minted = {
        k: v
        for k, v in load_pref_labels(dest if dest.is_file() else None).items()
        if is_minted_pref_label(v)
    }
    bands_used: dict[str, str] = {}
    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix dct:  <http://purl.org/dc/terms/> .",
        "@prefix clt:  <https://signals.zndx.org/clt/qwen3-1.7b-20k#> .",
        "",
        f"<{SCHEME_IRI}> a skos:ConceptScheme ;",
        '    dct:title "Bluelight CLT Qwen3-1.7B 20k" ;',
        '    dct:description "Activation kinds observed on Gaius-admitted 512-token items. Distinct from the SDG domain scheme." ;',
        '    skos:prefLabel "bluelight-clt-qwen3-1.7b-20k" .',
        "",
    ]
    for layer, feat, n in features:
        slug, band_label = _band(layer)
        bands_used[slug] = band_label
        logits = _read_logits(layer, feat)
        pref = minted.get(f"{layer}:{feat}") or _pref_label(layer, feat, logits)
        iri = f"{CONCEPT_NS}L{layer}F{feat}"
        band_iri = f"{CONCEPT_NS}band_{slug}"
        alts = " , ".join(f'"{_ttl_escape(t)}"' for t in logits) if logits else ""
        lines.append(f"<{iri}> a skos:Concept ;")
        lines.append(f"    skos:inScheme <{SCHEME_IRI}> ;")
        lines.append(f'    skos:notation "{layer}:{feat}" ;')
        lines.append(f'    skos:prefLabel "{_ttl_escape(pref)}" ;')
        if alts:
            lines.append(f"    skos:altLabel {alts} ;")
        lines.append(f'    skos:scopeNote "observed on {n} admitted items" ;')
        lines.append(f"    skos:broader <{band_iri}> .")
        lines.append("")
    for slug, label in bands_used.items():
        iri = f"{CONCEPT_NS}band_{slug}"
        lines.append(f"<{iri}> a skos:Concept ;")
        lines.append(f"    skos:inScheme <{SCHEME_IRI}> ;")
        lines.append(f'    skos:prefLabel "{label}" ;')
        lines.append(f"    skos:topConceptOf <{SCHEME_IRI}> .")
        lines.append("")
        lines.append(f"<{SCHEME_IRI}> skos:hasTopConcept <{iri}> .")
        lines.append("")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def load_pref_labels(path: Path | None = None) -> dict[str, str]:
    """notation (layer:idx) → prefLabel from the contrib TTL."""
    path = path or CONTRIB
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    notation = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("skos:notation"):
            notation = s.split('"', 2)[1]
        elif s.startswith("skos:prefLabel") and notation:
            out[notation] = s.split('"', 2)[1]
            notation = ""
    return out
