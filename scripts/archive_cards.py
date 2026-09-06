#!/usr/bin/env python
"""Archive published cards WITH a declared reason — the only sanctioned way.

    .devenv/state/venv/bin/python scripts/archive_cards.py --reason 'duplicate: kept card_abc' card_x card_y
    .devenv/state/venv/bin/python scripts/archive_cards.py --reason 'adversarial: vendor listicle' --sync card_x

The reason's category (prefix before ':') must be one of
surface_integrity.REMOVAL_REASONS; it is written by the cards_content_events
trigger from `SET LOCAL gaius.content_reason` in the same transaction, so the
removal is EXPLAINED to the conservation aspect of `surface_integrity`.
--sync re-syncs the public KV afterwards (scripts/sync_public_kv.py).
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def _run(card_ids: list[str], reason: str, actor: str, sync: bool) -> int:
    import asyncpg

    from gaius.core.config import get_database_url
    from gaius.engine.services.surface_integrity import REMOVAL_REASONS

    cat = reason.split(":", 1)[0].strip().lower()
    if cat not in REMOVAL_REASONS or ":" not in reason:
        print(f"reason must be '<category>: <why>' with category in {REMOVAL_REASONS}; got {reason!r}", file=sys.stderr)
        return 64
    pool = await asyncpg.create_pool(get_database_url(), min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('gaius.content_reason', $1, true)", reason)
                await conn.execute("SELECT set_config('gaius.content_actor', $1, true)", actor)
                rows = await conn.fetch(
                    "UPDATE collections.cards SET status = 'archived', updated_at = NOW() "
                    "WHERE card_id = ANY($1::text[]) AND status = 'published' RETURNING card_id",
                    card_ids,
                )
        done = [r["card_id"] for r in rows]
        print(f"archived {len(done)}/{len(card_ids)} with reason {reason!r}: {' '.join(done)}")
        missing = sorted(set(card_ids) - set(done))
        if missing:
            print(f"not published (untouched): {' '.join(missing)}")
    finally:
        await pool.close()
    if sync and done:
        from subprocess import call
        return call([sys.executable, "scripts/sync_public_kv.py"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reason", required=True, help="'<category>: <why>' — duplicate|adversarial|license|retired|broken|operator")
    ap.add_argument("--actor", default="scripts/archive_cards.py")
    ap.add_argument("--sync", action="store_true", help="re-sync the public KV afterwards")
    ap.add_argument("card_ids", nargs="+")
    a = ap.parse_args()
    return asyncio.run(_run(a.card_ids, a.reason, a.actor, a.sync))


if __name__ == "__main__":
    raise SystemExit(main())
