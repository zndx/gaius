/**
 * A2UI Renderer
 *
 * Renders A2UI messages to HTML. This is a server-side renderer
 * that produces static HTML from A2UI component descriptors.
 */

import type { A2UIMessage, A2UIComponent, OAuthCallbackData } from '@gaius-ui/a2ui-core';
import { renderComponent } from './catalog';

/**
 * Render an A2UI message to a complete HTML page.
 */
export function renderA2UIPage(
  message: A2UIMessage,
  context?: OAuthCallbackData
): string {
  const components = message.surfaceUpdate?.components ?? [];
  const renderedComponents = components.map((c) => renderComponent(c, context)).join('\n');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gaius - Authorization</title>
  <style>
    :root {
      --bg-primary: #1a1a2e;
      --bg-secondary: #16213e;
      --text-primary: #eee;
      --text-secondary: #888;
      --accent: #7c3aed;
      --success: #22c55e;
      --error: #ef4444;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg-primary);
      color: var(--text-primary);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    .shell {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }

    .shell-header {
      text-align: center;
      margin-bottom: 2rem;
    }

    .shell-title {
      font-size: 1.5rem;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 0.5rem;
    }

    .shell-subtitle {
      color: var(--text-secondary);
      font-size: 0.875rem;
    }

    .auth-result {
      background: var(--bg-secondary);
      border-radius: 12px;
      padding: 2rem;
      max-width: 400px;
      width: 100%;
      text-align: center;
    }

    .auth-result.success {
      border: 1px solid var(--success);
    }

    .auth-result.error {
      border: 1px solid var(--error);
    }

    .auth-icon {
      font-size: 3rem;
      margin-bottom: 1rem;
    }

    .auth-title {
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 0.5rem;
    }

    .auth-message {
      color: var(--text-secondary);
      font-size: 0.875rem;
      margin-bottom: 1.5rem;
    }

    .auth-code {
      background: var(--bg-primary);
      border-radius: 8px;
      padding: 1rem;
      font-family: 'SF Mono', Monaco, Consolas, monospace;
      font-size: 0.75rem;
      word-break: break-all;
      color: var(--text-secondary);
      margin-bottom: 1rem;
    }

    .auth-instructions {
      background: var(--bg-primary);
      border-radius: 8px;
      padding: 1rem;
      text-align: left;
      font-size: 0.875rem;
    }

    .auth-instructions h4 {
      color: var(--accent);
      margin-bottom: 0.5rem;
    }

    .auth-instructions code {
      background: var(--bg-secondary);
      padding: 0.125rem 0.375rem;
      border-radius: 4px;
      font-family: 'SF Mono', Monaco, Consolas, monospace;
      font-size: 0.75rem;
    }

    .auth-instructions ol {
      margin-left: 1.25rem;
      color: var(--text-secondary);
    }

    .auth-instructions li {
      margin-bottom: 0.5rem;
    }

    .auth-instructions p {
      color: var(--text-secondary);
      margin-bottom: 0.75rem;
    }

    .copy-command {
      background: var(--bg-primary);
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 1rem;
      margin-top: 1rem;
      cursor: pointer;
      position: relative;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }

    .copy-command:hover {
      background: rgba(124, 58, 237, 0.1);
      border-color: var(--success);
    }

    .copy-command code {
      font-family: 'SF Mono', Monaco, Consolas, monospace;
      font-size: 0.8rem;
      color: var(--text-primary);
      word-break: break-all;
      flex: 1;
      text-align: left;
    }

    .copy-command .copy-icon {
      font-size: 1.25rem;
      opacity: 0.7;
      transition: opacity 0.2s;
    }

    .copy-command:hover .copy-icon {
      opacity: 1;
    }

    .copy-command .copy-feedback {
      position: absolute;
      top: -2rem;
      left: 50%;
      transform: translateX(-50%);
      background: var(--success);
      color: white;
      padding: 0.25rem 0.75rem;
      border-radius: 4px;
      font-size: 0.75rem;
      opacity: 0;
      transition: opacity 0.2s;
      pointer-events: none;
    }

    .copy-command.copied .copy-feedback {
      opacity: 1;
    }

    .copy-command.copied {
      border-color: var(--success);
    }
  </style>
</head>
<body>
  ${renderedComponents}
</body>
</html>`;
}
