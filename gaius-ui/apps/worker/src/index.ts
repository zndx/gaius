/**
 * Gaius Web Worker
 *
 * Cloudflare Worker handling:
 * - Public landing page with 3D viz + masonry cards
 * - OAuth callbacks for X (Twitter)
 * - API endpoints for card/viz data
 * - Article permalinks with external redirects
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { handleOAuthCallback } from './routes/callback';
import {
  handleLanding,
  handleApiCards,
  handleApiViz,
  handleApiThemes,
  handleArticleRedirect,
} from './routes/landing';

// Type bindings for KV namespaces
type Bindings = {
  GAIUS_SESSIONS: KVNamespace;
  GAIUS_COLLECTIONS: KVNamespace;
};

const app = new Hono<{ Bindings: Bindings }>();

// CORS for API endpoints
app.use('/api/*', cors());

// Health check
app.get('/health', (c) => {
  return c.json({ status: 'ok', service: 'gaius-web' });
});

// OAuth callback route for X (Twitter)
app.get('/x-callback', handleOAuthCallback);

// ============================================================================
// Public Landing Page Routes
// ============================================================================

// Landing page - 3D viz header + masonry cards
app.get('/', handleLanding);

// API: Get published cards
app.get('/api/cards', handleApiCards);

// API: Get visualization data
app.get('/api/viz', handleApiViz);

// API: Get available themes
app.get('/api/themes', handleApiThemes);

// Article permalinks - redirect to external URL
app.get('/articles/:slug', handleArticleRedirect);

export default app;
