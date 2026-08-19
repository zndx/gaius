"""Summary lineup Corpus section — admitted 512-token windows.

Virtual notes (like cognition thoughts). Seed is a standing summary of
the accumulating admitted corpus. Discover list items open
``corpus/inflow/<content_items.id>``; each MaxSim window is
``corpus/item/<admitted_item.id>``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from gaius.engine.services.clt_skos_propose import is_minted_pref_label, load_pref_labels
from gaius.engine.services.summary_lineup import LineupNote, SummaryLineupError, extract_links

GURU_NOCORPUSDB = (
    "Summary Corpus needs the engine database pool.\n"
    "  Guru: #WS.00000015.NOCORPUSDB\n"
    "  Try: /health fix postgres"
)
GURU_NOITEM = (
    "That admitted window is not in admitted_item.\n"
    "  Guru: #WS.00000016.NOCORPUS\n"
    "  Try: open it from Discover after MaxSim admit"
)
GURU_NOINFLOW = (
    "That inbound document is not in content_items.\n"
    "  Guru: #WS.00000017.NOINFLOW\n"
    "  Try: open it from the Discover list"
)
GURU_BADID = (
    "Corpus note id must be lens/corpus, corpus/item/<id>, or corpus/inflow/<id>.\n"
    "  Guru: #WS.00000018.BADCORPUS"
)

ITEM_RE = re.compile(r"^corpus/item/(\d+)$")
INFLOW_RE = re.compile(r"^corpus/inflow/([^/]+)$")
SEED_ID = "lens/corpus"


def parse_corpus_id(note_id: str) -> tuple[str, str]:
    """Return (kind, key) or ('', '')."""
    nid = (note_id or "").strip()
    if nid in (SEED_ID, "corpus"):
        return "seed", ""
    m = ITEM_RE.match(nid)
    if m:
        return "item", m.group(1)
    m = INFLOW_RE.match(nid)
    if m:
        return "inflow", m.group(1)
    return "", ""


def _iso(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _excerpt(text: str, n: int = 220) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _aperture_meta(code: str) -> tuple[str, str]:
    from gaius.engine.services.sdg_aperture import SdgAperture

    raw = (code or "").strip()
    if not raw:
        return "", ""
    ap = SdgAperture.load()
    hit = ap.resolve(raw)
    if hit:
        return hit.label or raw, hit.iri
    return raw, f"https://signals.zndx.org/sdg#{raw}"


def _position_line(code: str) -> str:
    from gaius.engine.services.sdg_catalog import SdgCatalog

    cat = SdgCatalog.load()
    key = code if code in cat else f"SDG.{code}"
    concept = cat.get(key) or cat.get(code)
    if concept is None:
        return ""
    chain = [concept.label or concept.code]
    parent = concept.parent_code
    seen: set[str] = set()
    while parent and parent not in seen:
        seen.add(parent)
        nxt = cat.get(parent)
        if nxt is None:
            chain.append(parent)
            break
        chain.append(nxt.label or nxt.code)
        parent = nxt.parent_code
    chain.reverse()
    return " → ".join(chain)


def _md_table(rows: list[tuple[str, str]]) -> str:
    lines = [
        "| skos property | value |",
        "| --- | --- |",
    ]
    for k, v in rows:
        if not v:
            continue
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _seed_body(
    *,
    n_items: int,
    n_sources: int,
    first: datetime | None,
    last: datetime | None,
    mix: list[tuple[str, int]],
    n_act: int,
    n_feat: int,
    n_minted: int,
    recent: list[tuple[int, str, str, str]],
    strategy_id: str,
    tau: float,
    grain: int,
    collection: str,
) -> str:
    span = ""
    if first and last:
        span = f"{_iso(first)[:10]} – {_iso(last)[:10]}"
    mix_txt = (
        " · ".join(f"{code or '—'} {n}" for code, n in mix)
        if mix
        else "none yet"
    )
    blurb = (
        f"{n_items} admitted 512-token window(s) from {n_sources} inbound "
        f"document(s){f' ({span})' if span else ''}. Aperture mix: {mix_txt}. "
        f"{n_act} window(s) have CLT activations ({n_feat} distinct features); "
        f"{n_minted} feature(s) carry a minted skos:prefLabel."
    )
    lines = [
        "# Corpus",
        "",
        "admitted-corpus",
        "",
        "**Corpus** — admitted 512-token windows from Gaius inbound "
        "(the CLT admission surface's unit of text).",
        "",
        f"> {blurb}",
        "",
        _md_table(
            [
                ("prefLabel", "Corpus"),
                ("notation", "corpus"),
                ("broader", "Knowledge"),
                ("strategy", strategy_id),
                ("collection", collection),
                ("τ", str(tau)),
                ("grain", f"{grain} tokens"),
            ]
        ),
        "",
        "**Admission role.** MaxSim against the aiming aperture. Windows that "
        "pass the threshold are `admitted_item` rows. CLT extract writes "
        "activation spans on those windows. Discover lists inbound documents; "
        "this section is the admitted corpus.",
        "",
        f"**Aperture mix.** {mix_txt}",
        "",
        "**Recent admissions.**",
        "",
    ]
    if not recent:
        lines.append("Empty — no admitted windows yet.")
    for iid, title, code, ex in recent:
        label = title or ex or f"item {iid}"
        lines.append(f"- [[corpus/item/{iid}|{label}]] · `{code}`")
    lines.append("")
    return "\n".join(lines)


def _item_body(
    *,
    iid: int,
    title: str,
    text: str,
    code: str,
    margin: float,
    char_start: int,
    char_end: int,
    source_id: str,
    features: list[tuple[str, str]],
    url: str,
) -> str:
    label, iri = _aperture_meta(code)
    pos = _position_line(code)
    feat_line = (
        " · ".join(f"{name} (`{notation}`)" for notation, name in features)
        if features
        else "none extracted yet"
    )
    display = title or _excerpt(text, 80) or f"Admitted window {iid}"
    lines = [
        f"# {display}",
        "",
        "admitted-item",
        "",
        f"**{display}** — an admitted 512-token window (the CLT admission "
        "surface's unit — see [[lens/corpus|Corpus]]).",
        "",
        f"> {_excerpt(text, 900)}",
        "",
        _md_table(
            [
                ("prefLabel", label or code),
                ("altLabel", code),
                ("notation", code),
                ("IRI", iri),
                ("source", source_id),
                ("span", f"{char_start}–{char_end}"),
                ("margin", f"{margin:.3f}"),
            ]
        ),
        "",
    ]
    if pos:
        lines.append(f"**Position.** {pos}")
        lines.append("")
    lines.append(f"**Activated features.** {feat_line}")
    lines.append("")
    lines.append(
        "**Admission role.** MaxSim-admitted 512-token window on Gaius inbound. "
        "ColBERT-Zero against `sdg_aperture`. This text is in the admission "
        "surface (point, not chord)."
    )
    lines.append("")
    lines.append(f"Inbound document: [[corpus/inflow/{source_id}|source]]")
    if url:
        lines.append("")
        lines.append(f"Origin: {url}")
    lines.append("")
    return "\n".join(lines)


def _inflow_body(
    *,
    cid: str,
    title: str,
    summary: str,
    url: str,
    source: str,
    windows: list[tuple[int, str, str]],
) -> str:
    display = title or f"Inbound {cid}"
    lines = [
        f"# {display}",
        "",
        "inbound-document",
        "",
        f"**{display}** — an inbound document. Admitted windows below are "
        "the corpus units (see [[lens/corpus|Corpus]]).",
        "",
    ]
    if summary:
        lines.append(f"> {_excerpt(summary, 600)}")
        lines.append("")
    rows = [
        ("prefLabel", display),
        ("source", source),
        ("inflow", cid),
    ]
    if url:
        rows.append(("url", url))
    lines.append(_md_table(rows))
    lines.append("")
    lines.append("**Admitted windows.**")
    lines.append("")
    if not windows:
        lines.append(
            "None yet — this document has not passed MaxSim into `admitted_item`."
        )
    for iid, code, ex in windows:
        lines.append(f"- [[corpus/item/{iid}|{ex or code or iid}]] · `{code}`")
    lines.append("")
    return "\n".join(lines)


async def build_corpus_index(
    db_pool: Any,
    window_label: str,
    cap: int,
) -> dict[str, object]:
    if db_pool is None:
        raise SummaryLineupError(GURU_NOCORPUSDB)
    from gaius.engine.services.sdg_aperture import SdgAperture

    ap = SdgAperture.load()
    minted_n = sum(1 for v in load_pref_labels().values() if is_minted_pref_label(v))
    async with db_pool.acquire() as conn:
        n_items = int(await conn.fetchval("SELECT count(*) FROM admitted_item") or 0)
        n_sources = int(
            await conn.fetchval("SELECT count(DISTINCT source_id) FROM admitted_item")
            or 0
        )
        first = await conn.fetchval("SELECT min(admitted_at) FROM admitted_item")
        last = await conn.fetchval("SELECT max(admitted_at) FROM admitted_item")
        mix_rows = await conn.fetch(
            """
            SELECT aperture_code AS code, count(*)::int AS n
              FROM admitted_item
             GROUP BY 1
             ORDER BY n DESC
            """
        )
        n_act = int(
            await conn.fetchval(
                "SELECT count(DISTINCT item_id) FROM activation WHERE model = 'clt'"
            )
            or 0
        )
        n_feat = int(
            await conn.fetchval(
                """
                SELECT count(*) FROM (
                  SELECT DISTINCT layer, feature_idx
                    FROM activation WHERE model = 'clt'
                ) s
                """
            )
            or 0
        )
        recent_rows = await conn.fetch(
            """
            SELECT id, aperture_code, text, source_id, admitted_at
              FROM admitted_item
             ORDER BY admitted_at DESC
             LIMIT $1
            """,
            cap,
        )
    mix = [(str(r["code"] or ""), int(r["n"])) for r in mix_rows]
    recent: list[tuple[int, str, str, str]] = []
    items: list[LineupNote] = []
    for r in recent_rows:
        iid = int(r["id"])
        ex = _excerpt(r["text"] or "", 72)
        title = ex or f"item {iid}"
        recent.append((iid, title, str(r["aperture_code"] or ""), ex))
        items.append(
            LineupNote(
                id=f"corpus/item/{iid}",
                title=title,
                body="",
                section="corpus",
                lens="knowledge",
                week=window_label,
                excerpt=ex,
                virtual=True,
            )
        )
    body = _seed_body(
        n_items=n_items,
        n_sources=n_sources,
        first=first,
        last=last,
        mix=mix,
        n_act=n_act,
        n_feat=n_feat,
        n_minted=minted_n,
        recent=recent,
        strategy_id=ap.strategy_id,
        tau=ap.tau,
        grain=ap.colbert_token_limit,
        collection=ap.collection,
    )
    seed = LineupNote(
        id=SEED_ID,
        title="Corpus",
        body=body,
        section="corpus",
        lens="knowledge",
        week=window_label,
        links=extract_links(body),
        virtual=True,
        excerpt=_excerpt(body),
    )
    return {
        "week": window_label,
        "landing_id": SEED_ID,
        "seed": seed,
        "items": items,
    }


async def load_corpus_note(db_pool: Any, note_id: str, *, week: str = "") -> LineupNote:
    kind, key = parse_corpus_id(note_id)
    if not kind:
        raise SummaryLineupError(GURU_BADID)
    if db_pool is None:
        raise SummaryLineupError(GURU_NOCORPUSDB)
    if kind == "seed":
        idx = await build_corpus_index(db_pool, week, 24)
        seed = idx["seed"]
        assert isinstance(seed, LineupNote)
        return seed
    if kind == "item":
        return await _load_item(db_pool, int(key), week)
    return await _load_inflow(db_pool, key, week)


async def _load_item(db_pool: Any, iid: int, week: str) -> LineupNote:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.source_id, a.char_start, a.char_end, a.text,
                   a.aperture_code, a.margin, a.admitted_at,
                   c.title, c.url
              FROM admitted_item a
              LEFT JOIN content_items c ON c.id::text = a.source_id
             WHERE a.id = $1
            """,
            iid,
        )
        if row is None:
            raise SummaryLineupError(GURU_NOITEM)
        feats = await conn.fetch(
            """
            SELECT DISTINCT layer, feature_idx
              FROM activation
             WHERE model = 'clt' AND item_id = $1
             ORDER BY layer, feature_idx
             LIMIT 24
            """,
            iid,
        )
    minted = load_pref_labels()
    features: list[tuple[str, str]] = []
    for f in feats:
        notation = f"{int(f['layer'])}:{int(f['feature_idx'])}"
        pref = minted.get(notation, "")
        if is_minted_pref_label(pref):
            features.append((notation, pref))
    title = str(row["title"] or "") or _excerpt(row["text"] or "", 80)
    body = _item_body(
        iid=iid,
        title=title,
        text=str(row["text"] or ""),
        code=str(row["aperture_code"] or ""),
        margin=float(row["margin"] or 0.0),
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        source_id=str(row["source_id"] or ""),
        features=features,
        url=str(row["url"] or ""),
    )
    created = row["admitted_at"]
    if created is not None and getattr(created, "tzinfo", None) is None:
        created = created.replace(tzinfo=timezone.utc)
    ms = int(created.timestamp() * 1000) if created else 0
    return LineupNote(
        id=f"corpus/item/{iid}",
        title=title,
        body=body,
        section="corpus",
        lens="knowledge",
        week=week,
        mtime_ms=ms,
        links=extract_links(body),
        origin_id=str(row["source_id"] or ""),
        excerpt=_excerpt(body),
        virtual=True,
    )


async def _load_inflow(db_pool: Any, cid: str, week: str) -> LineupNote:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.id::text AS cid, c.title, c.summary, c.url,
                   COALESCE(s.name, '') AS source
              FROM content_items c
              LEFT JOIN feed_sources s ON s.id = c.source_id
             WHERE c.id::text = $1
            """,
            cid,
        )
        if row is None:
            raise SummaryLineupError(GURU_NOINFLOW)
        wins = await conn.fetch(
            """
            SELECT id, aperture_code, text
              FROM admitted_item
             WHERE source_id = $1
             ORDER BY char_start
            """,
            cid,
        )
    windows = [
        (int(w["id"]), str(w["aperture_code"] or ""), _excerpt(w["text"] or "", 72))
        for w in wins
    ]
    title = str(row["title"] or "") or f"Inbound {cid}"
    body = _inflow_body(
        cid=cid,
        title=title,
        summary=str(row["summary"] or ""),
        url=str(row["url"] or ""),
        source=str(row["source"] or ""),
        windows=windows,
    )
    return LineupNote(
        id=f"corpus/inflow/{cid}",
        title=title,
        body=body,
        section="corpus",
        lens="knowledge",
        week=week,
        links=extract_links(body),
        origin_id=cid,
        excerpt=_excerpt(body),
        virtual=True,
    )
