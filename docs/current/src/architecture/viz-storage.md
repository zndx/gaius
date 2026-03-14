# Viz Storage

Rendered card visualizations are stored in Cloudflare R2 and served from a public URL. The storage layer handles upload, database updates, and KV sync for live site pages.

## R2 Bucket

| Property | Value |
|----------|-------|
| Bucket name | `gaius-viz` |
| Public URL | `https://viz.gaius.zndx.org` |

## Object Key Convention

Rendered images follow a predictable path structure:

```
viz/cards/{card_id}/{variant}.png
```

For example:

```
viz/cards/abc123/display.png
viz/cards/abc123/og.png
```

## Variants

Each card is rendered in two variants:

| Variant | Dimensions | Purpose |
|---------|-----------|---------|
| `display` | 1400x300 | Card header image on the site |
| `og` | 1200x630 | OpenGraph image for social sharing |

## Database Integration

The `image_url` column in the cards table stores the display variant URL:

```
https://viz.gaius.zndx.org/viz/cards/{card_id}/display.png
```

The OG variant URL is derived by path convention -- replace `display.png` with `og.png`. There is no separate database column for the OG URL.

## Upload Flow

After the [LuxCore renderer](./luxcore.md) produces an image, the storage module (`gaius.viz.storage`) handles:

1. **R2 upload** -- uploads both display and OG variants to the bucket
2. **DB update** -- sets the `image_url` column on the card row
3. **KV sync** -- updates Cloudflare KV stores used by the live card pages

```python
# Simplified upload path
await upload_to_r2(card_id, display_bytes, "display")
await upload_to_r2(card_id, og_bytes, "og")
await update_card_image_url(card_id, display_url)
await sync_kv(card_id)
```

## CLI Access

```bash
# Render cards for a collection
uv run gaius-cli --cmd "/render collection-id"

# The render command handles the full pipeline:
# grammar expansion -> LuxCore render -> R2 upload -> DB update -> KV sync
```

## GPU Eviction

Rendering requires GPU access, but vLLM typically occupies all GPUs. The render workload requests GPU eviction via `allow_baseline_eviction=True` in the gRPC workload metadata. After rendering completes, `clear_embeddings()` releases the Nomic embedding model (~3GB) from GPU memory. See [Visualization](./visualization.md) for the full pipeline context.
