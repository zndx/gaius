/**
 * Collection page routes for gaius.zndx.org
 *
 * Provides:
 * - GET /collections — Index page listing all active collections
 * - GET /collections/:id — Individual collection page with multi-model summaries
 *
 * Data is sourced from Cloudflare KV:
 * - collection:{collection_id} — Full collection page data
 * - collection-alias:{slug} — Slug-to-UUID resolution
 * - collections_index — Index listing
 * - theme_config — Theme selection
 */

import type { Context } from 'hono';
import { getTheme, generateCSSVariables, type Theme } from '../themes';
import type {
  Card,
  ThemeConfig,
  CollectionData,
  CollectionIndexEntry,
  CollectionAliasData,
} from '../types';
import { escapeHtml, renderCard, simpleMarkdown } from '../utils/html';

// ============================================================================
// Styles
// ============================================================================

function generateCollectionStyles(theme: Theme): string {
  const cssVars = generateCSSVariables(theme);

  return `
    ${cssVars}

    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
      background: var(--color-void);
      color: var(--text-primary);
      min-height: 100vh;
      line-height: 1.6;
    }

    a { color: var(--color-info); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Breadcrumb + header */
    .page-header {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2rem 2rem 0;
    }

    .breadcrumb {
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-bottom: 1rem;
    }

    .breadcrumb a { color: var(--color-info); }

    .collection-title {
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 0.5rem;
    }

    .collection-description {
      font-size: 1rem;
      color: var(--text-secondary);
      margin-bottom: 1.5rem;
      max-width: 800px;
    }

    /* Summary panels */
    .summaries-container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 2rem;
    }

    .summaries-scroll {
      display: flex;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
      gap: 0;
    }

    .summaries-scroll::-webkit-scrollbar { display: none; }

    .summary-panel {
      flex: 0 0 100%;
      scroll-snap-align: start;
      scroll-snap-stop: always;
      background: var(--color-charcoal);
      border: 1px solid var(--color-grid);
      border-radius: 4px;
      padding: 1.5rem;
      position: relative;
    }

    .summary-panel::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 12px;
      height: 12px;
      border-top: 2px solid var(--color-amber);
      border-left: 2px solid var(--color-amber);
    }

    .summary-label {
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--color-info);
      background: color-mix(in srgb, var(--color-info) 15%, transparent);
      padding: 0.25rem 0.5rem;
      border-radius: 2px;
      display: inline-block;
      margin-bottom: 1rem;
    }

    .summary-text {
      font-size: 0.95rem;
      color: var(--text-secondary);
      line-height: 1.7;
    }

    .summary-text p { margin-bottom: 0.75rem; }
    .summary-text p:last-child { margin-bottom: 0; }
    .summary-text strong { color: var(--text-primary); }
    .summary-text code {
      background: var(--color-void);
      padding: 0.1rem 0.3rem;
      border-radius: 2px;
      font-size: 0.85em;
    }
    .summary-text ul { padding-left: 1.5rem; margin-bottom: 0.75rem; }
    .summary-text li { margin-bottom: 0.25rem; }

    .summary-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 1rem;
      padding-top: 0.75rem;
      border-top: 1px solid var(--color-grid);
      font-family: ui-monospace, 'SF Mono', monospace;
    }

    /* Dot indicators (mobile) */
    .summary-indicators {
      display: flex;
      justify-content: center;
      gap: 0.5rem;
      padding: 1rem 0;
    }

    .summary-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--color-grid);
      transition: background 0.2s;
    }

    .summary-dot.active {
      background: var(--color-amber);
    }

    /* Desktop: side-by-side */
    @media (min-width: 1024px) {
      .summaries-scroll {
        overflow-x: visible;
        scroll-snap-type: none;
        gap: 1.25rem;
      }
      .summary-panel { flex: 1; }
      .summary-indicators { display: none; }
    }

    /* Card grid */
    main {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2rem;
    }

    .section-title {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--color-grid);
    }

    .masonry-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1.25rem;
      align-items: start;
    }

    /* Card styles (reused from landing) */
    .card {
      background: var(--color-charcoal);
      border-radius: 4px;
      padding: 1.25rem;
      border: 1px solid var(--color-grid);
      transition: all 0.2s ease;
      cursor: pointer;
      position: relative;
      text-decoration: none;
      display: block;
      color: inherit;
    }

    .card::before {
      content: '';
      position: absolute;
      top: 0; left: 0;
      width: 12px; height: 12px;
      border-top: 2px solid var(--color-amber);
      border-left: 2px solid var(--color-amber);
    }

    .card::after {
      content: '';
      position: absolute;
      bottom: 0; right: 0;
      width: 12px; height: 12px;
      border-bottom: 2px solid var(--color-amber);
      border-right: 2px solid var(--color-amber);
    }

    .card:hover {
      border-color: var(--color-amber);
      transform: translateY(-2px);
      box-shadow: var(--shadow-card);
    }

    .card-title {
      font-size: 1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 0.5rem;
      line-height: 1.4;
    }

    .card-summary {
      font-size: 0.875rem;
      color: var(--text-secondary);
      margin-bottom: 0.75rem;
    }

    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 0.75rem;
      border-top: 1px solid var(--color-grid);
    }

    .card-type {
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--color-info);
      background: color-mix(in srgb, var(--color-info) 15%, transparent);
      padding: 0.25rem 0.5rem;
      border-radius: 2px;
    }

    .card-date {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-family: ui-monospace, 'SF Mono', monospace;
    }

    /* Footer */
    .page-footer {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2rem;
      border-top: 1px solid var(--color-grid);
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .aliases {
      margin-bottom: 0.5rem;
    }

    .alias-tag {
      display: inline-block;
      font-size: 0.75rem;
      color: var(--color-info);
      background: color-mix(in srgb, var(--color-info) 10%, transparent);
      padding: 0.15rem 0.5rem;
      border-radius: 2px;
      margin-right: 0.5rem;
      margin-bottom: 0.25rem;
      font-family: ui-monospace, 'SF Mono', monospace;
    }

    .canonical-url {
      font-family: ui-monospace, 'SF Mono', monospace;
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    /* Index page styles */
    .index-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 1.25rem;
      align-items: start;
    }

    .collection-card {
      background: var(--color-charcoal);
      border-radius: 4px;
      padding: 1.5rem;
      border: 1px solid var(--color-grid);
      transition: all 0.2s ease;
      text-decoration: none;
      display: block;
      color: inherit;
      position: relative;
    }

    .collection-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0;
      width: 12px; height: 12px;
      border-top: 2px solid var(--color-amber);
      border-left: 2px solid var(--color-amber);
    }

    .collection-card:hover {
      border-color: var(--color-amber);
      transform: translateY(-2px);
      box-shadow: var(--shadow-card);
    }

    .collection-card-name {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 0.5rem;
    }

    .collection-card-desc {
      font-size: 0.875rem;
      color: var(--text-secondary);
      margin-bottom: 0.75rem;
    }

    .collection-card-meta {
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      color: var(--text-muted);
      padding-top: 0.75rem;
      border-top: 1px solid var(--color-grid);
    }

    .featured-badge {
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--color-amber);
      background: color-mix(in srgb, var(--color-amber) 15%, transparent);
      padding: 0.15rem 0.5rem;
      border-radius: 2px;
    }

    /* Empty state */
    .empty-state {
      text-align: center;
      padding: 4rem 2rem;
      color: var(--text-secondary);
    }

    .empty-state h2 { margin-bottom: 0.5rem; }

    /* Responsive */
    @media (max-width: 1024px) {
      .masonry-grid { grid-template-columns: repeat(2, 1fr); }
    }

    @media (max-width: 640px) {
      .masonry-grid { grid-template-columns: 1fr; }
      .collection-title { font-size: 1.5rem; }
      main { padding: 1rem; }
      .page-header { padding: 1rem 1rem 0; }
      .summaries-container { padding: 0 1rem; }
      .page-footer { padding: 1rem; }
    }
  `;
}

// ============================================================================
// Scroll indicator script (mobile swipe)
// ============================================================================

function generateScrollScript(): string {
  return `
    (function() {
      const scroll = document.querySelector('.summaries-scroll');
      const dots = document.querySelectorAll('.summary-dot');
      if (!scroll || dots.length === 0) return;

      scroll.addEventListener('scroll', function() {
        const idx = Math.round(scroll.scrollLeft / scroll.clientWidth);
        dots.forEach(function(d, i) {
          d.classList.toggle('active', i === idx);
        });
      });
    })();
  `;
}

// ============================================================================
// Helpers
// ============================================================================

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;

  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;

  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

async function getThemeFromKV(kv: KVNamespace | undefined): Promise<Theme> {
  let themeConfig: ThemeConfig = { theme_id: 'keiretsu-dark' };
  try {
    if (kv) {
      const config = await kv.get('theme_config', 'json') as ThemeConfig | null;
      if (config?.theme_id) {
        themeConfig = config;
      }
    }
  } catch (err) {
    console.error('Failed to fetch theme config:', err);
  }
  return getTheme(themeConfig.theme_id);
}

// ============================================================================
// Collection Page Handler
// ============================================================================

export async function handleCollectionPage(c: Context): Promise<Response> {
  const id = c.req.param('id');
  const kv = c.env?.GAIUS_COLLECTIONS;

  if (!kv) {
    return c.text('KV namespace not available', 500);
  }

  // 1. Try direct collection lookup
  let collectionData = await kv.get(`collection:${id}`, 'json') as CollectionData | null;

  // 2. If miss, try alias lookup → redirect to canonical URL
  if (!collectionData) {
    const aliasData = await kv.get(`collection-alias:${id}`, 'json') as CollectionAliasData | null;
    if (aliasData?.collection_id) {
      // Redirect to canonical UUID URL
      return c.redirect(`/collections/${aliasData.collection_id}`, 301);
    }

    // 404
    const theme = await getThemeFromKV(kv);
    return c.html(render404(theme, id), 404);
  }

  const theme = await getThemeFromKV(kv);
  const data = collectionData;

  // Render summaries
  const summaryPanels: string[] = [];
  const summaryLabels: string[] = [];

  if (data.summaries.frontier) {
    summaryLabels.push('Brave API');
    summaryPanels.push(renderSummaryPanel(data.summaries.frontier, 'Brave API'));
  }
  if (data.summaries.cerebras) {
    summaryLabels.push('Cerebras Thinking');
    summaryPanels.push(renderSummaryPanel(data.summaries.cerebras, 'Cerebras Thinking'));
  }
  if (data.summaries.open_weights) {
    summaryLabels.push('Open-Weights Reasoning');
    summaryPanels.push(renderSummaryPanel(data.summaries.open_weights, 'Open-Weights Reasoning'));
  }

  const hasSummaries = summaryPanels.length > 0;
  const hasMultipleSummaries = summaryPanels.length > 1;

  // Render cards
  const cardHtml = data.cards.length > 0
    ? `
      <div class="section-title">Research Materials (${data.cards.length})</div>
      <div class="masonry-grid">
        ${data.cards.map((card: Card) => `
          <div>${renderCard(card)}</div>
        `).join('')}
      </div>
    `
    : `
      <div class="empty-state">
        <h2>No published cards yet</h2>
        <p>Cards will appear here as research materials are curated.</p>
      </div>
    `;

  // Render aliases
  const aliasHtml = data.zettle_aliases.length > 0
    ? `
      <div class="aliases">
        <span>Aliases: </span>
        ${data.zettle_aliases.map((alias: string) =>
          `<span class="alias-tag">${escapeHtml(alias)}</span>`
        ).join('')}
      </div>
    `
    : '';

  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>${escapeHtml(data.name)} - Gaius Collections</title>
      <meta name="description" content="${escapeHtml(data.description)}">
      <style>${generateCollectionStyles(theme)}</style>
    </head>
    <body>
      <div class="page-header">
        <div class="breadcrumb">
          <a href="/collections">&larr; Collections</a>
        </div>
        <h1 class="collection-title">${escapeHtml(data.name)}</h1>
        ${data.description ? `<p class="collection-description">${escapeHtml(data.description)}</p>` : ''}
      </div>

      ${hasSummaries ? `
        <div class="summaries-container">
          <div class="summaries-scroll">
            ${summaryPanels.join('')}
          </div>
          ${hasMultipleSummaries ? `
            <div class="summary-indicators">
              ${summaryPanels.map((_, i: number) =>
                `<div class="summary-dot${i === 0 ? ' active' : ''}"></div>`
              ).join('')}
            </div>
          ` : ''}
        </div>
      ` : ''}

      <main>
        ${cardHtml}
      </main>

      <div class="page-footer">
        ${aliasHtml}
        <div class="canonical-url">
          Canonical: /collections/${escapeHtml(data.collection_id)}
        </div>
      </div>

      ${hasMultipleSummaries ? `<script>${generateScrollScript()}</script>` : ''}
    </body>
    </html>
  `;

  return c.html(html);
}

function renderSummaryPanel(summary: { text: string; model_label: string; generated_at: string }, label: string): string {
  const ago = summary.generated_at ? timeAgo(summary.generated_at) : '';

  return `
    <div class="summary-panel">
      <div class="summary-label">${escapeHtml(label)}</div>
      <div class="summary-text">${simpleMarkdown(summary.text)}</div>
      ${ago ? `<div class="summary-meta">Generated ${ago}</div>` : ''}
    </div>
  `;
}

function render404(theme: Theme, id: string): string {
  return `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Collection Not Found - Gaius</title>
      <style>${generateCollectionStyles(theme)}</style>
    </head>
    <body>
      <div class="page-header">
        <div class="breadcrumb">
          <a href="/collections">&larr; Collections</a>
        </div>
      </div>
      <div class="empty-state">
        <h2>Collection Not Found</h2>
        <p>No collection found for "${escapeHtml(id)}".</p>
        <p style="margin-top: 1rem;"><a href="/collections">Browse all collections</a></p>
      </div>
    </body>
    </html>
  `;
}

// ============================================================================
// Collection Index Handler
// ============================================================================

export async function handleCollectionIndex(c: Context): Promise<Response> {
  const kv = c.env?.GAIUS_COLLECTIONS;

  if (!kv) {
    return c.text('KV namespace not available', 500);
  }

  const theme = await getThemeFromKV(kv);

  // Get collections index from KV
  let collections: CollectionIndexEntry[] = [];
  try {
    const data = await kv.get('collections_index', 'json');
    if (data && Array.isArray(data)) {
      collections = data as CollectionIndexEntry[];
    }
  } catch (err) {
    console.error('Failed to fetch collections index:', err);
  }

  const collectionCards = collections.length > 0
    ? `
      <div class="index-grid">
        ${collections.map((coll: CollectionIndexEntry) => `
          <a href="/collections/${escapeHtml(coll.collection_id)}" class="collection-card">
            <div class="collection-card-name">
              ${escapeHtml(coll.name)}
              ${coll.featured ? '<span class="featured-badge">Featured</span>' : ''}
            </div>
            ${coll.description ? `<div class="collection-card-desc">${escapeHtml(coll.description)}</div>` : ''}
            <div class="collection-card-meta">
              <span>${coll.published_cards} published card${coll.published_cards !== 1 ? 's' : ''}</span>
              ${coll.updated_at ? `<span>${timeAgo(coll.updated_at)}</span>` : ''}
            </div>
          </a>
        `).join('')}
      </div>
    `
    : `
      <div class="empty-state">
        <h2>No Collections Yet</h2>
        <p>Collections will appear here as research is curated.</p>
      </div>
    `;

  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Collections - Gaius</title>
      <meta name="description" content="Curated research collections in AI reasoning, epistemic uncertainty, and normative aesthetics">
      <style>${generateCollectionStyles(theme)}</style>
    </head>
    <body>
      <div class="page-header">
        <div class="breadcrumb">
          <a href="/">&larr; Home</a>
        </div>
        <h1 class="collection-title">Collections</h1>
        <p class="collection-description">Curated research collections with multi-model AI summaries.</p>
      </div>

      <main>
        ${collectionCards}
      </main>

      <div class="page-footer">
        <p>Powered by <a href="https://github.com/zndx/gaius">Gaius</a></p>
      </div>
    </body>
    </html>
  `;

  return c.html(html);
}
