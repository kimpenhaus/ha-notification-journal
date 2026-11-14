import { html, type TemplateResult } from "lit";

const INLINE = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^*\n]+?)\*\*|\*([^*\s][^*\n]*?)\*/g;

export function navigate(path: string): void {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

function followInternal(event: MouseEvent): void {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
  const href = (event.currentTarget as HTMLAnchorElement).getAttribute("href");
  if (!href) return;
  event.preventDefault();
  navigate(href);
}

function link(label: string, href: string): TemplateResult | string {
  if (href.startsWith("/") && !href.startsWith("//")) {
    return html`<a href=${href} @click=${followInternal}>${inline(label)}</a>`;
  }
  if (/^https?:\/\//i.test(href)) {
    return html`<a href=${href} target="_blank" rel="noopener noreferrer">${inline(label)}</a>`;
  }
  return label;
}

/** The inline Markdown of Home Assistant's notifications (code, links, bold, italic); the rest stays text. */
export function inline(text: string): (TemplateResult | string)[] {
  const parts: (TemplateResult | string)[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const [, code, label, href, bold, italic] = match;
    if (code !== undefined) parts.push(html`<code>${code}</code>`);
    else if (label !== undefined && href !== undefined) parts.push(link(label, href));
    else if (bold !== undefined) parts.push(html`<strong>${inline(bold)}</strong>`);
    else if (italic !== undefined) parts.push(html`<em>${inline(italic)}</em>`);
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
