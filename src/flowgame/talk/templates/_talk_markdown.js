/** Lightweight Markdown + HTML preview renderer for talk assistant bubbles. */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function sanitizeHref(href) {
  const value = String(href || '').trim();
  if (/^(https?:|mailto:|tel:)/i.test(value)) return value;
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  return '#';
}

var HTML_PREVIEW_ALLOWED_TAGS = {
  article: true,
  aside: true,
  b: true,
  blockquote: true,
  br: true,
  caption: true,
  code: true,
  div: true,
  em: true,
  figcaption: true,
  figure: true,
  footer: true,
  h1: true,
  h2: true,
  h3: true,
  h4: true,
  h5: true,
  h6: true,
  header: true,
  hr: true,
  i: true,
  img: true,
  li: true,
  main: true,
  mark: true,
  ol: true,
  p: true,
  section: true,
  small: true,
  span: true,
  strong: true,
  sub: true,
  sup: true,
  table: true,
  tbody: true,
  td: true,
  th: true,
  thead: true,
  tr: true,
  u: true,
  ul: true
};

var HTML_PREVIEW_GLOBAL_ATTRS = ['class', 'style', 'id', 'title', 'role', 'aria-label'];
var HTML_PREVIEW_TAG_ATTRS = {
  a: ['href', 'target', 'rel'],
  img: ['src', 'alt', 'width', 'height', 'loading'],
  td: ['colspan', 'rowspan'],
  th: ['colspan', 'rowspan']
};

function sanitizeStyleValue(style) {
  const value = String(style || '');
  if (/expression|javascript:|@import|behavior:|url\s*\(\s*['"]?\s*javascript:/i.test(value)) {
    return '';
  }
  return value;
}

function sanitizeElementAttributes(el) {
  const tag = el.tagName.toLowerCase();
  const allowed = HTML_PREVIEW_GLOBAL_ATTRS.concat(HTML_PREVIEW_TAG_ATTRS[tag] || []);
  Array.prototype.slice.call(el.attributes).forEach(function (attr) {
    const name = attr.name.toLowerCase();
    if (name.indexOf('on') === 0 || name === 'srcdoc' || name === 'formaction') {
      el.removeAttribute(attr.name);
      return;
    }
    if (allowed.indexOf(name) === -1) {
      el.removeAttribute(attr.name);
      return;
    }
    if (name === 'href' || name === 'src') {
      const safe = sanitizeHref(attr.value);
      el.setAttribute(attr.name, safe);
      return;
    }
    if (name === 'style') {
      const safeStyle = sanitizeStyleValue(attr.value);
      if (safeStyle) {
        el.setAttribute('style', safeStyle);
      } else {
        el.removeAttribute('style');
      }
    }
  });
  if (tag === 'a' && el.getAttribute('target') === '_blank') {
    el.setAttribute('rel', 'noopener noreferrer');
  }
}

function sanitizeHtmlNode(node) {
  const children = Array.prototype.slice.call(node.childNodes);
  children.forEach(function (child) {
    if (child.nodeType === 8) {
      node.removeChild(child);
      return;
    }
    if (child.nodeType !== 1) return;
    const tag = child.tagName.toLowerCase();
    if (!HTML_PREVIEW_ALLOWED_TAGS[tag]) {
      while (child.firstChild) {
        node.insertBefore(child.firstChild, child);
      }
      node.removeChild(child);
      return;
    }
    sanitizeElementAttributes(child);
    sanitizeHtmlNode(child);
  });
}

function extractHtmlFragment(raw) {
  const trimmed = String(raw || '').trim();
  if (!trimmed) return '';
  if (/<!DOCTYPE|<html[\s>]/i.test(trimmed)) {
    const doc = new DOMParser().parseFromString(trimmed, 'text/html');
    return doc.body ? doc.body.innerHTML : trimmed;
  }
  return trimmed;
}

function sanitizeHtmlPreview(raw) {
  const fragment = extractHtmlFragment(raw);
  if (!fragment) return '';
  const doc = new DOMParser().parseFromString('<div data-talk-root="1">' + fragment + '</div>', 'text/html');
  const root = doc.querySelector('[data-talk-root]');
  if (!root) return '';
  sanitizeHtmlNode(root);
  return root.innerHTML;
}

function renderHtmlPreview(raw) {
  return '<div class="assistant-html-preview">' + sanitizeHtmlPreview(raw) + '</div>';
}

function renderInlineMarkdown(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  out = out.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  out = out.replace(/_([^_\n]+)_/g, '<em>$1</em>');
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, href) {
    const safeHref = sanitizeHref(href);
    const extra = safeHref.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : '';
    return '<a href="' + escapeHtml(safeHref) + '"' + extra + '>' + label + '</a>';
  });
  return out;
}

function renderMarkdownBlocks(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  const html = [];
  let index = 0;

  function flushParagraph(buffer) {
    const content = buffer.join('\n').trim();
    if (!content) return;
    html.push('<p>' + renderInlineMarkdown(content).replace(/\n/g, '<br>') + '</p>');
  }

  while (index < lines.length) {
    const line = lines[index];

    if (/^```/.test(line)) {
      const langMatch = line.match(/^```([^\s`]*)/);
      const lang = ((langMatch && langMatch[1]) || '').toLowerCase();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const code = codeLines.join('\n');
      if (lang === 'html' || lang === 'htm') {
        html.push(renderHtmlPreview(code));
      } else {
        html.push('<pre><code>' + escapeHtml(code) + '</code></pre>');
      }
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      html.push('<h' + level + '>' + renderInlineMarkdown(heading[2]) + '</h' + level + '>');
      index += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ''));
        index += 1;
      }
      html.push('<blockquote>' + renderInlineMarkdown(quoteLines.join('\n')).replace(/\n/g, '<br>') + '</blockquote>');
      continue;
    }

    if (/^[-*+]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index])) {
        items.push('<li>' + renderInlineMarkdown(lines[index].replace(/^[-*+]\s+/, '')) + '</li>');
        index += 1;
      }
      html.push('<ul>' + items.join('') + '</ul>');
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push('<li>' + renderInlineMarkdown(lines[index].replace(/^\d+\.\s+/, '')) + '</li>');
        index += 1;
      }
      html.push('<ol>' + items.join('') + '</ol>');
      continue;
    }

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !/^```/.test(lines[index]) && !/^(#{1,6})\s+/.test(lines[index]) && !/^>\s?/.test(lines[index]) && !/^[-*+]\s+/.test(lines[index]) && !/^\d+\.\s+/.test(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    flushParagraph(paragraph);
  }

  return html.join('');
}

function renderAssistantMarkdown(content) {
  return renderMarkdownBlocks(content);
}
