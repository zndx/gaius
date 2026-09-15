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


def materialize_tbox(*, device: str | None = None) -> dict[str, Any]:
    """Encode each TBox class verbalization into ``sdg_tbox``."""
    from qdrant_client import models

    records = class_verbalizations(certified_ontology_path())
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
        if not text:
            continue
        multi, _ = embedder.encode_text(text, prefix="search_document: ")
        structs.append(
            models.PointStruct(
                id=_point_id(rec.iri),
                vector=multi.tolist(),
                payload={"iri": rec.iri, "label": rec.label},
            )
        )
    client.upsert(collection_name=COLLECTION, points=structs)
    return {
        "collection": COLLECTION,
        "points": len(structs),
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
    client = _qdrant()
    if not client.collection_exists(COLLECTION):
        materialize_tbox()
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
    client = _qdrant()
    if not client.collection_exists(COLLECTION):
        materialize_tbox()
    enc = _zero()

    def _fn(chunk: str, k: int = 8) -> list[tuple[str, float]]:
        return maxsim_tbox_topk(chunk, k=k, embedder=enc)

    return _fn
