function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeHref(value) {
  const href = String(value || "").trim();
  return /^(https?:|mailto:|#)/i.test(href) ? escapeHtml(href) : "#";
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, href) => `<a href="${safeHref(href)}" rel="noreferrer">${label}</a>`);
  html = html.replace(/\[\^([^\]]+)\]/g, '<sup class="footnote-ref">[$1]</sup>');
  return html;
}

export function markdownToSafeHtml(markdown) {
  const lines = String(markdown || "").replaceAll("\r\n", "\n").split("\n");
  const output = [];
  const paragraph = [];
  const footnotes = [];
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replaceAll("\n", "<br>")}</p>`);
    paragraph.length = 0;
  };
  let inCode = false;
  const code = [];
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        code.length = 0;
      } else flushParagraph();
      inCode = !inCode;
      continue;
    }
    if (inCode) { code.push(line); continue; }
    const footnote = line.match(/^\[\^([^\]]+)\]:\s*(.+)$/);
    if (footnote) { flushParagraph(); footnotes.push(`<li><b>${escapeHtml(footnote[1])}.</b> ${inlineMarkdown(footnote[2])}</li>`); continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) { flushParagraph(); const level = heading[1].length; output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) { flushParagraph(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
    if (!line.trim()) flushParagraph();
    else paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
  flushParagraph();
  if (footnotes.length) output.push(`<section class="footnotes" aria-label="Footnotes"><ol>${footnotes.join("")}</ol></section>`);
  return output.join("\n");
}

export function renderMarkdown(container, markdown) {
  container.innerHTML = markdownToSafeHtml(markdown);
}

export function wrapMarkdownSelection(textarea, action) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = textarea.value.slice(start, end);
  const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
  const inlineText = selected || "text";
  const linkText = selected || "label";
  const formats = {
    emphasis: [`*${inlineText}*`, 1, 1 + inlineText.length],
    strong: [`**${inlineText}**`, 2, 2 + inlineText.length],
    link: [`[${linkText}](https://)`, 1, 1 + linkText.length],
    footnote: [`${selected}[^note]\n\n[^note]: `, selected.length + 2, selected.length + 6],
  };
  let replacement;
  let selectStart = start;
  let selectEnd = end;
  if (action === "quote" || action === "heading") {
    const prefix = action === "quote" ? "> " : "## ";
    const block = textarea.value.slice(lineStart, end || textarea.value.length).replace(/^/gm, prefix);
    textarea.setRangeText(block, lineStart, end || textarea.value.length, "select");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  [replacement, selectStart, selectEnd] = formats[action] || [selected, 0, selected.length];
  textarea.setRangeText(replacement, start, end, "end");
  textarea.setSelectionRange(start + selectStart, start + selectEnd);
  textarea.focus();
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}
