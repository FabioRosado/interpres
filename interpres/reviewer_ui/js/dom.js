export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined && options.text !== null) element.textContent = String(options.text);
  if (options.title) element.title = options.title;
  if (options.open) element.open = true;
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null) element.setAttribute(key, String(value));
  }
  for (const [key, value] of Object.entries(options.dataset || {})) element.dataset[key] = String(value);
  for (const child of children) if (child !== null && child !== undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}

export function textDiff(before, after) {
  const beforeParts = String(before || "").split(/(\s+)/);
  const afterParts = String(after || "").split(/(\s+)/);
  if (!before && !after) return [];
  const matrix = Array.from({ length: beforeParts.length + 1 }, () => Array(afterParts.length + 1).fill(0));
  for (let i = 1; i <= beforeParts.length; i++) {
    for (let j = 1; j <= afterParts.length; j++) {
      matrix[i][j] = beforeParts[i - 1] === afterParts[j - 1]
        ? matrix[i - 1][j - 1] + 1
        : Math.max(matrix[i][j - 1], matrix[i - 1][j]);
    }
  }
  const ops = [];
  let i = beforeParts.length;
  let j = afterParts.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && beforeParts[i - 1] === afterParts[j - 1]) {
      ops.unshift({ kind: "equal", text: beforeParts[--i] }); j--;
    } else if (j > 0 && (i === 0 || matrix[i][j - 1] >= matrix[i - 1][j])) {
      ops.unshift({ kind: "insert", text: afterParts[--j] });
    } else {
      ops.unshift({ kind: "delete", text: beforeParts[--i] });
    }
  }
  return ops.reduce((segments, op) => {
    if (!op.text) return segments;
    const previous = segments.at(-1);
    if (previous?.kind === op.kind) previous.text += op.text;
    else segments.push({ ...op });
    return segments;
  }, []);
}

export function clear(element) { element.replaceChildren(); return element; }
export function stringify(value) { return JSON.stringify(value, null, 2); }
export function humanize(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
export function statusClass(value) { return String(value || "incomplete").toLowerCase().replaceAll(" ", "_"); }
export function evidenceStatusClass(value) { return String(value || "unavailable").toLowerCase().replaceAll(/[_\s]+/g, "-"); }
export function compactId(value) {
  if (!value) return "—";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-6)}` : text;
}
export function emptyState(message, stateName = null) {
  return node("div", { className: "empty-state", text: stateName ? `${humanize(stateName)} · ${message}` : message });
}
export function pill(text, className = "type-pill") { return node("span", { className, text: humanize(text) }); }
export function relatedDataset(ids) { return { unitIds: (ids || []).join(" ") }; }
export function unique(values) { return Array.from(new Set((values || []).filter(Boolean).map(String))); }
export function containsAny(left, right) {
  const rightSet = new Set(right || []);
  return (left || []).some((item) => rightSet.has(item));
}
export function primaryId(record) {
  return record?.issue_id || record?.finding_id || record?.request_id || record?.edit_id || record?.evidence_id || record?.flag_id || record?.entry_id || null;
}

export function findQuoteRange(text, quote, from = 0) {
  const source = String(text || "");
  const needle = String(quote || "").trim();
  if (!source || !needle) return null;
  const direct = source.indexOf(needle, from);
  return direct >= 0 ? { start: direct, end: direct + needle.length } : null;
}
