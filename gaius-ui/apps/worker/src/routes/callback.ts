/**
 * OAuth Callback Handler
 *
 * Handles X (Twitter) OAuth 2.0 callback:
 * 1. Stores code+state in KV for engine polling
 * 2. Tries direct callback to engine if configured
 * 3. Displays result via A2UI
 */

import type { Context } from 'hono';
import { createOAuthResultMessage, type OAuthCallbackData } from '@gaius-ui/a2ui-core';
import { renderA2UIPage } from '../a2ui/renderer';

interface Env {
  GAIUS_SESSIONS: KVNamespace;
  ENGINE_CALLBACK_URL?: string;
}

export async function handleOAuthCallback(c: Context<{ Bindings: Env }>): Promise<Response> {
  // Extract OAuth parameters from query string
  const code = c.req.query('code');
  const state = c.req.query('state');
  const error = c.req.query('error');
  const errorDescription = c.req.query('error_description');

  let callbackSucceeded = false;

  // If we have a valid code and state, store in KV and try direct callback
  if (code && state && !error) {
    // Store in KV for engine polling (TTL: 5 minutes)
    try {
      await c.env.GAIUS_SESSIONS.put(
        `oauth-pending/${state}`,
        JSON.stringify({ code, timestamp: Date.now() }),
        { expirationTtl: 300 }
      );
      console.log(`Stored OAuth code in KV for state=${state.substring(0, 8)}...`);
    } catch (e) {
      console.error('Failed to store OAuth code in KV:', e);
    }

    // Try direct callback to engine if configured
    const engineUrl = c.env.ENGINE_CALLBACK_URL;
    if (engineUrl) {
      try {
        const response = await fetch(`${engineUrl}/api/oauth/x-callback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, state }),
        });
        if (response.ok) {
          callbackSucceeded = true;
          console.log('Direct callback to engine succeeded');
        } else {
          console.log(`Direct callback returned ${response.status}, engine will poll KV`);
        }
      } catch (e) {
        console.log('Direct callback failed, engine will poll KV:', e);
      }
    }
  }

  const callbackData: OAuthCallbackData = {
    code,
    state,
    error,
    errorDescription,
  };

  // Generate A2UI message for the result
  const a2uiMessage = createOAuthResultMessage(callbackData, callbackSucceeded);

  // Render as HTML page
  const html = renderA2UIPage(a2uiMessage, callbackData);

  return c.html(html);
}
