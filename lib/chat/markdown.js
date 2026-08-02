import { marked } from 'marked';

marked.setOptions({ gfm: true, breaks: true });

let dompurifyLinksHooked = false;

export function safeHtml(raw) {
  if (typeof window === 'undefined') return raw;
  try {
    const DOMPurify = require('dompurify');
    if (!dompurifyLinksHooked) {
      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        if (node.tagName === 'A' && node.hasAttribute('href')) {
          node.setAttribute('target', '_blank');
          node.setAttribute('rel', 'noopener noreferrer');
        }
      });
      dompurifyLinksHooked = true;
    }
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch {
    return raw;
  }
}

export function renderSafeMarkdown(text) {
  return safeHtml(marked.parse(text || ''));
}
