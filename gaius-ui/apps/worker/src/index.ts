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
import {
  handleCollectionIndex,
  handleCollectionPage,
} from './routes/collections';

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

// ============================================================================
// Well-Known Verification Files
// ============================================================================

// Brave Rewards publisher verification
app.get('/.well-known/brave-rewards-verification.txt', (c) => {
  const verificationText = `This is a Brave Creators publisher verification file.

Domain: zndx.org
Token: e92f68d6a291100fe760a6f1352e97d7543d5f3537f5ab4743d25a2029e6e4a8
`;
  return c.text(verificationText);
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

// Collection pages
app.get('/collections', handleCollectionIndex);
app.get('/collections/:id', handleCollectionPage);

// Article permalinks - redirect to external URL
app.get('/articles/:slug', handleArticleRedirect);

export default app;
