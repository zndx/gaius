#!/usr/bin/env bash
# backfill_card_images.sh — Render card visualizations and push to live app.
#
# Renders cards that are missing image_url, uploads to R2, and syncs
# to Cloudflare KV so the images appear on the live site.
#
# Usage:
#   ./scripts/backfill_card_images.sh              # Render 5 cards (default sample)
#   ./scripts/backfill_card_images.sh 10            # Render 10 cards
#   ./scripts/backfill_card_images.sh --collection ai-reasoning-agents
#   ./scripts/backfill_card_images.sh --all         # Render ALL cards missing images
#   ./scripts/backfill_card_images.sh --dry-run     # Show what would be rendered
#
# Prerequisites:
#   - Engine running: devenv processes up -d
#   - Both endpoints HEALTHY: uv run gaius-cli --cmd "/gpu status"
#   - R2 credentials set: CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY
#
# What happens:
#   1. Shows current card/image stats
#   2. Renders cards via /render (evicts vLLM, runs Blender, restores vLLM)
#   3. Syncs updated cards to Cloudflare KV
#   4. Prints live URLs for visual verification

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

SAMPLE_SIZE=5
COLLECTION=""
DRY_RUN=false
FORCE=false

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --collection|-c)
            COLLECTION="$2"; shift 2 ;;
        --all)
            SAMPLE_SIZE=0; shift ;;
        --dry-run)
            DRY_RUN=true; shift ;;
        --force)
            FORCE=true; shift ;;
        --help|-h)
            head -18 "$0" | tail -16; exit 0 ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                SAMPLE_SIZE="$1"
            fi
            shift ;;
    esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────

echo "=== Card Image Backfill ==="
echo ""

# Check engine is running
if ! nc -zw2 localhost 50051 2>/dev/null; then
    echo "ERROR: Engine not running on port 50051"
    echo "  Fix: devenv processes up -d && just restart-clean"
    exit 1
fi

# Check endpoints (2>/dev/null strips metaflow log line, leaving pure JSON)
echo "Checking endpoint health..."
UNHEALTHY=$(uv run gaius-cli --cmd "/gpu status" --format json 2>/dev/null \
    | jq -r '[.data.endpoints[]? | select(.status != "PROCESS_STATUS_HEALTHY") | .name] | join(",")' 2>/dev/null)

if [[ -n "$UNHEALTHY" ]]; then
    echo "WARNING: Unhealthy endpoints: $UNHEALTHY"
    echo "  Rendering will still proceed (it evicts endpoints anyway)"
    echo ""
fi

# ── Stats ─────────────────────────────────────────────────────────────────────

echo "Current card image stats:"
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius -t -A -F'|' -c "
    SELECT col.slug,
           COUNT(c.card_id),
           COUNT(c.image_url) FILTER (WHERE c.image_url IS NOT NULL AND c.image_url != ''),
           COUNT(*) FILTER (WHERE c.image_url IS NULL OR c.image_url = '')
    FROM collections.cards c
    JOIN collections.collections col ON c.collection_id = col.collection_id
    WHERE c.status = 'published'
    GROUP BY col.slug ORDER BY col.slug
" 2>/dev/null | while IFS='|' read -r slug total has needs; do
    printf "  %-25s %3d published, %3d with images, %3d need rendering\n" "$slug" "$total" "$has" "$needs"
done

TOTAL_NEEDS=$(PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius -t -A -c "
    SELECT COUNT(*) FROM collections.cards
    WHERE status = 'published' AND (image_url IS NULL OR image_url = '')
" 2>/dev/null)
echo ""
echo "Total cards needing images: $TOTAL_NEEDS"
echo ""

if [[ "$TOTAL_NEEDS" == "0" ]]; then
    echo "All published cards have images. Nothing to do."
    echo "Use --force to re-render existing images."
    if [[ "$FORCE" != "true" ]]; then
        exit 0
    fi
fi

# ── Dry Run ───────────────────────────────────────────────────────────────────

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] Would render:"
    if [[ "$SAMPLE_SIZE" -gt 0 ]]; then
        echo "  $SAMPLE_SIZE random cards (from ${COLLECTION:-all collections})"
    else
        echo "  All $TOTAL_NEEDS cards missing images"
    fi
    exit 0
fi

# ── Render ────────────────────────────────────────────────────────────────────

RENDER_ARGS=""
if [[ "$SAMPLE_SIZE" -gt 0 ]]; then
    RENDER_ARGS="--sample $SAMPLE_SIZE"
    echo "Rendering $SAMPLE_SIZE card(s)..."
else
    echo "Rendering all $TOTAL_NEEDS card(s) missing images..."
fi

if [[ -n "$COLLECTION" ]]; then
    RENDER_ARGS="$RENDER_ARGS --collection $COLLECTION"
fi

if [[ "$FORCE" == "true" ]]; then
    RENDER_ARGS="$RENDER_ARGS --force"
fi

echo "Running: /render $RENDER_ARGS"
echo ""

# Capture render output — the /render command prints streaming progress
# lines to stdout followed by a JSON result.
RENDER_TMPFILE=$(mktemp)
trap "rm -f $RENDER_TMPFILE" EXIT
uv run gaius-cli --cmd "/render $RENDER_ARGS" --format json >"$RENDER_TMPFILE" 2>/dev/null

# Show progress lines (non-JSON lines starting with [)
grep '^\[' "$RENDER_TMPFILE" || true
echo ""

# Extract the JSON result (skip progress lines, parse from first { onward)
RENDER_JSON=$(sed -n '/^{/,$p' "$RENDER_TMPFILE")

if [[ -z "$RENDER_JSON" ]]; then
    echo "ERROR: Could not parse render output"
    cat "$RENDER_TMPFILE"
    exit 1
fi

SUCCESS=$(echo "$RENDER_JSON" | jq -r '.data.success // false' 2>/dev/null)
CARDS_DONE=$(echo "$RENDER_JSON" | jq -r '.data.cards_done // 0' 2>/dev/null)
DURATION=$(echo "$RENDER_JSON" | jq -r '.data.duration_ms // 0' 2>/dev/null)

if [[ "$SUCCESS" != "true" ]]; then
    echo "ERROR: Render failed"
    echo "$RENDER_JSON" | jq . 2>/dev/null
    exit 1
fi

echo "Rendered $CARDS_DONE card(s) in $((DURATION / 1000))s"
echo ""

# ── KV Sync ───────────────────────────────────────────────────────────────────
# /publish cards -N 1 publishes up to 1 pending card AND syncs ALL published
# cards (including newly-updated image_url values) to Cloudflare KV.
# If no pending cards exist, 0 get published but the KV sync still runs.

echo "Syncing updated cards to Cloudflare KV..."
SYNC_JSON=$(uv run gaius-cli --cmd "/publish cards -N 1" --format json 2>/dev/null)

if [[ -n "$SYNC_JSON" ]]; then
    SYNC_ERR=$(echo "$SYNC_JSON" | jq -r '.data.error // empty' 2>/dev/null)
    SYNC_PUB=$(echo "$SYNC_JSON" | jq -r '.data.published_count // 0' 2>/dev/null)
    if [[ -n "$SYNC_ERR" ]]; then
        echo "  WARNING: $SYNC_ERR"
    else
        echo "  OK: KV synced ($SYNC_PUB new card(s) published)"
    fi
else
    echo "  WARNING: No output from publish command"
fi
echo ""

# ── Verification URLs ─────────────────────────────────────────────────────────

echo "=== Verify in Live App ==="
echo ""

# Query cards that have images
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius -t -A -F'|' -c "
    SELECT c.card_id, c.title, c.image_url, col.slug
    FROM collections.cards c
    JOIN collections.collections col ON c.collection_id = col.collection_id
    WHERE c.status = 'published'
      AND c.image_url IS NOT NULL AND c.image_url != ''
    ORDER BY c.card_id
    LIMIT 20
" 2>/dev/null | while IFS='|' read -r card_id title image_url slug; do
    short_title="${title:0:50}"
    [[ ${#title} -gt 50 ]] && short_title="${short_title}..."
    echo "  Card: $short_title"
    echo "    Image: $image_url"
    echo "    Page:  https://gaius.zndx.org/cards/$card_id"
    echo ""
done

# ── Final Stats ───────────────────────────────────────────────────────────────

echo "=== Updated Stats ==="
PGPASSWORD=gaius psql -h localhost -p 5444 -U gaius -d zndx_gaius -t -A -F'|' -c "
    SELECT col.slug,
           COUNT(c.card_id),
           COUNT(c.image_url) FILTER (WHERE c.image_url IS NOT NULL AND c.image_url != ''),
           COUNT(*) FILTER (WHERE c.image_url IS NULL OR c.image_url = '')
    FROM collections.cards c
    JOIN collections.collections col ON c.collection_id = col.collection_id
    WHERE c.status = 'published'
    GROUP BY col.slug ORDER BY col.slug
" 2>/dev/null | while IFS='|' read -r slug total has needs; do
    printf "  %-25s %3d published, %3d with images, %3d remaining\n" "$slug" "$total" "$has" "$needs"
done
echo ""

# Wait for endpoint restoration
echo "Waiting for endpoint restoration..."
for i in 1 2 3 4 5 6; do
    sleep 10
    ALL_HEALTHY=$(uv run gaius-cli --cmd "/gpu status" --format json 2>/dev/null \
        | jq -r 'if [.data.endpoints[]? | .status] | all(. == "PROCESS_STATUS_HEALTHY") then "yes" else "no" end' 2>/dev/null)
    if [[ "$ALL_HEALTHY" == "yes" ]]; then
        echo "All endpoints restored to HEALTHY."
        break
    fi
    if [[ $i -eq 6 ]]; then
        echo "WARNING: Endpoints not yet healthy after 60s. Check: /gpu status"
    fi
done

echo ""
echo "Done. Open the card page URLs above to verify images in the live app."
