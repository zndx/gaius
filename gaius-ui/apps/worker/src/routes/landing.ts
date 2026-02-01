/**
 * Landing page route for gaius.zndx.org
 *
 * Displays:
 * - 3D UMAP visualization header (non-interactive, ambient rotation)
 * - Masonry card grid with research materials
 * - Cards link to PUBLIC sources only (arXiv, HuggingFace, etc.)
 *
 * Themes are configurable via KV (theme_config key) or default to Keiretsu Dark.
 */

import type { Context } from 'hono';
import { getTheme, generateCSSVariables, listThemes, type Theme } from '../themes';

interface Card {
  card_id: string;
  title: string;
  summary: string;
  image_url?: string;
  source_url: string;
  source_type: string;
  published_at: string;
  source_date?: string;  // Original source publication date (e.g., arXiv submission)
}

interface ThemeConfig {
  theme_id: string;
  title?: string;
  subtitle?: string;
}

/**
 * Generate CSS styles using theme variables
 */
function generateStyles(theme: Theme): string {
  const cssVars = generateCSSVariables(theme);

  return `
    ${cssVars}

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
      background: var(--color-void);
      color: var(--text-primary);
      min-height: 100vh;
      line-height: 1.6;
    }

    /* Header with 3D viz */
    .viz-header {
      position: relative;
      height: 280px;
      overflow: hidden;
      border-bottom: 1px solid var(--color-charcoal);
    }

    #viz-canvas {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      z-index: 1;
    }

    .viz-overlay {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      padding: 1.5rem 2rem;
      background: linear-gradient(transparent, var(--color-void));
      z-index: 2;
    }

    .viz-title {
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 0.25rem;
    }

    .viz-subtitle {
      font-size: 0.9rem;
      color: var(--text-secondary);
    }

    /* Card grid - CSS Grid for top-aligned responsive columns */
    main {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2rem;
    }

    .masonry-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1.25rem;
      align-items: start;
    }

    .masonry-column {
      /* Wrapper for each card */
    }

    /* Cards */
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

    /* Corner brackets */
    .card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 12px;
      height: 12px;
      border-top: 2px solid var(--color-amber);
      border-left: 2px solid var(--color-amber);
    }

    .card::after {
      content: '';
      position: absolute;
      bottom: 0;
      right: 0;
      width: 12px;
      height: 12px;
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

    /* Empty state */
    .empty-state {
      text-align: center;
      padding: 4rem 2rem;
      color: var(--text-secondary);
    }

    .empty-state h2 {
      margin-bottom: 0.5rem;
    }

    /* Footer */
    footer {
      text-align: center;
      padding: 2rem;
      color: var(--text-muted);
      font-size: 0.8rem;
    }

    footer a {
      color: var(--color-info);
      text-decoration: none;
    }

    footer a:hover {
      text-decoration: underline;
    }

    .theme-info {
      margin-top: 0.5rem;
      font-size: 0.7rem;
      opacity: 0.7;
    }

    /* Responsive */
    @media (max-width: 1024px) {
      .masonry-grid {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    @media (max-width: 640px) {
      .masonry-grid {
        grid-template-columns: 1fr;
      }
      .viz-header { height: 200px; }
      .viz-title { font-size: 1.5rem; }
      main { padding: 1rem; }
    }
  `;
}

/**
 * Generate Three.js visualization script with theme colors
 */
function generateVizScript(theme: Theme): string {
  const { three } = theme;

  // Convert hex to RGB components for Three.js color array
  const hexToRgbArray = (hex: number): [number, number, number] => {
    const r = ((hex >> 16) & 255) / 255;
    const g = ((hex >> 8) & 255) / 255;
    const b = (hex & 255) / 255;
    return [r, g, b];
  };

  const colorChoices = [
    hexToRgbArray(three.gridPrimary),
    hexToRgbArray(three.pointLight1),
    hexToRgbArray(three.pointLight2),
    hexToRgbArray(three.directionalLight),
  ];

  return `
    // Check if Three.js loaded
    if (typeof THREE === 'undefined') {
      console.error('Three.js not loaded');
    } else {
      const container = document.getElementById('viz-canvas');
      if (container) {
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x${three.fog.toString(16).padStart(6, '0')});

        const camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
        camera.position.z = 15;

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        container.appendChild(renderer.domElement);

        // Create points from viz data if available
        const geometry = new THREE.BufferGeometry();
        const positions = [];
        const colors = [];

        // Generate placeholder points (will be replaced by real data)
        const numPoints = 500;
        const colorChoices = ${JSON.stringify(colorChoices)};

        for (let i = 0; i < numPoints; i++) {
          positions.push(
            (Math.random() - 0.5) * 20,
            (Math.random() - 0.5) * 20,
            (Math.random() - 0.5) * 20
          );
          const c = colorChoices[Math.floor(Math.random() * colorChoices.length)];
          colors.push(c[0], c[1], c[2]);
        }

        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

        const material = new THREE.PointsMaterial({
          size: 0.15,
          vertexColors: true,
          transparent: true,
          opacity: 0.8,
          sizeAttenuation: true,
        });

        const points = new THREE.Points(geometry, material);
        scene.add(points);

        // Ambient rotation
        function animate() {
          requestAnimationFrame(animate);
          points.rotation.y += 0.001;
          points.rotation.x += 0.0003;
          renderer.render(scene, camera);
        }
        animate();

        // Handle resize
        window.addEventListener('resize', () => {
          camera.aspect = container.clientWidth / container.clientHeight;
          camera.updateProjectionMatrix();
          renderer.setSize(container.clientWidth, container.clientHeight);
        });
      }
    }
  `;
}

function renderCard(card: Card): string {
  // Prefer source_date (original publication) over published_at (when we added it)
  const dateStr = card.source_date || card.published_at;
  const date = new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });

  return `
    <a href="${card.source_url}" target="_blank" rel="noopener noreferrer" class="card">
      <div class="card-title">${escapeHtml(card.title)}</div>
      <div class="card-summary">${escapeHtml(card.summary)}</div>
      <div class="card-footer">
        <span class="card-type">${card.source_type}</span>
        <span class="card-date">${date}</span>
      </div>
    </a>
  `;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export async function handleLanding(c: Context): Promise<Response> {
  const kv = c.env?.GAIUS_COLLECTIONS;

  // Get theme configuration from KV (or use default)
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

  const theme = getTheme(themeConfig.theme_id);
  const title = themeConfig.title || 'Gaius';
  const subtitle = themeConfig.subtitle || 'Curated research in AI reasoning, transformers, and machine learning';

  // Get cards from KV (or return empty array if not available)
  let cards: Card[] = [];
  try {
    if (kv) {
      const data = await kv.get('published_cards', 'json');
      if (data && Array.isArray(data)) {
        cards = data as Card[];
      }
    }
  } catch (err) {
    console.error('Failed to fetch cards:', err);
  }

  // Cards rendered directly (CSS columns handles layout)
  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>${escapeHtml(title)} - Research Collections</title>
      <meta name="description" content="${escapeHtml(subtitle)}">
      <style>${generateStyles(theme)}</style>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js" crossorigin="anonymous"></script>
    </head>
    <body>
      <header class="viz-header">
        <div id="viz-canvas"></div>
        <div class="viz-overlay">
          <h1 class="viz-title">${escapeHtml(title)}</h1>
          <p class="viz-subtitle">${escapeHtml(subtitle)}</p>
        </div>
      </header>

      <main>
        ${cards.length > 0 ? `
          <div class="masonry-grid">
            ${cards.map(card => `
              <div class="masonry-column">
                ${renderCard(card)}
              </div>
            `).join('')}
          </div>
        ` : `
          <div class="empty-state">
            <h2>Coming Soon</h2>
            <p>Research materials will be published here.</p>
          </div>
        `}
      </main>

      <footer>
        <p>Powered by <a href="https://github.com/zndx/gaius">Gaius</a></p>
        <p class="theme-info">Theme: ${escapeHtml(theme.meta.name)}</p>
      </footer>

      <script>${generateVizScript(theme)}</script>
    </body>
    </html>
  `;

  return c.html(html);
}

export async function handleApiCards(c: Context): Promise<Response> {
  try {
    const kv = c.env?.GAIUS_COLLECTIONS;
    if (!kv) {
      return c.json({ cards: [], error: 'KV not available' }, 500);
    }

    const cards = await kv.get('published_cards', 'json') || [];
    return c.json({ cards });
  } catch (err) {
    console.error('Failed to fetch cards:', err);
    return c.json({ cards: [], error: String(err) }, 500);
  }
}

export async function handleApiViz(c: Context): Promise<Response> {
  try {
    const kv = c.env?.GAIUS_COLLECTIONS;
    if (!kv) {
      return c.json({ error: 'KV not available' }, 500);
    }

    const viz = await kv.get('viz_data', 'json');
    if (!viz) {
      // Return placeholder data
      return c.json({
        points: [],
        clusters: [],
        metadata: { generatedAt: new Date().toISOString(), totalPoints: 0 }
      });
    }
    return c.json(viz);
  } catch (err) {
    console.error('Failed to fetch viz:', err);
    return c.json({ error: String(err) }, 500);
  }
}

export async function handleApiThemes(c: Context): Promise<Response> {
  // Return list of available themes
  return c.json({
    themes: listThemes(),
    default: 'keiretsu-dark',
  });
}

export async function handleArticleRedirect(c: Context): Promise<Response> {
  const slug = c.req.param('slug');

  try {
    const kv = c.env?.GAIUS_COLLECTIONS;
    if (!kv) {
      return c.text('Article not found', 404);
    }

    // Look up article by slug
    const article = await kv.get(`article:${slug}`, 'json') as { external_url?: string; title?: string } | null;

    if (article?.external_url) {
      // 302 redirect to external URL (Substack, X, etc.)
      return c.redirect(article.external_url, 302);
    }

    // Fallback: article not found
    return c.text(`Article "${slug}" not found`, 404);
  } catch (err) {
    console.error('Failed to lookup article:', err);
    return c.text('Internal error', 500);
  }
}
