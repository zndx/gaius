"""ACP-minted skos:prefLabel for CLT features.

Each feature is named from the admitted item text that fired it and that
feature's top_logits. Default ACP is grok-build on local thinking
(Qwen3.8-27B). Thinking must already be HEALTHY — Complete does not
cold-start vLLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from gaius.acp.security import sanitize_issue_content
from gaius.engine.services.clt_skos_propose import CONCEPT_NS

MAX_LABEL = 8
GURU_PARSE = (
    "ACP prefLabel reply was not JSON.\n"
    "  Guru: #CLT.00000012.PREFLABEL"
)
GURU_EMPTY = (
    "ACP prefLabel was empty or not a display phrase.\n"
    "  Guru: #CLT.00000013.PREFEMPTY"
)


@dataclass
class LabelCase:
    layer: int
    feature_idx: int
    notation: str
    clt_uri: str
    logits: list[str] = field(default_factory=list)
    items: list[dict[str, str]] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)


def _excerpt(text: str, start: int, end: int, *, radius: int = 140) -> str:
    lo = max(0, int(start) - radius)
    hi = min(len(text), int(end) + radius)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()[:400]


async def find_unlabeled(pool: Any, *, limit: int = 8) -> list[LabelCase]:
    """Features with admitted activations that still lack a minted prefLabel."""
    from gaius.engine.services.clt_skos_propose import is_minted_pref_label, load_pref_labels

    minted = {k for k, v in load_pref_labels().items() if is_minted_pref_label(v)}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.layer, a.feature_idx,
                   count(DISTINCT a.item_id)::int AS n,
                   array_agg(DISTINCT a.item_id) AS item_ids
              FROM activation a
             WHERE a.model = 'clt'
             GROUP BY 1, 2
             ORDER BY n DESC, a.layer, a.feature_idx
             LIMIT $1
            """,
            max(limit * 4, 16),
        )
    out: list[LabelCase] = []
    for r in rows:
        layer, feat = int(r["layer"]), int(r["feature_idx"])
        notation = f"{layer}:{feat}"
        if notation in minted:
            continue
        out.append(
            LabelCase(
                layer=layer,
                feature_idx=feat,
                notation=notation,
                clt_uri=f"{CONCEPT_NS}L{layer}F{feat}",
                item_ids=[int(x) for x in (r["item_ids"] or [])],
            )
        )
        if len(out) >= limit:
            break
    return out


async def attach_label_evidence(pool: Any, case: LabelCase) -> LabelCase:
    from gaius.engine.services.clt_skos_propose import _read_logits

    case.logits = _read_logits(case.layer, case.feature_idx)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.id, i.text, i.aperture_code, a.span_start, a.span_end, a.activation
              FROM activation a
              JOIN admitted_item i ON i.id = a.item_id
             WHERE a.model = 'clt'
               AND a.layer = $1 AND a.feature_idx = $2
               AND a.span_end > a.span_start
             ORDER BY a.activation DESC
             LIMIT 3
            """,
            case.layer,
            case.feature_idx,
        )
    items: list[dict[str, str]] = []
    ids: list[int] = []
    for r in rows:
        text = r["text"] or ""
        start, end = int(r["span_start"]), int(r["span_end"])
        items.append(
            {
                "aperture": str(r["aperture_code"] or ""),
                "span": text[start:end],
                "excerpt": _excerpt(text, start, end),
            }
        )
        ids.append(int(r["id"]))
    case.items = items
    if ids:
        case.item_ids = ids
    return case


def build_label_prompt(case: LabelCase) -> str:
    blocks = []
    for i, it in enumerate(case.items, 1):
        blocks.append(
            f"item {i} aperture={it.get('aperture','')} "
            f"span={it.get('span','')!r}\nexcerpt: {it.get('excerpt','')}"
        )
    body = "\n".join(blocks) if blocks else "(no grounded item text)"
    raw = (
        "Assign one skos:prefLabel for a CLT activation feature.\n"
        "The label is for faceted search over admitted items: a short noun "
        "phrase (2–5 words) a reader would click to explore this feature.\n"
        "Use the admitted item text and the feature's top_logits together. "
        "Think about how they relate, then name the feature.\n"
        "Reply with ONLY JSON: "
        '{"prefLabel":"","reason":""}.\n'
        f"notation: {case.notation}\n"
        f"top_logits: {case.logits}\n"
        f"{body}\n"
    )
    return sanitize_issue_content(raw)


def parse_label_reply(text: str) -> dict[str, str]:
    from gaius.engine.services.clt_skos_propose import is_minted_pref_label

    blob = text.strip()
    m = re.search(r"\{.*\}", blob, re.S)
    if not m:
        raise ValueError(GURU_PARSE)
    data = json.loads(m.group(0))
    label = re.sub(r"\s+", " ", str(data.get("prefLabel") or "").strip())
    label = label[:48]
    if label.startswith("skos:"):
        label = label[5:].strip()
    if not is_minted_pref_label(label):
        raise ValueError(f"{GURU_EMPTY}\n  prefLabel={label!r}")
    return {
        "prefLabel": label,
        "reason": str(data.get("reason") or "")[:400],
    }


async def run_acp_label(
    pool: Any,
    *,
    run_id: str,
    max_cases: int = MAX_LABEL,
) -> dict[str, Any]:
    from gaius.acp import GaiusACPClient
    from gaius.engine.services.clt_skos_align import record_alignment
    from gaius.engine.services.clt_skos_propose import set_pref_label

    cases = await find_unlabeled(pool, limit=max_cases)
    if not cases:
        return {"cases": 0, "labeled": 0, "pending": 0}

    labeled = 0
    pending = 0
    try:
        client = GaiusACPClient()
        await client.connect()
    except Exception as e:
        for case in cases:
            await record_alignment(
                pool,
                clt_uri=case.clt_uri,
                sdg_uri="",
                match_kind="prefLabel",
                verdict="pending",
                reason=f"#ACP.00000001.CONNFAIL {e}",
                item_ids=case.item_ids,
                run_id=run_id,
            )
            pending += 1
        return {"cases": len(cases), "labeled": 0, "pending": pending}

    try:
        for case in cases[:max_cases]:
            case = await attach_label_evidence(pool, case)
            prompt = build_label_prompt(case)
            try:
                reply = await client.prompt(prompt, timeout=180.0)
                parsed = parse_label_reply(reply)
                set_pref_label(case.notation, parsed["prefLabel"])
                await record_alignment(
                    pool,
                    clt_uri=case.clt_uri,
                    sdg_uri="",
                    match_kind="prefLabel",
                    verdict="labeled",
                    reason=parsed["reason"],
                    item_ids=case.item_ids,
                    run_id=run_id,
                )
                labeled += 1
            except Exception as e:
                await record_alignment(
                    pool,
                    clt_uri=case.clt_uri,
                    sdg_uri="",
                    match_kind="prefLabel",
                    verdict="pending",
                    reason=str(e)[:400],
                    item_ids=case.item_ids,
                    run_id=run_id,
                )
                pending += 1
    finally:
        await client.close()
    return {"cases": len(cases), "labeled": labeled, "pending": pending}
