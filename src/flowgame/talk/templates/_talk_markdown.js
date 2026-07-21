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

/** 是否像图片 URL（含带签名参数的 OSS / CDN） */
function isLikelyImageUrl(url) {
  const u = String(url || '').trim();
  if (!u) return false;
  if (/^data:image\//i.test(u)) return true;
  if (!/^https?:\/\//i.test(u)) return false;
  if (/\.(png|jpe?g|gif|webp|bmp|svg)(\?|#|$)/i.test(u)) return true;
  if (/\.(png|jpe?g|gif|webp|bmp|svg)(?=[?#/])/i.test(u)) return true;
  return false;
}

function extractImageUrlsFromText(text) {
  const raw = String(text || '');
  const found = [];
  const trimmed = raw.trim();
  if (isLikelyImageUrl(trimmed)) {
    found.push(trimmed);
    return found;
  }

  const mdRe = /!\[[^\]]*\]\((https?:[^)\s]+)\)/gi;
  let m;
  while ((m = mdRe.exec(raw))) {
    const url = String(m[1] || '').trim();
    if (isLikelyImageUrl(url) && found.indexOf(url) === -1) found.push(url);
  }

  const urlRe = /https?:\/\/[^\s<>"'\]]+/gi;
  while ((m = urlRe.exec(raw))) {
    let url = m[0].replace(/[),.;!?]+$/g, '');
    if (isLikelyImageUrl(url) && found.indexOf(url) === -1) found.push(url);
  }
  return found;
}

function filenameFromImageUrl(url) {
  try {
    const path = new URL(url, window.location.href).pathname;
    const base = (path.split('/').pop() || 'image').split('?')[0];
    if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(base)) return base;
    return (base || 'image') + '.png';
  } catch (e) {
    return 'image.png';
  }
}

function renderAssistantImageCards(urls) {
  return urls.map(function (url) {
    const safe = escapeHtml(url);
    const name = escapeHtml(filenameFromImageUrl(url));
    return (
      '<div class="assistant-image-card">' +
        '<a class="assistant-image-link" href="' + safe + '" target="_blank" rel="noopener noreferrer">' +
          '<img class="assistant-image" src="' + safe + '" alt="生成图片" loading="lazy" />' +
        '</a>' +
        '<div class="assistant-image-actions">' +
          '<button type="button" class="assistant-image-download" data-image-url="' + safe + '" data-image-name="' + name + '">下载图片</button>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

function downloadAssistantImage(url, filename) {
  const href = String(url || '').trim();
  if (!href) return;
  const name = String(filename || filenameFromImageUrl(href) || 'image.png');

  function fallbackOpen() {
    window.open(href, '_blank', 'noopener,noreferrer');
  }

  if (/^data:image\//i.test(href)) {
    const a = document.createElement('a');
    a.href = href;
    a.download = name;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }

  fetch(href, { mode: 'cors', credentials: 'omit' })
    .then(function (res) {
      if (!res.ok) throw new Error('download failed');
      return res.blob();
    })
    .then(function (blob) {
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = name;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 1500);
    })
    .catch(fallbackOpen);
}

/** 绑定气泡内「下载图片」按钮（事件委托） */
function bindAssistantImageDownloads(root) {
  if (!root || root.dataset.imageDownloadBound === '1') return;
  root.dataset.imageDownloadBound = '1';
  root.addEventListener('click', function (e) {
    const btn = e.target && e.target.closest
      ? e.target.closest('.assistant-image-download')
      : null;
    if (!btn || !root.contains(btn)) return;
    e.preventDefault();
    e.stopPropagation();
    downloadAssistantImage(
      btn.getAttribute('data-image-url'),
      btn.getAttribute('data-image-name')
    );
  });
}

/**
 * 若 content 是纯图片 URL / 含图片链接：渲染预览 + 下载；
 * 其余文本仍走 Markdown。
 */
function renderAssistantMarkdown(content) {
  const text = String(content == null ? '' : content);
  const urls = extractImageUrlsFromText(text);
  if (!urls.length) return renderMarkdownBlocks(text);

  let remainder = text;
  urls.forEach(function (url) {
    remainder = remainder.split(url).join(' ');
  });
  remainder = remainder
    .replace(/!\[[^\]]*\]\(\s*\)/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const cards = renderAssistantImageCards(urls);
  if (!remainder) return cards;
  return cards + renderMarkdownBlocks(remainder);
}
