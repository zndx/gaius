/**
 * Card detail page route for gaius.zndx.org
 *
 * Provides:
 * - GET /cards/:id — Individual card page with multi-model summaries,
 *   Brave follow-up search links, source link, and collection link
 *
 * Data is sourced from Cloudflare KV:
 * - card:{card_id} — Full card page data (synced by CollectionService)
 * - theme_config — Theme selection
 */

import type { Context } from 'hono';
import { getTheme, generateCSSVariables, type Theme } from '../themes';
import type { CardPageData, ThemeConfig } from '../types';
import { escapeHtml, simpleMarkdown } from '../utils/html';

// ============================================================================
// Styles
// ============================================================================

function generateCardPageStyles(theme: Theme): string {
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
    .breadcrumb .sep { margin: 0 0.5rem; }

    .card-page-title {
      font-size: 1.75rem;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 0.75rem;
      line-height: 1.3;
    }

    .card-meta {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
    }

    .source-badge {
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
      font-size: 0.85rem;
      color: var(--text-muted);
      font-family: ui-monospace, 'SF Mono', monospace;
    }

    /* Brief summary */
    .card-brief {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 2rem 1.5rem;
    }

    .card-brief p {
      font-size: 1.05rem;
      color: var(--text-secondary);
      line-height: 1.7;
    }

    /* Summary panels (reused from collections) */
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
      top: 0; left: 0;
      width: 12px; height: 12px;
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

    /* Actions section */
    .card-actions {
      max-width: 1400px;
      margin: 0 auto;
      padding: 1.5rem 2rem;
    }

    /* Brave citation links */
    .citations {
      margin-bottom: 1.5rem;
    }

    .citations-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.75rem;
    }

    .citation-links {
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }

    .citation-link {
      font-size: 0.85rem;
      color: var(--color-info);
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.4rem 0;
      transition: color 0.15s ease;
    }

    .citation-link:hover {
      color: var(--text-primary);
      text-decoration: none;
    }

    .citation-link .cite-domain {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-family: ui-monospace, 'SF Mono', monospace;
      flex-shrink: 0;
    }

    /* Source link */
    .source-link-section {
      margin-bottom: 1.5rem;
    }

    .source-link {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.95rem;
      color: var(--color-info);
      background: var(--color-charcoal);
      border: 1px solid var(--color-grid);
      padding: 0.75rem 1.25rem;
      border-radius: 4px;
      text-decoration: none;
      transition: all 0.15s ease;
    }

    .source-link:hover {
      border-color: var(--color-amber);
      text-decoration: none;
    }

    .source-link .arrow { font-size: 1.1rem; }

    /* Collection card */
    .collection-link {
      display: block;
      background: var(--color-charcoal);
      border: 1px solid var(--color-grid);
      border-radius: 4px;
      padding: 1.25rem;
      text-decoration: none;
      color: inherit;
      transition: all 0.2s ease;
      position: relative;
      max-width: 400px;
    }

    .collection-link::before {
      content: '';
      position: absolute;
      top: 0; left: 0;
      width: 12px; height: 12px;
      border-top: 2px solid var(--color-amber);
      border-left: 2px solid var(--color-amber);
    }

    .collection-link:hover {
      border-color: var(--color-amber);
      transform: translateY(-2px);
      box-shadow: var(--shadow-card);
      text-decoration: none;
    }

    .collection-link-label {
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.5rem;
    }

    .collection-link-name {
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    /* Card navigation */
    .card-nav {
      max-width: 1400px;
      margin: 0 auto;
      padding: 1rem 2rem 2rem;
      display: flex;
      justify-content: space-between;
    }

    .card-nav a {
      font-size: 0.85rem;
      color: var(--text-muted);
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

    /* Responsive */
    @media (max-width: 640px) {
      .card-page-title { font-size: 1.35rem; }
      .page-header { padding: 1rem 1rem 0; }
      .card-brief { padding: 0 1rem 1rem; }
      .summaries-container { padding: 0 1rem; }
      .card-actions { padding: 1rem; }
      .card-nav { padding: 0.5rem 1rem 1rem; }
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
      var scroll = document.querySelector('.summaries-scroll');
      var dots = document.querySelectorAll('.summary-dot');
      if (!scroll || dots.length === 0) return;

      scroll.addEventListener('scroll', function() {
        var idx = Math.round(scroll.scrollLeft / scroll.clientWidth);
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

// ============================================================================
// Card Page Handler
// ============================================================================

export async function handleCardPage(c: Context): Promise<Response> {
  const id = c.req.param('id');
  const kv = c.env?.GAIUS_COLLECTIONS;

  if (!kv) {
    return c.text('KV namespace not available', 500);
  }

  // Look up card page data
  const cardData = await kv.get(`card:${id}`, 'json') as CardPageData | null;

  if (!cardData) {
    const theme = await getThemeFromKV(kv);
    return c.html(render404(theme, id), 404);
  }

  const theme = await getThemeFromKV(kv);
  const data = cardData;

  // Format date
  const dateStr = data.source_date || data.published_at;
  const dateObj = new Date(dateStr);
  const currentYear = new Date().getFullYear();
  const contentYear = dateObj.getFullYear();
  const formattedDate = dateObj.toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    ...(contentYear < currentYear && { year: 'numeric' }),
  });

  // Render summaries
  const summaryPanels: string[] = [];

  if (data.summaries.frontier) {
    summaryPanels.push(renderSummaryPanel(data.summaries.frontier, 'Brave API'));
  }
  if (data.summaries.cerebras) {
    summaryPanels.push(renderSummaryPanel(data.summaries.cerebras, 'Cerebras Thinking'));
  }
  if (data.summaries.open_weights) {
    summaryPanels.push(renderSummaryPanel(data.summaries.open_weights, 'Open-Weights Reasoning'));
  }

  const hasSummaries = summaryPanels.length > 0;
  const hasMultipleSummaries = summaryPanels.length > 1;

  // Render Brave citation links (URLs from Brave Answers API)
  const citationsHtml = data.brave_followups && data.brave_followups.length > 0
    ? `
      <div class="citations">
        <div class="citations-title">Sources</div>
        <div class="citation-links">
          ${data.brave_followups.map((url: string) => {
            let domain = '';
            try { domain = new URL(url).hostname.replace('www.', ''); } catch { domain = url; }
            return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="citation-link"><span class="cite-domain">${escapeHtml(domain)}</span> &#x2197;</a>`;
          }).join('')}
        </div>
      </div>
    `
    : '';

  // Render source link
  const sourceHtml = data.source_url
    ? `
      <div class="source-link-section">
        <a href="${escapeHtml(data.source_url)}" target="_blank" rel="noopener noreferrer" class="source-link">
          <span class="source-badge">${escapeHtml(data.source_type)}</span>
          View source
          <span class="arrow">&#x2197;</span>
        </a>
      </div>
    `
    : '';

  // Render collection link
  const collectionHtml = data.collection_id
    ? `
      <a href="/collections/${escapeHtml(data.collection_id)}" class="collection-link">
        <div class="collection-link-label">From collection</div>
        <div class="collection-link-name">${escapeHtml(data.collection_name || 'View collection')}</div>
      </a>
    `
    : '';

  // Prev/next navigation
  const navHtml = (data.prev_card_id || data.next_card_id)
    ? `
      <div class="card-nav">
        ${data.prev_card_id
          ? `<a href="/cards/${escapeHtml(data.prev_card_id)}">&larr; Previous</a>`
          : '<span></span>'}
        ${data.next_card_id
          ? `<a href="/cards/${escapeHtml(data.next_card_id)}">Next &rarr;</a>`
          : '<span></span>'}
      </div>
    `
    : '';

  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>${escapeHtml(data.title)} - Gaius</title>
      <meta name="description" content="${escapeHtml(data.summary)}">
      <style>${generateCardPageStyles(theme)}</style>
    </head>
    <body>
      <div class="page-header">
        <div class="breadcrumb">
          <a href="/">Home</a>
          <span class="sep">/</span>
          <a href="/collections">Collections</a>
          <span class="sep">/</span>
          <a href="/collections/${escapeHtml(data.collection_id)}">${escapeHtml(data.collection_name || 'Collection')}</a>
          <span class="sep">/</span>
          <span>${escapeHtml(data.title.length > 40 ? data.title.slice(0, 37) + '...' : data.title)}</span>
        </div>
        <h1 class="card-page-title">${escapeHtml(data.title)}</h1>
        <div class="card-meta">
          <span class="source-badge">${escapeHtml(data.source_type)}</span>
          <span class="card-date">${formattedDate}</span>
        </div>
      </div>

      <div class="card-brief">
        <p>${escapeHtml(data.summary)}</p>
      </div>

      ${hasSummaries ? `
        <div class="summaries-container">
          <div class="summaries-scroll">
            ${summaryPanels.join('')}
          </div>
          ${hasMultipleSummaries ? `
            <div class="summary-indicators">
              ${summaryPanels.map((_: string, i: number) =>
                `<div class="summary-dot${i === 0 ? ' active' : ''}"></div>`
              ).join('')}
            </div>
          ` : ''}
        </div>
      ` : ''}

      <div class="card-actions">
        ${citationsHtml}
        ${sourceHtml}
        ${collectionHtml}
      </div>

      ${navHtml}

      <div class="page-footer">
        <p>Powered by <a href="https://github.com/zndx/gaius">Gaius</a></p>
      </div>

      ${hasMultipleSummaries ? `<script>${generateScrollScript()}</script>` : ''}
    </body>
    </html>
  `;

  return c.html(html);
}

function render404(theme: Theme, id: string): string {
  return `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Card Not Found - Gaius</title>
      <style>${generateCardPageStyles(theme)}</style>
    </head>
    <body>
      <div class="page-header">
        <div class="breadcrumb">
          <a href="/">&larr; Home</a>
        </div>
      </div>
      <div style="text-align: center; padding: 4rem 2rem; color: var(--text-secondary);">
        <h2>Card Not Found</h2>
        <p>No card found for "${escapeHtml(id)}".</p>
        <p style="margin-top: 1rem;"><a href="/">Browse all cards</a></p>
      </div>
    </body>
    </html>
  `;
}
