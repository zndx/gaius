/**
 * Shared HTML utility functions for the Gaius web worker.
 *
 * Extracted from landing.ts for reuse across landing page,
 * collection pages, and other routes.
 */

import type { Card } from '../types';

/**
 * Escape HTML special characters to prevent XSS.
 */
export function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Render a card as an HTML anchor element.
 *
 * Default: links to /cards/{card_id} with source_type badge (no external link).
 * linkTo: 'source' — links to external source_url (for future use).
 * linkToSource: true — backward compat alias for linkTo: 'source'.
 *
 * Prefers source_date (original publication) over published_at (when added to collection).
 * Includes year for content from past years (HN-style).
 */
export function renderCard(card: Card, options?: { linkTo?: 'card' | 'source'; linkToSource?: boolean }): string {
  const dateStr = card.source_date || card.published_at;
  const dateObj = new Date(dateStr);
  const currentYear = new Date().getFullYear();
  const contentYear = dateObj.getFullYear();

  const date = dateObj.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(contentYear < currentYear && { year: 'numeric' }),
  });

  // Resolve link target: default is card detail page
  const linkToSource = options?.linkTo === 'source' || options?.linkToSource === true;

  const href = linkToSource
    ? escapeHtml(card.source_url)
    : `/cards/${escapeHtml(card.card_id)}`;
  const target = linkToSource ? ' target="_blank" rel="noopener noreferrer"' : '';

  // Always show source_type badge (no external link icon on card listings)
  const sourceTag = `<span class="card-type">${escapeHtml(card.source_type)}</span>`;

  return `
    <a href="${href}"${target} class="card">
      <div class="card-title">${escapeHtml(card.title)}</div>
      <div class="card-summary">${escapeHtml(card.summary)}</div>
      <div class="card-footer">
        ${sourceTag}
        <span class="card-date">${date}</span>
      </div>
    </a>
  `;
}

/**
 * Lightweight inline Markdown to HTML converter.
 *
 * Supports: paragraphs, bold, italic, inline code, bullet lists, headers (h2-h4).
 * Does NOT support: images, links, tables, blockquotes (intentionally minimal).
 */
export function simpleMarkdown(text: string): string {
  // Split into blocks by double newlines
  const blocks = text.split(/\n\n+/);

  return blocks
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return '';

      // Headers
      if (trimmed.startsWith('#### ')) {
        return `<h4>${inlineMarkdown(escapeHtml(trimmed.slice(5)))}</h4>`;
      }
      if (trimmed.startsWith('### ')) {
        return `<h3>${inlineMarkdown(escapeHtml(trimmed.slice(4)))}</h3>`;
      }
      if (trimmed.startsWith('## ')) {
        return `<h2>${inlineMarkdown(escapeHtml(trimmed.slice(3)))}</h2>`;
      }

      // Bullet lists (lines starting with - or *)
      const lines = trimmed.split('\n');
      if (lines.every((l) => /^[\-\*]\s/.test(l.trim()))) {
        const items = lines
          .map((l) => `<li>${inlineMarkdown(escapeHtml(l.trim().slice(2)))}</li>`)
          .join('');
        return `<ul>${items}</ul>`;
      }

      // Regular paragraph
      return `<p>${inlineMarkdown(escapeHtml(trimmed.replace(/\n/g, ' ')))}</p>`;
    })
    .join('\n');
}

/**
 * Apply inline Markdown formatting (bold, italic, code).
 * Input should already be HTML-escaped.
 */
function inlineMarkdown(text: string): string {
  return (
    text
      // Bold: **text**
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Italic: *text*
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // Inline code: `text`
      .replace(/`(.+?)`/g, '<code>$1</code>')
  );
}
