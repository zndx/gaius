"""Materialize Aegir's aiming C in Gaius Qdrant with ColBERT-Zero MaxSim.

Same C / regime / 512-grain as ``sdg-strategy``. Encoder is
``lightonai/ColBERT-Zero`` (Signals multi-vector SoR). Sources stay
Gaius inbound. Score used for τ is mean MaxSim (raw / n_query_tokens)
so strategy ``domain_tau`` stays on a 0–1 scale.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from gaius.engine.services.sdg_aperture import SdgAperture

GURU_NOMAXSIM = (
    "Aperture MaxSim collection is required for CLT SKOS ingest.\n"
    "  Guru: #SDG.00000005.NOMAXSIM\n"
    "  Materialize sdg_aperture: CltSkosEvalFlow start or "
    "clt_skos_aperture.materialize_aperture()"
)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
ZERO_MODEL = "lightonai/ColBERT-Zero"


def _zero(device: str | None = None):
    from gaius.inference.search.colbert import ColBERTZeroEmbedder

    return ColBERTZeroEmbedder(device=device or _default_device())


def _qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def _snapshot_points(aperture: SdgAperture) -> list[dict[str, Any]]:
    path = aperture.root / "components" / "lens" / "aperture.snapshot.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pts = data.get("points") or []
    if not pts:
        raise RuntimeError(
            f"{GURU_NOMAXSIM}\n  snapshot has no points: {path}"
        )
    return pts


def _exclude_codes(aperture: SdgAperture) -> set[str]:
    filt = aperture.root / "components" / "lens" / "admission_filter.json"
    rec = json.loads(filt.read_text(encoding="utf-8"))
    armed = bool(rec.get("armed")) or os.environ.get("AEGIR_ADMISSION_FILTER") == "1"
    if not armed:
        return set()
    return {str(c) for c in (rec.get("exclude_codes") or [])}


def materialize_aperture(
    aperture: SdgAperture | None = None,
    *,
    device: str | None = None,
) -> dict[str, Any]:
    """Encode snapshot retrieval_text with ColBERT-Zero into sdg_aperture."""
    from qdrant_client import models

    aperture = aperture or SdgAperture.load()
    points = _snapshot_points(aperture)
    embedder = _zero(device)
    client = _qdrant()
    if client.collection_exists(aperture.collection):
        client.delete_collection(aperture.collection)
    dim = embedder.embedding_dim
    client.create_collection(
        collection_name=aperture.collection,
        vectors_config=models.VectorParams(
            size=dim,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
        ),
    )
    structs = []
    for pt in points:
        text = str(pt.get("retrieval_text") or pt.get("label") or "").strip()
        if not text:
            raise RuntimeError(
                f"{GURU_NOMAXSIM}\n  point {pt.get('iri')} has no retrieval_text"
            )
        multi, _ = embedder.encode_text(text, prefix="search_document: ")
        structs.append(
            models.PointStruct(
                id=int(pt["id"]),
                vector=multi.tolist(),
                payload={
                    "iri": pt.get("iri"),
                    "code": _code_from_path(pt),
                    "pref_label": pt.get("label") or "",
                    "local_name": (pt.get("iri") or "").rsplit("#", 1)[-1],
                    "retrieval_tokens": int(pt.get("retrieval_tokens") or 0),
                },
            )
        )
    client.upsert(collection_name=aperture.collection, points=structs)
    return {
        "collection": aperture.collection,
        "points": len(structs),
        "dim": dim,
        "encoder": ZERO_MODEL,
        "tau": aperture.tau,
    }


def _code_from_path(pt: dict[str, Any]) -> str:
    iri = str(pt.get("iri") or "")
    for c in pt.get("constituents") or []:
        if c.get("iri") == iri and c.get("code"):
            return str(c["code"])
    cons = pt.get("constituents") or []
    if cons and cons[0].get("code"):
        return str(cons[0]["code"])
    return ""


def v2_offsets(text: str) -> list[tuple[int, int]]:
    """Char spans from ColBERT-Zero tokenizer (512 grain)."""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(ZERO_MODEL)
    enc = tok(
        text,
        truncation=False,
        return_offsets_mapping=True,
        add_special_tokens=False,
    )
    return [(int(a), int(b)) for a, b in enc["offset_mapping"] if b > a]


def _default_device() -> str:
    """YK leftover GPU for ColBERT. Never thinking's cuda:0."""
    from gaius.engine.sentinel_claim import embedding_cuda_device

    return embedding_cuda_device()


def maxsim_window(
    text: str,
    *,
    aperture: SdgAperture | None = None,
    embedder: Any | None = None,
) -> tuple[str, float]:
    """Top-1 MaxSim vs C. Empty code if below τ (caller still sees the score)."""
    from qdrant_client import models

    aperture = aperture or SdgAperture.load()
    client = _qdrant()
    if not client.collection_exists(aperture.collection):
        raise RuntimeError(
            f"{GURU_NOMAXSIM}\n  collection={aperture.collection!r} "
            f"not on {QDRANT_HOST}:{QDRANT_PORT}"
        )
    enc = embedder or _zero()
    multi, _ = enc.encode_text(text, prefix="search_query: ")
    exclude = _exclude_codes(aperture)
    flt = None
    if exclude:
        flt = models.Filter(
            must_not=[
                models.FieldCondition(
                    key="code", match=models.MatchAny(any=sorted(exclude))
                )
            ]
        )
    hits = client.query_points(
        collection_name=aperture.collection,
        query=multi.tolist(),
        limit=3,
        query_filter=flt,
        with_payload=True,
    ).points
    if not hits:
        return "", 0.0
    top = hits[0]
    payload = top.payload or {}
    code = str(payload.get("local_name") or payload.get("pref_label") or "")
    raw = float(top.score)
    n_tok = max(1, int(multi.shape[0]))
    score = raw / n_tok
    if score < aperture.tau:
        return "", score
    return code, score


def unique_maxsim_window(
    text: str,
    *,
    aperture: SdgAperture | None = None,
    embedder: Any | None = None,
) -> tuple[str, float, str]:
    """Admit iff exactly one C point scores >= tau (Aegir unique-domain)."""
    from qdrant_client import models

    from gaius.engine.services.axis_admit import unique_topic

    aperture = aperture or SdgAperture.load()
    client = _qdrant()
    if not client.collection_exists(aperture.collection):
        raise RuntimeError(
            f"{GURU_NOMAXSIM}\n  collection={aperture.collection!r} "
            f"not on {QDRANT_HOST}:{QDRANT_PORT}"
        )
    enc = embedder or _zero()
    multi, _ = enc.encode_text(text, prefix="search_query: ")
    exclude = _exclude_codes(aperture)
    flt = None
    if exclude:
        flt = models.Filter(
            must_not=[
                models.FieldCondition(
                    key="code", match=models.MatchAny(any=sorted(exclude))
                )
            ]
        )
    hits = client.query_points(
        collection_name=aperture.collection,
        query=multi.tolist(),
        limit=2,
        query_filter=flt,
        with_payload=True,
    ).points
    n_tok = max(1, int(multi.shape[0]))
    ranked: list[tuple[str, float]] = []
    for h in hits:
        payload = h.payload or {}
        code = str(payload.get("local_name") or payload.get("pref_label") or "")
        ranked.append((code, float(h.score) / n_tok))
    return unique_topic(ranked, aperture.tau)


@lru_cache(maxsize=1)
def live_maxsim() -> Any:
    """Callable for scan_windows; materializes C if missing."""
    aperture = SdgAperture.load()
    client = _qdrant()
    if not client.collection_exists(aperture.collection):
        materialize_aperture(aperture)
    enc = _zero()

    def _fn(chunk: str) -> tuple[str, float]:
        return maxsim_window(chunk, aperture=aperture, embedder=enc)

    return _fn
