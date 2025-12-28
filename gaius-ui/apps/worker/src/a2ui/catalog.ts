/**
 * A2UI Component Catalog
 *
 * Server-side component renderers. Each component type has a renderer
 * that converts A2UI component descriptors to HTML.
 */

import type { A2UIComponent, OAuthCallbackData } from '@gaius-ui/a2ui-core';

type ComponentRenderer = (
  props: Record<string, unknown>,
  context?: OAuthCallbackData
) => string;

/**
 * Component catalog - maps component types to their HTML renderers.
 */
const catalog: Record<string, ComponentRenderer> = {
  GaiusShell: (props) => {
    const title = props.title as string || 'Gaius';
    return `
      <div class="shell">
        <div class="shell-header">
          <div class="shell-title">${escapeHtml(title)}</div>
          <div class="shell-subtitle">Agent Interface Service</div>
        </div>
    `;
  },

  GaiusAuthResult: (props, context) => {
    const success = props.success as boolean;
    const code = props.code as string | undefined;
    const error = props.error as string | undefined;
    const errorDescription = props.errorDescription as string | undefined;
    const callbackSucceeded = props.callbackSucceeded as boolean | undefined;

    if (success && code) {
      // If direct callback succeeded, show simplified success message
      if (callbackSucceeded) {
        return `
        <div class="auth-result success">
          <div class="auth-icon">&#10003;</div>
          <div class="auth-title">Authorization Complete</div>
          <div class="auth-message">
            Your X account has been connected to Gaius.
            The TUI will update automatically.
          </div>
          <div class="auth-instructions">
            <p>You can close this page and return to your terminal.</p>
          </div>
        </div>
      </div>
        `;
      }

      // Fallback: show copy command if direct callback didn't work
      const command = `gaius-cli --cmd "/x-bookmarks auth complete ${code}"`;
      return `
        <div class="auth-result success">
          <div class="auth-icon">&#10003;</div>
          <div class="auth-title">Authorization Successful</div>
          <div class="auth-message">
            Your X account has been connected to Gaius.
          </div>
          <div class="auth-instructions">
            <h4>Next Step</h4>
            <p>Click the command below to copy, then paste in your terminal:</p>
          </div>
          <div class="copy-command" onclick="copyToClipboard(this)" title="Click to copy">
            <code>${escapeHtml(command)}</code>
            <span class="copy-icon">&#128203;</span>
            <span class="copy-feedback">Copied!</span>
          </div>
        </div>
      </div>
      <script>
        function copyToClipboard(el) {
          const code = el.querySelector('code').textContent;
          navigator.clipboard.writeText(code).then(() => {
            el.classList.add('copied');
            setTimeout(() => el.classList.remove('copied'), 2000);
          });
        }
      </script>
      `;
    } else {
      return `
        <div class="auth-result error">
          <div class="auth-icon">&#10005;</div>
          <div class="auth-title">Authorization Failed</div>
          <div class="auth-message">
            ${escapeHtml(errorDescription || 'Unable to connect your X account.')}
          </div>
          ${error ? `<div class="auth-code"><strong>Error:</strong> ${escapeHtml(error)}</div>` : ''}
          <div class="auth-instructions">
            <h4>Troubleshooting</h4>
            <ol>
              <li>Ensure the X app has OAuth 2.0 enabled</li>
              <li>Verify the callback URL is configured correctly</li>
              <li>Try running <code>/x-bookmarks auth</code> again</li>
            </ol>
          </div>
        </div>
      </div>
      `;
    }
  },

  Text: (props) => {
    const content = props.content as string || '';
    return `<p>${escapeHtml(content)}</p>`;
  },

  Button: (props) => {
    const label = props.label as string || 'Button';
    const action = props.action as string || '';
    return `<button data-action="${escapeHtml(action)}">${escapeHtml(label)}</button>`;
  },

  Container: (props) => {
    const children = props.children as string || '';
    return `<div class="container">${children}</div>`;
  },
};

/**
 * Render a single A2UI component to HTML.
 */
export function renderComponent(
  component: A2UIComponent,
  context?: OAuthCallbackData
): string {
  // Find the component type (first key in component object)
  const componentType = Object.keys(component.component)[0];
  if (!componentType) {
    return `<!-- Unknown component: ${component.id} -->`;
  }

  const renderer = catalog[componentType];
  if (!renderer) {
    return `<!-- Unsupported component type: ${componentType} -->`;
  }

  const props = component.component[componentType as keyof typeof component.component] || {};
  return renderer(props as Record<string, unknown>, context);
}

/**
 * Escape HTML special characters to prevent XSS.
 */
function escapeHtml(text: string): string {
  const htmlEscapes: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  };
  return text.replace(/[&<>"']/g, (char) => htmlEscapes[char] || char);
}
