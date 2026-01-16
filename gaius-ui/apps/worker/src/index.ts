/**
 * Gaius Web Worker
 *
 * Cloudflare Worker handling OAuth callbacks and serving A2UI surfaces.
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { handleOAuthCallback } from './routes/callback';

const app = new Hono();

// CORS for API endpoints
app.use('/api/*', cors());

// Health check
app.get('/health', (c) => {
  return c.json({ status: 'ok', service: 'gaius-web' });
});

// OAuth callback route for X (Twitter)
app.get('/x-callback', handleOAuthCallback);

// Root - simple status page
app.get('/', (c) => {
  return c.html(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Gaius</title>
      <style>
        body {
          font-family: system-ui, -apple-system, sans-serif;
          display: flex;
          justify-content: center;
          align-items: center;
          min-height: 100vh;
          margin: 0;
          background: #1a1a2e;
          color: #eee;
        }
        .container {
          text-align: center;
          padding: 2rem;
        }
        h1 { color: #7c3aed; }
        p { color: #888; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Gaius</h1>
        <p>Agent Interface Service</p>
      </div>
    </body>
    </html>
  `);
});

export default app;
