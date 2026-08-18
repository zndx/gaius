"""ACP-gated SKOS alignment. Does not admit or extract.

Ambiguous cases only: a CLT concept whose admitted evidence spans more
than one SDG aperture code, or whose logits do not mention that code.
Cadence: at most ``MAX_ACP`` prompts per run. No GitHub issues.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from gaius.acp.security import sanitize_issue_content
from gaius.engine.services.clt_skos_propose import CONCEPT_NS

MAX_ACP = 3
GURU_PARSE = (
    "ACP alignment reply was not JSON.\n"
    "  Guru: #CLT.00000011.ACPJSON"
)

# SKOS mapping + hierarchical properties. Do not shrink this to the
# relations a given prompt happens to demand — broader into SDG is valid.
_VERDICTS = frozenset({
    "broader",
    "narrower",
    "related",
    "relatedMatch",
    "closeMatch",
    "exactMatch",
    "broadMatch",
    "narrowMatch",
    "none",
    "pending",
})


@dataclass
class AmbiguousCase:
    layer: int
    feature_idx: int
    clt_uri: str
    notation: str
    pref_label: str
    codes: list[str]
    item_ids: list[int]
    logits: list[str]
    span_glosss: list[str]


async def find_ambiguous(pool: Any, *, limit: int = 8) -> list[AmbiguousCase]:
    """CLT features whose evidence items carry more than one aperture code."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.layer, a.feature_idx,
                   array_agg(DISTINCT i.aperture_code) AS codes,
                   array_agg(DISTINCT i.id) AS item_ids
              FROM activation a
              JOIN admitted_item i ON i.id = a.item_id
             WHERE a.model = 'clt'
               AND i.aperture_code <> ''
             GROUP BY 1, 2
            HAVING count(DISTINCT i.aperture_code) > 1
             ORDER BY count(DISTINCT i.id) DESC
             LIMIT $1
            """,
            limit,
        )
    out: list[AmbiguousCase] = []
    for r in rows:
        layer, feat = int(r["layer"]), int(r["feature_idx"])
        out.append(
            AmbiguousCase(
                layer=layer,
                feature_idx=feat,
                clt_uri=f"{CONCEPT_NS}L{layer}F{feat}",
                notation=f"{layer}:{feat}",
                pref_label="",
                codes=sorted(c for c in (r["codes"] or []) if c),
                item_ids=[int(x) for x in (r["item_ids"] or [])],
                logits=[],
                span_glosss=[],
            )
        )
    return out


async def attach_evidence(pool: Any, case: AmbiguousCase) -> AmbiguousCase:
    """Fill logits/gloss from contrib TTL + a few grounded spans."""
    from gaius.engine.services.clt_skos_propose import _read_logits, load_pref_labels

    labels = load_pref_labels()
    case.pref_label = labels.get(case.notation, f"L{case.layer} F{case.feature_idx}")
    case.logits = _read_logits(case.layer, case.feature_idx)
    async with pool.acquire() as conn:
        spans = await conn.fetch(
            """
            SELECT i.text, a.span_start, a.span_end, i.aperture_code
              FROM activation a
              JOIN admitted_item i ON i.id = a.item_id
             WHERE a.model = 'clt'
               AND a.layer = $1 AND a.feature_idx = $2
               AND a.span_end > a.span_start
             ORDER BY a.activation DESC
             LIMIT 4
            """,
            case.layer,
            case.feature_idx,
        )
    gloss = []
    for s in spans:
        frag = (s["text"] or "")[int(s["span_start"]) : int(s["span_end"])]
        if frag.strip():
            gloss.append(f"{s['aperture_code']}: {frag.strip()[:80]}")
    case.span_glosss = gloss
    return case


def build_align_prompt(case: AmbiguousCase) -> str:
    sdg = [f"https://signals.zndx.org/sdg#{c}" for c in case.codes]
    raw = (
        "You align CLT activation concepts to the SDG SKOS scheme.\n"
        "The two schemes stay distinct ConceptSchemes. Relate them with any "
        "SKOS property that fits the evidence (broader, narrower, related, "
        "relatedMatch, closeMatch, exactMatch, broadMatch, narrowMatch). "
        "Do not refuse a relation because it was not demanded.\n"
        "Reply with ONLY JSON: "
        '{"match":"relatedMatch|closeMatch|exactMatch|broader|narrower|'
        'related|broadMatch|narrowMatch|none","sdg_uri":"","reason":""}.\n'
        f"CLT concept: {case.clt_uri}\n"
        f"notation: {case.notation}\n"
        f"prefLabel: {case.pref_label}\n"
        f"top_logits: {case.logits}\n"
        f"admitted as: {case.codes}\n"
        f"candidate SDG URIs: {sdg}\n"
        f"grounded spans: {case.span_glosss}\n"
    )
    return sanitize_issue_content(raw)


def parse_align_reply(text: str) -> dict[str, str]:
    blob = text.strip()
    m = re.search(r"\{.*\}", blob, re.S)
    if not m:
        raise ValueError(GURU_PARSE)
    data = json.loads(m.group(0))
    match = str(data.get("match") or "none").strip()
    if match.startswith("skos:"):
        match = match[5:]
    if match not in _VERDICTS:
        raise ValueError(f"{GURU_PARSE}\n  match={match!r}")
    return {
        "match": match,
        "sdg_uri": str(data.get("sdg_uri") or ""),
        "reason": str(data.get("reason") or "")[:500],
    }


async def record_alignment(
    pool: Any,
    *,
    clt_uri: str,
    sdg_uri: str,
    match_kind: str,
    verdict: str,
    reason: str,
    item_ids: list[int],
    run_id: str,
) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO skos_alignment
                (clt_uri, sdg_uri, match_kind, verdict, reason, item_ids, run_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            clt_uri,
            sdg_uri,
            match_kind,
            verdict,
            reason,
            item_ids,
            run_id,
        )
    return int(row["id"])


async def run_acp_align(
    pool: Any,
    *,
    run_id: str,
    max_cases: int = MAX_ACP,
) -> dict[str, Any]:
    from gaius.acp import ACPConnectionError, GaiusACPClient

    cases = await find_ambiguous(pool, limit=max_cases)
    if not cases:
        return {"cases": 0, "aligned": 0, "pending": 0}

    aligned = 0
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
                match_kind="",
                verdict="pending",
                reason=f"#ACP.00000001.CONNFAIL {e}",
                item_ids=case.item_ids,
                run_id=run_id,
            )
            pending += 1
        return {"cases": len(cases), "aligned": 0, "pending": pending}

    try:
        for case in cases[:max_cases]:
            case = await attach_evidence(pool, case)
            prompt = build_align_prompt(case)
            try:
                reply = await client.prompt(prompt, timeout=120.0)
                parsed = parse_align_reply(reply)
                await record_alignment(
                    pool,
                    clt_uri=case.clt_uri,
                    sdg_uri=parsed["sdg_uri"],
                    match_kind=parsed["match"],
                    verdict=parsed["match"],
                    reason=parsed["reason"],
                    item_ids=case.item_ids,
                    run_id=run_id,
                )
                aligned += 1
            except Exception as e:
                await record_alignment(
                    pool,
                    clt_uri=case.clt_uri,
                    sdg_uri="",
                    match_kind="",
                    verdict="pending",
                    reason=str(e)[:400],
                    item_ids=case.item_ids,
                    run_id=run_id,
                )
                pending += 1
    finally:
        await client.close()
    return {"cases": len(cases), "aligned": aligned, "pending": pending}
