#!/usr/bin/env python
"""Re-sync the public Cloudflare KV surface from Postgres without publishing.

`publish_and_sync` publishes THEN syncs; there was no way to push a
status change (archive) to the landing page without also publishing. This
runs the same three syncs the curation flow runs after `publish_batch`
(`sync_to_kv`, per-collection `sync_collection_to_kv`,
`sync_collections_index_to_kv`) and nothing else.

    .devenv/state/venv/bin/python scripts/sync_public_kv.py [--collections col_a col_b]

Without --collections every active collection is synced.
"""

from __future__ import annotations

import argparse
import asyncio


async def _run(collection_ids: list[str]) -> int:
    import asyncpg

    from gaius.core.config import get_database_url
    from gaius.engine.services.collection_service import CollectionService

    async with asyncpg.create_pool(get_database_url(), min_size=1, max_size=3) as pool:
        service = CollectionService(pool)
        res = await service.sync_to_kv()
        print(f"sync_to_kv: {res.get('cards_synced', 0)} cards in published_cards")
        if not collection_ids:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT collection_id FROM collections.collections WHERE status = 'active' ORDER BY collection_id"
                )
            collection_ids = [str(r["collection_id"]) for r in rows]
        for cid in collection_ids:
            r = await service.sync_collection_to_kv(cid)
            print(f"sync_collection_to_kv {cid}: {r.get('cards_synced', 0)} cards")
        idx = await service.sync_collections_index_to_kv()
        print(f"sync_collections_index_to_kv: {idx.get('collections_synced', 0)} collections")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--collections", nargs="*", default=[], help="collection ids (default: all active)")
    args = ap.parse_args()
    return asyncio.run(_run(list(args.collections)))


if __name__ == "__main__":
    raise SystemExit(main())
