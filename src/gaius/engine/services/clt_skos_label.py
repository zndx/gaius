"""Mint skos:prefLabel for CLT features via Engine/Complete thinking.

Each feature is named from the admitted item text that fired it and that
feature's top_logits. Qwen3.8-27B (capability=thinking) does the naming.
Thinking must already be HEALTHY — Complete does not cold-start vLLM.
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
    """Tape-hot features that lack a fresh minted prefLabel (or are stale)."""
    from gaius.engine.services.clt_skos_propose import is_minted_pref_label, load_pref_labels

    from gaius.engine.services.clt_skos_propose import _read_logits, is_admin_logits

    minted = {k for k, v in load_pref_labels().items() if is_minted_pref_label(v)}
    async with pool.acquire() as conn:
        stale = {
            str(r["notation"])
            for r in await conn.fetch(
                "SELECT notation FROM skos_pref_label WHERE stale"
            )
        }
        tape = await conn.fetch(
            """
            SELECT layer, feature_idx, count(*)::int AS n
              FROM feature_tape
             GROUP BY 1, 2
             ORDER BY count(*) * avg(activation) DESC
             LIMIT $1
            """,
            max(limit * 8, 40),
        )
    out: list[LabelCase] = []
    for r in tape:
        layer, feat = int(r["layer"]), int(r["feature_idx"])
        notation = f"{layer}:{feat}"
        if notation in minted and notation not in stale:
            continue
        if is_admin_logits(_read_logits(layer, feat)):
            continue
        async with pool.acquire() as conn:
            ids = await conn.fetch(
                """
                SELECT DISTINCT item_id
                  FROM activation
                 WHERE model = 'clt' AND layer = $1 AND feature_idx = $2
                 LIMIT 8
                """,
                layer,
                feat,
            )
        if not ids:
            continue
        out.append(
            LabelCase(
                layer=layer,
                feature_idx=feat,
                notation=notation,
                clt_uri=f"{CONCEPT_NS}L{layer}F{feat}",
                item_ids=[int(x["item_id"]) for x in ids],
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
        "Think about how they relate, then name the feature as it appears "
        "in the admitted aperture content. Do not name HTML, CSS, "
        "punctuation, or other document machinery.\n"
        "Do not call tools. After thinking, reply with only a JSON object "
        "whose prefLabel is the noun phrase and whose reason is one sentence.\n"
        f"notation: {case.notation}\n"
        f"top_logits: {case.logits}\n"
        f"{body}\n"
    )
    return sanitize_issue_content(raw)


def parse_label_reply(text: str) -> dict[str, str]:
    from gaius.engine.services.clt_skos_propose import (
        is_admin_pref_label,
        is_minted_pref_label,
    )

    blob = text.strip()
    m = re.search(r"\{.*\}", blob, re.S)
    data: dict[str, Any] = {}
    if m:
        raw_json = m.group(0)
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', raw_json)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                data = {}
    if not data.get("prefLabel"):
        km = re.search(r"prefLabel['\"]?\s*:\s*['\"]([^'\"]+)['\"]", blob)
        if km:
            data["prefLabel"] = km.group(1)
    label = re.sub(r"\s+", " ", str(data.get("prefLabel") or "").strip())
    label = label[:48]
    if label.startswith("skos:"):
        label = label[5:].strip()
    if label.lower() in {"example phrase", "noun phrase", "pref label", "label"}:
        label = ""
    if is_admin_pref_label(label):
        label = ""
    if not is_minted_pref_label(label):
        raise ValueError(f"{GURU_EMPTY}\n  prefLabel={label!r}")
    return {
        "prefLabel": label,
        "reason": str(data.get("reason") or "")[:400],
    }


_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "prefLabel": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["prefLabel"],
}


def _thinking_label(prompt: str) -> tuple[str, str]:
    from gaius.flows.lattice import complete

    got = complete(
        prompt,
        capability="thinking",
        max_tokens=2048,
        temperature=0.3,
        json_schema=_LABEL_SCHEMA,
        timeout_s=600.0,
    )
    text = (got.text or "") + ("\n" + got.reasoning_content if got.reasoning_content else "")
    return text, str(got.model or "")


async def run_acp_label(
    pool: Any,
    *,
    run_id: str,
    max_cases: int = MAX_LABEL,
    task_id: int = 0,
) -> dict[str, Any]:
    import asyncio

    from gaius.engine.services.clt_skos_align import record_alignment
    from gaius.engine.services.clt_skos_clock import (
        current_exemplars,
        ensure_clock,
        exemplar_hash,
        mark_clock_started,
        mark_stale_labels,
        upsert_pref_label,
        write_task_run_id,
    )
    from gaius.engine.services.clt_skos_propose import set_pref_label

    await ensure_clock(pool)
    await write_task_run_id(pool, task_id, run_id)
    await mark_clock_started(pool, "label", run_id)
    stale_n = await mark_stale_labels(pool)
    cases = await find_unlabeled(pool, limit=max_cases)
    if not cases:
        return {"cases": 0, "labeled": 0, "pending": 0, "stale": stale_n, "run_id": run_id}

    labeled = 0
    pending = 0
    for case in cases[:max_cases]:
        case = await attach_label_evidence(pool, case)
        prompt = build_label_prompt(case)
        try:
            reply, model = await asyncio.to_thread(_thinking_label, prompt)
            parsed = parse_label_reply(reply)
            set_pref_label(case.notation, parsed["prefLabel"])
            exemplars = await current_exemplars(pool, case.layer, case.feature_idx)
            await upsert_pref_label(
                pool,
                notation=case.notation,
                pref_label=parsed["prefLabel"],
                clt_uri=case.clt_uri,
                labeler_model=model,
                labeler_version=model,
                exemplar_hash_s=exemplar_hash(exemplars),
                item_ids=[t[0] for t in exemplars] or case.item_ids,
                run_id=run_id,
            )
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
                verdict="error",
                reason=str(e)[:400],
                item_ids=case.item_ids,
                run_id=run_id,
            )
            raise
    return {
        "cases": len(cases),
        "labeled": labeled,
        "pending": pending,
        "stale": stale_n,
        "run_id": run_id,
    }


async def pref_label_health(pool: Any, *, top: int = 20) -> dict[str, Any]:
    """Tape-hot non-admin features vs minted display prefLabels.

    Healthy Gaius: Discover landing shows a meaningful set of names.
    empty = 0 names; thin = <5; ok = ≥5.
    """
    from gaius.engine.services.clt_skos_propose import (
        _read_logits,
        is_admin_logits,
        is_minted_pref_label,
        load_pref_labels,
    )

    minted = load_pref_labels()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT layer, feature_idx, count(*)::int AS n
              FROM feature_tape
             GROUP BY 1, 2
             ORDER BY count(*) * avg(activation) DESC
             LIMIT $1
            """,
            top * 3,
        )
    eligible: list[str] = []
    named: list[dict[str, Any]] = []
    for r in rows:
        layer, feat = int(r["layer"]), int(r["feature_idx"])
        if is_admin_logits(_read_logits(layer, feat)):
            continue
        notation = f"{layer}:{feat}"
        eligible.append(notation)
        pref = minted.get(notation, "")
        if is_minted_pref_label(pref):
            named.append({"notation": notation, "prefLabel": pref, "n": int(r["n"])})
        if len(eligible) >= top:
            break
    n_named = len(named)
    n_el = len(eligible)
    if n_named >= 5:
        status = "ok"
    elif n_named >= 1:
        status = "thin"
    else:
        status = "empty"
    return {
        "status": status,
        "eligible": n_el,
        "named": n_named,
        "labels": named,
        "unlabeled": [n for n in eligible if n not in {x["notation"] for x in named}],
    }
