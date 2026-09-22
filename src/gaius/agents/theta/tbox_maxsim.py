"""ColBERT-Zero MaxSim of admitted text against the full TBox class set.

Harvest ``sdg_aperture`` is aiming C (33 points). This collection is every
named class in the certified OWL. Same encoder, MAX_SIM comparator, 128-d.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Any

from gaius.agents.theta.tbox import class_verbalizations, certified_ontology_path

COLLECTION = "sdg_tbox"
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6339"))
ZERO_MODEL = "lightonai/ColBERT-Zero"
# Qdrant rejects one JSON body over 32MiB. 905 ColBERT multivectors are ~45MiB.
UPSERT_BATCH = 64
GURU_NOMAXSIM = (
    "#SDG.00000005.NOMAXSIM TBox MaxSim collection is required for consolidation grounding.\n"
    "  Materialize sdg_tbox via tbox_maxsim.materialize_tbox()."
)


def _zero(device: str | None = None):
    """ColBERT in THIS process. Callers must hold a LIGHT YK token
    (``own_gpu_application``); do not load from a COMPUTE child."""
    from gaius.engine.embeddings.colbert import get_colbert_embedder

    return get_colbert_embedder(device=device)


def _qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def _point_id(iri: str) -> int:
    return int(hashlib.sha1(iri.encode("utf-8")).hexdigest()[:15], 16)


def tbox_index_ready(client: Any, expected: int) -> bool:
    """An existing collection with zero points is not an index.

    ``materialize_tbox`` creates the collection before upsert. A 32MiB
    rejection used to leave ``sdg_tbox`` present and empty, and the next
    cycle treated that as ready.
    """
    if expected < 1 or not client.collection_exists(COLLECTION):
        return False
    try:
        got = int(client.count(COLLECTION).count or 0)
    except Exception:
        return False
    return got >= expected


def upsert_in_batches(
    client: Any, points: list[Any], *, batch_size: int = UPSERT_BATCH
) -> int:
    """Upsert multivectors under Qdrant's JSON body limit. Returns points sent."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    sent = 0
    for start in range(0, len(points), batch_size):
        chunk = points[start : start + batch_size]
        if not chunk:
            continue
        client.upsert(collection_name=COLLECTION, points=chunk)
        sent += len(chunk)
    return sent


def _indexable_verbalizations() -> list[Any]:
    return [
        rec
        for rec in class_verbalizations(certified_ontology_path())
        if rec.retrieval_text.strip()
    ]


def _ensure_tbox_index(*, device: str | None = None) -> None:
    expected = len(_indexable_verbalizations())
    client = _qdrant()
    if tbox_index_ready(client, expected):
        return
    materialize_tbox(device=device)


def materialize_tbox(*, device: str | None = None) -> dict[str, Any]:
    """Encode each TBox class verbalization into ``sdg_tbox``."""
    from qdrant_client import models

    records = _indexable_verbalizations()
    if not records:
        raise RuntimeError(f"{GURU_NOMAXSIM}\n  certified OWL has no named classes")
    embedder = _zero(device)
    client = _qdrant()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(
            size=embedder.embedding_dim,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
        ),
    )
    structs = []
    for rec in records:
        text = rec.retrieval_text.strip()
        multi, _ = embedder.encode_text(text, prefix="search_document: ")
        structs.append(
            models.PointStruct(
                id=_point_id(rec.iri),
                vector=multi.tolist(),
                payload={"iri": rec.iri, "label": rec.label},
            )
        )
    written = upsert_in_batches(client, structs)
    return {
        "collection": COLLECTION,
        "points": written,
        "dim": embedder.embedding_dim,
        "encoder": ZERO_MODEL,
    }


def maxsim_tbox_topk(
    text: str,
    *,
    k: int = 8,
    embedder: Any | None = None,
) -> list[tuple[str, float]]:
    """Top-k TBox class IRIs for this text. No harvest-τ filter (C is not the TBox)."""
    if not (text or "").strip() or k < 1:
        return []
    _ensure_tbox_index()
    client = _qdrant()
    enc = embedder or _zero()
    multi, _ = enc.encode_text(text, prefix="search_query: ")
    hits = client.query_points(
        collection_name=COLLECTION,
        query=multi.tolist(),
        limit=k,
        with_payload=True,
    ).points
    n_tok = max(1, int(multi.shape[0]))
    out: list[tuple[str, float]] = []
    for h in hits:
        payload = h.payload or {}
        iri = str(payload.get("iri") or "")
        if not iri:
            continue
        out.append((iri, float(h.score) / n_tok))
    return out


@lru_cache(maxsize=1)
def live_tbox_maxsim() -> Any:
    _ensure_tbox_index()
    enc = _zero()

    def _fn(chunk: str, k: int = 8) -> list[tuple[str, float]]:
        return maxsim_tbox_topk(chunk, k=k, embedder=enc)

    return _fn
