"use strict";

const state = {
  overview: null,
  view: null,
  currentChunkId: null,
  selectedUnit: null,
  selectedReviewTarget: null,
  issueFilter: "open",
  reviewMode: "review",
  layers: {
    deterministic: true,
    witness_disagreement: true,
    prosecutor: true,
    adjudicator: true,
    adjudicator_edit: true,
    unresolved: true,
    human_review: true,
    verification: true,
    source_mapping: true,
  },
  reviewIndex: null,
  resolutions: new Map(),
  dirty: false,
  saving: false,
};

const LAYER_LABELS = {
  deterministic: "Deterministic",
  witness_disagreement: "Disagreements",
  prosecutor: "Prosecutor",
  adjudicator: "Adjudicator findings",
  adjudicator_edit: "Adjudicator edits",
  unresolved: "Unresolved",
  human_review: "Human review",
  verification: "Verification",
  source_mapping: "Source mappings",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined && options.text !== null) element.textContent = String(options.text);
  if (options.title) element.title = options.title;
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null) element.setAttribute(key, String(value));
  }
  for (const [key, value] of Object.entries(options.dataset || {})) element.dataset[key] = String(value);
  for (const child of children) if (child !== null && child !== undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}

function clear(element) { element.replaceChildren(); return element; }
function stringify(value) { return JSON.stringify(value, null, 2); }
function humanize(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function statusClass(value) { return String(value || "incomplete").toLowerCase().replaceAll(" ", "_"); }
function compactId(value) {
  if (!value) return "—";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-6)}` : text;
}
function emptyState(message, stateName = null) {
  return node("div", { className: "empty-state", text: stateName ? `${humanize(stateName)} · ${message}` : message });
}
function pill(text, className = "type-pill") { return node("span", { className, text: humanize(text) }); }
function relatedDataset(ids) { return { unitIds: (ids || []).join(" ") }; }

function unique(values) { return Array.from(new Set((values || []).filter(Boolean).map(String))); }
function containsAny(left, right) {
  const rightSet = new Set(right || []);
  return (left || []).some((item) => rightSet.has(item));
}
function primaryId(record) {
  return record?.issue_id || record?.finding_id || record?.request_id || record?.edit_id || record?.evidence_id || record?.flag_id || record?.entry_id || null;
}
function normalizedText(value) { return String(value || "").replace(/\s+/g, " ").trim(); }
function findQuoteRange(text, quote, from = 0) {
  const source = String(text || "");
  const needle = String(quote || "").trim();
  if (!source || !needle) return null;
  const direct = source.indexOf(needle, from);
  if (direct >= 0) return { start: direct, end: direct + needle.length };
  const compactNeedle = normalizedText(needle);
  if (!compactNeedle) return null;
  const compactSource = normalizedText(source);
  const compactIndex = compactSource.indexOf(compactNeedle);
  if (compactIndex < 0) return null;
  return null;
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.message || payload?.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function annotationRecord({ id, type, layer, sourceUnitIds = [], findingIds = [], evidenceIds = [], editIds = [], issueIds = [], textQuote = null, startQuote = null, endQuote = null, replacementQuote = null, label = null, decisionTrailId = null, raw = null }) {
  return {
    id,
    type,
    layer,
    sourceUnitIds: unique(sourceUnitIds),
    findingIds: unique(findingIds),
    evidenceIds: unique(evidenceIds),
    editIds: unique(editIds),
    issueIds: unique(issueIds),
    textQuote,
    startQuote,
    endQuote,
    replacementQuote,
    label,
    decisionTrailId,
    raw,
  };
}

function buildReviewIndex(view) {
  const annotations = [];
  const byIssue = new Map();
  const byUnit = new Map();
  const byEdit = new Map();
  const add = (record) => {
    annotations.push(record);
    for (const id of record.issueIds) byIssue.set(id, record);
    for (const id of record.sourceUnitIds) byUnit.set(id, [...(byUnit.get(id) || []), record]);
    for (const id of record.editIds) byEdit.set(id, record);
  };

  for (const issue of view.issues?.items || []) {
    const id = issue.issue_id;
    const layer = issue.origin === "adjudicator" ? "adjudicator" : issue.origin;
    const quote = issue.english && typeof issue.english === "string" && !issue.english.startsWith("witness_") ? issue.english : null;
    const trail = issue.origin === "deterministic" ? "decision-challenges"
      : issue.origin === "prosecutor" ? "decision-challenges"
      : issue.origin === "adjudicator" || issue.origin === "unresolved" || issue.origin === "human_review" ? "decision-adjudicator"
      : issue.origin === "witness_disagreement" ? "decision-witnesses" : null;
    add(annotationRecord({
      id,
      type: "issue",
      layer,
      sourceUnitIds: issue.source_unit_ids,
      findingIds: [issue.source_record_id],
      evidenceIds: issue.evidence_ids,
      issueIds: [id],
      textQuote: quote,
      label: issue.message || issue.type || issue.origin,
      decisionTrailId: trail,
      raw: issue,
    }));
  }

  for (const edit of view.adjudicator?.edits || []) {
    const id = edit.edit_id;
    add(annotationRecord({
      id,
      type: "adjudicator_edit",
      layer: "adjudicator_edit",
      sourceUnitIds: edit.source_unit_ids,
      editIds: [id],
      evidenceIds: edit.evidence_ids,
      textQuote: edit.old,
      replacementQuote: edit.new,
      label: edit.reason || "Adjudicator edit",
      decisionTrailId: "decision-adjudicator",
      raw: edit,
    }));
  }

  for (const unit of view.source?.units || []) {
    const mapping = mappingForUnit(unit.source_unit_id, view.final?.source_mappings || []);
    const quote = mappingQuote(mapping);
    if (!quote) continue;
    add(annotationRecord({
      id: `source-map:${unit.source_unit_id}`,
      type: "source_mapping",
      layer: "source_mapping",
      sourceUnitIds: [unit.source_unit_id],
      textQuote: quote,
      label: `${unit.source_unit_id} final source mapping`,
      decisionTrailId: "decision-final",
      raw: mapping,
    }));
  }

  for (const item of view.verification?.incomplete_stages || []) {
    if (item.state === "complete") continue;
    add(annotationRecord({
      id: `verification:${item.stage}`,
      type: "verification",
      layer: "verification",
      sourceUnitIds: view.source?.units?.map((unit) => unit.source_unit_id),
      label: `${humanize(item.stage)} is ${humanize(item.state)}`,
      decisionTrailId: "decision-verification",
      raw: item,
    }));
  }

  const missingUnits = view.verification?.missing_source_unit_ids || [];
  for (const unitId of missingUnits) {
    add(annotationRecord({
      id: `coverage:${unitId}`,
      type: "verification",
      layer: "verification",
      sourceUnitIds: [unitId],
      label: "Coverage missing for this source unit",
      decisionTrailId: "decision-verification",
      raw: { source_unit_id: unitId },
    }));
  }

  return { annotations, byIssue, byUnit, byEdit };
}

function mappingForUnit(unitId, mappings = []) {
  return (mappings || []).find((mapping) => String(mapping.source_unit_id || "") === String(unitId));
}

function mappingQuote(mapping) {
  if (!mapping) return null;
  return mapping.english_start_quote || mapping.english_quote || mapping.text || mapping.translation || null;
}

function annotationRange(text, annotation, options = {}) {
  const source = String(text || "");
  if (!source || !annotation) return null;
  const startOffset = annotation.raw?.english_start_offset;
  const endOffset = annotation.raw?.english_end_offset;
  if (Number.isInteger(startOffset) && Number.isInteger(endOffset) && startOffset >= 0 && endOffset > startOffset && endOffset <= source.length) {
    return { start: startOffset, end: endOffset };
  }
  const startQuote = annotation.startQuote || annotation.raw?.english_start_quote;
  const endQuote = annotation.endQuote || annotation.raw?.english_end_quote;
  if (startQuote && endQuote) {
    const start = source.indexOf(String(startQuote));
    if (start >= 0) {
      const endStart = source.indexOf(String(endQuote), start);
      if (endStart >= 0) return { start, end: endStart + String(endQuote).length };
    }
  }
  const quote = options.preferReplacement ? annotation.replacementQuote || annotation.textQuote : annotation.textQuote || annotation.replacementQuote;
  return findQuoteRange(source, quote);
}

function showLoading() { $("#loading-panel").hidden = false; $("#review-content").hidden = true; $("#error-panel").hidden = true; }
function showContent() { $("#loading-panel").hidden = true; $("#review-content").hidden = false; $("#error-panel").hidden = true; }
function showError(error) {
  $("#loading-panel").hidden = true;
  $("#review-content").hidden = true;
  $("#error-panel").hidden = false;
  $("#error-message").textContent = error instanceof Error ? error.message : String(error);
}

function setDirty(dirty) {
  state.dirty = dirty;
  const badge = $("#save-state");
  badge.textContent = state.saving ? "Saving…" : dirty ? "Unsaved" : "Saved";
  badge.className = `save-state${state.saving ? " saving" : dirty ? " unsaved" : ""}`;
}

function targetMatchesAnnotation(target, annotation) {
  if (!target || !annotation) return false;
  return target.id === annotation.id
    || containsAny(target.sourceUnitIds, annotation.sourceUnitIds)
    || containsAny(target.issueIds, annotation.issueIds)
    || containsAny(target.findingIds, annotation.findingIds)
    || containsAny(target.evidenceIds, annotation.evidenceIds)
    || containsAny(target.editIds, annotation.editIds);
}

function targetFromAnnotation(annotation) {
  return {
    id: annotation.id,
    type: annotation.type,
    sourceUnitIds: annotation.sourceUnitIds,
    findingIds: annotation.findingIds,
    evidenceIds: annotation.evidenceIds,
    editIds: annotation.editIds,
    issueIds: annotation.issueIds,
    decisionTrailId: annotation.decisionTrailId,
    label: annotation.label,
    raw: annotation.raw,
  };
}

function targetFromUnit(unitId) {
  const records = state.reviewIndex?.byUnit.get(unitId) || [];
  return {
    id: unitId,
    type: "source_unit",
    sourceUnitIds: [unitId],
    findingIds: unique(records.flatMap((item) => item.findingIds)),
    evidenceIds: unique(records.flatMap((item) => item.evidenceIds)),
    editIds: unique(records.flatMap((item) => item.editIds)),
    issueIds: unique(records.flatMap((item) => item.issueIds)),
    label: unitId,
  };
}

function renderAnnotatedText(container, text, annotations = [], options = {}) {
  clear(container);
  const ranges = [];
  const used = new Set();
  for (const annotation of annotations) {
    if (!state.layers[annotation.layer] && !targetMatchesAnnotation(state.selectedReviewTarget, annotation)) continue;
    const range = annotationRange(text, annotation, options);
    if (!range) continue;
    const key = `${range.start}:${range.end}:${annotation.id}`;
    if (used.has(key)) continue;
    used.add(key);
    ranges.push({ ...range, annotation });
  }
  ranges.sort((a, b) => a.start - b.start || b.end - a.end);
  const filtered = [];
  let cursor = -1;
  for (const range of ranges) {
    if (range.start < cursor) {
      const existing = filtered.find((item) => item.start <= range.start && item.end >= range.end);
      if (existing) existing.annotations.push(range.annotation);
      continue;
    }
    filtered.push({ ...range, annotations: [range.annotation] });
    cursor = range.end;
  }
  let offset = 0;
  for (const range of filtered) {
    if (range.start > offset) container.append(document.createTextNode(text.slice(offset, range.start)));
    const primary = range.annotations[0];
    const span = node("span", {
      className: `annotation ${primary.layer} ${state.layers[primary.layer] ? "" : "hidden-layer"} ${targetMatchesAnnotation(state.selectedReviewTarget, primary) ? "selected selected-source" : ""}`.trim(),
      title: range.annotations.map((item) => item.label || humanize(item.layer)).join("\n"),
      attrs: { tabindex: "0", role: "button", "aria-label": `Review annotation: ${primary.label || primary.layer}` },
      dataset: { reviewId: primary.id, marker: range.annotations.length > 1 ? String(range.annotations.length) : humanize(primary.layer).slice(0, 1) },
    }, [text.slice(range.start, range.end)]);
    span.addEventListener("click", (event) => { event.stopPropagation(); selectReviewTarget(targetFromAnnotation(primary), { scroll: true, focusIssues: true }); });
    span.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectReviewTarget(targetFromAnnotation(primary), { scroll: true, focusIssues: true });
      }
    });
    container.append(span);
    offset = range.end;
  }
  if (offset < text.length) container.append(document.createTextNode(text.slice(offset)));
  if (!text) container.append(emptyState("No text is available."));
}

function renderLayerControls() {
  const controls = clear($("#layer-controls"));
  for (const [key, label] of Object.entries(LAYER_LABELS)) {
    const checkbox = node("input", { attrs: { type: "checkbox" } });
    checkbox.checked = state.layers[key] === true;
    checkbox.addEventListener("change", () => {
      state.layers[key] = checkbox.checked;
      rerenderReviewSurfaces();
    });
    controls.append(node("label", { className: "layer-toggle" }, [checkbox, node("span", { text: label })]));
  }
}

function renderChunkList() {
  const list = clear($("#chunk-list"));
  const query = $("#chunk-search").value.trim().toLowerCase();
  const chunks = state.overview?.chunks || [];
  $("#chunk-total").textContent = String(chunks.length);
  for (const chunk of chunks) {
    const haystack = `${chunk.chunk_id} ${chunk.pl_start} ${chunk.pl_end} ${chunk.final_status}`.toLowerCase();
    if (query && !haystack.includes(query)) continue;
    const counts = chunk.counts || {};
    const issueCount = (counts.deterministic_findings || 0) + (counts.prosecutor_findings || 0) + (counts.unresolved_human_review || 0);
    const revisionCount = chunk.editorial?.revision_count || 0;
    const button = node("button", { className: `chunk-link${chunk.chunk_id === state.currentChunkId ? " active" : ""}`, attrs: { type: "button" }, title: chunk.chunk_id });
    button.append(
      node("i", { className: `status-dot ${statusClass(chunk.final_status)}` }),
      node("span", {}, [
        node("b", {}, [chunk.chunk_id, revisionCount ? node("i", { className: "editorial-dot", title: `${revisionCount} editorial revisions` }) : null]),
        node("small", { text: `PL ${chunk.pl_start || "—"}–${chunk.pl_end || "—"} · ${humanize(chunk.final_status)}` }),
      ]),
      node("span", { className: "chunk-issue-count", text: issueCount })
    );
    button.addEventListener("click", () => loadChunk(chunk.chunk_id));
    list.append(button);
  }
  if (!list.children.length) list.append(emptyState(query ? "No chunks match this search." : "No chunks are available."));
}

function renderMetrics(counts) {
  const strip = clear($("#metric-strip"));
  for (const [value, label] of [
    [counts.witness_disagreements, "Explicit disagreements"],
    [counts.deterministic_findings, "Deterministic findings"],
    [counts.prosecutor_findings, "Prosecutor findings"],
    [counts.adjudicator_edits, "Validated edits"],
    [counts.unresolved_human_review, "Unresolved / human review"],
  ]) {
    strip.append(node("div", { className: "metric" }, [
      node("b", { text: value === null || value === undefined ? "—" : value }),
      node("span", { text: label }),
    ]));
  }
}

function selectUnit(unitId, options = {}) {
  if (!unitId) {
    selectReviewTarget(null, options);
  } else {
    selectReviewTarget(targetFromUnit(unitId), { scroll: true, ...options });
  }
}

function selectReviewTarget(target, { scroll = false, focusIssues = false, openDecisionTrail = false } = {}) {
  state.selectedReviewTarget = target;
  state.selectedUnit = target?.sourceUnitIds?.[0] || null;
  refreshSelectedTextSurfaces();
  applySelection({ scroll, focusIssues, openDecisionTrail });
}

function refreshSelectedTextSurfaces() {
  if (!state.view) return;
  renderMachineFinal();
  renderEditorialPreview();
}

function applySelection({ scroll = false, focusIssues = false, openDecisionTrail = false } = {}) {
  const target = state.selectedReviewTarget;
  const unitId = state.selectedUnit;
  $("#clear-unit").hidden = !target;
  $("#clear-selection").disabled = !target;
  for (const element of $$(".unit-button")) {
    const active = (target?.sourceUnitIds || []).includes(element.dataset.unitId);
    element.classList.toggle("active", active);
    element.setAttribute("aria-pressed", active ? "true" : "false");
  }
  for (const element of $$(".latin-unit")) {
    const active = (target?.sourceUnitIds || []).includes(element.dataset.unitId);
    element.classList.toggle("selected", active);
    element.classList.toggle("dimmed", Boolean(target) && !active);
  }
  for (const element of $$(".related-record")) {
    const ids = (element.dataset.unitIds || "").split(/\s+/).filter(Boolean);
    const issueId = element.dataset.issueId;
    const findingId = element.dataset.findingId;
    const editId = element.dataset.editId;
    const evidenceId = element.dataset.evidenceId;
    const active = Boolean(target) && (
      containsAny(ids, target.sourceUnitIds)
      || (issueId && (target.issueIds || []).includes(issueId))
      || (findingId && (target.findingIds || []).includes(findingId))
      || (editId && (target.editIds || []).includes(editId))
      || (evidenceId && (target.evidenceIds || []).includes(evidenceId))
    );
    element.classList.toggle("dimmed", Boolean(target) && ids.length > 0 && !active);
    element.classList.toggle("selected", active);
  }
  for (const element of $$(".resolution-card")) {
    const active = Boolean(target) && ((target.issueIds || []).includes(element.dataset.issueId) || containsAny((element.dataset.unitIds || "").split(/\s+/).filter(Boolean), target.sourceUnitIds));
    element.classList.toggle("selected", active);
    element.classList.toggle("unrelated", Boolean(target) && !active);
    if (active) element.open = true;
  }
  for (const element of $$(".annotation")) {
    const annotation = state.reviewIndex?.annotations.find((item) => item.id === element.dataset.reviewId);
    element.classList.toggle("selected", targetMatchesAnnotation(target, annotation));
  }
  renderSelectedContext(target);
  if (scroll && target) scrollSelectionIntoView(target, { focusIssues });
  if (openDecisionTrail && target?.decisionTrailId) jumpToDecisionTrail(target.decisionTrailId);
}

function scrollSelectionIntoView(target, { focusIssues = false } = {}) {
  const source = target.sourceUnitIds?.[0] ? $(`.latin-unit[data-unit-id="${CSS.escape(target.sourceUnitIds[0])}"]`) : null;
  const issue = (target.issueIds || []).length ? $(`.resolution-card[data-issue-id="${CSS.escape(target.issueIds[0])}"]`) : null;
  const machineAnnotation = $(`#machine-final .annotation.selected-source, #machine-final .annotation.selected`);
  const annotation = machineAnnotation || $(`.annotation.selected`);
  for (const element of [source, annotation, focusIssues ? issue : null, issue && !source ? issue : null]) {
    if (element) element.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  }
}

function jumpToDecisionTrail(sectionId) {
  const target = sectionId ? document.getElementById(sectionId) : null;
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSelectedContext(target) {
  const panel = clear($("#selected-context"));
  panel.hidden = !target;
  if (!target) return;
  const raw = target.raw || {};
  const issueIds = target.issueIds || [];
  const issue = issueIds.length ? (state.view?.issues?.items || []).find((item) => item.issue_id === issueIds[0]) : null;
  const data = issue || raw;
  const selectedUnitId = target.type === "source_unit" ? target.sourceUnitIds?.[0] : null;
  const selectedFinalMapping = selectedUnitId ? mappingForUnit(selectedUnitId, state.view?.final?.source_mappings || []) : null;
  panel.append(node("h4", { text: target.label || data.message || humanize(target.type) }));
  const dl = node("dl");
  for (const [label, value] of [
    ["Type", data.type || data.origin || target.type],
    ["Severity", data.severity || data.status],
    ["Source units", (target.sourceUnitIds || []).join(" · ")],
    ["Latin", data.latin],
    ["Machine / English", data.english || data.new],
    ["Base witness text", data.old],
    ["Reason", data.reason || data.message || data.missing_evidence || data.issue],
    ["Evidence", (target.evidenceIds || []).join(" · ")],
    ["State", data.resolution || data.verification || data.status],
    ["Machine final mapping", selectedUnitId ? (selectedFinalMapping ? "Persisted boundary quotes available" : "No persisted final-source mapping for this source unit") : null],
  ]) {
    if (!value) continue;
    dl.append(node("dt", { text: label }), node("dd", { text: value }));
  }
  panel.append(dl);
  if (target.decisionTrailId) {
    const link = node("button", { className: "text-button", text: "View in Decision Trail", attrs: { type: "button" } });
    link.addEventListener("click", () => jumpToDecisionTrail(target.decisionTrailId));
    panel.append(link);
  }
}

function visibleIssueCards() {
  return $$(".resolution-card").filter((card) => !card.hidden && card.dataset.issueId);
}

function navigateIssue(direction) {
  const cards = visibleIssueCards();
  if (!cards.length) return;
  const selectedId = state.selectedReviewTarget?.issueIds?.[0];
  let index = selectedId ? cards.findIndex((card) => card.dataset.issueId === selectedId) : -1;
  if (index < 0) index = direction > 0 ? -1 : 0;
  const next = cards[(index + direction + cards.length) % cards.length];
  const annotation = state.reviewIndex?.byIssue.get(next.dataset.issueId);
  if (annotation) selectReviewTarget(targetFromAnnotation(annotation), { scroll: true, focusIssues: true });
}

function renderSource(view) {
  const tabs = clear($("#source-unit-tabs"));
  const units = clear($("#latin-units"));
  const finalMappings = view.final?.source_mappings || [];
  const witnessMappings = (view.witnesses || []).flatMap((witness) => witness.source_mappings || []);
  for (const unit of view.source.units || []) {
    const id = unit.source_unit_id;
    const tab = node("button", { className: "unit-button", text: id, attrs: { type: "button" }, dataset: { unitId: id } });
    tab.addEventListener("click", () => selectUnit(state.selectedUnit === id ? null : id));
    tabs.append(tab);
    const card = node("article", { className: "latin-unit", dataset: { unitId: id } }, [
      node("span", { className: "unit-label", text: `${id} · PL ${unit.page || "—"}` }),
      node("p", { className: "latin-text", text: unit.text || "" }),
    ]);
    const linked = state.reviewIndex?.byUnit.get(id) || [];
    const badges = node("div", { className: "source-badges" });
    const hasFinalMapping = Boolean(mappingForUnit(id, finalMappings));
    const hasWitnessMapping = Boolean(mappingForUnit(id, witnessMappings));
    badges.append(node("span", { className: `source-badge${hasFinalMapping ? "" : " warning"}`, text: hasFinalMapping ? "final mapped" : "final not mapped" }));
    if (!hasWitnessMapping) badges.append(node("span", { className: "source-badge warning", text: "witness not mapped" }));
    for (const layer of unique(linked.map((item) => item.layer)).slice(0, 4)) badges.append(node("span", { className: "source-badge", text: humanize(layer) }));
    card.append(badges);
    card.addEventListener("click", () => selectUnit(state.selectedUnit === id ? null : id));
    units.append(card);
  }
  if (!(view.source.units || []).length) units.append(emptyState("Source units are unavailable."));
  const context = clear($("#context-grid"));
  for (const [heading, value] of [
    ["Context before", view.source.context_before || "None recorded"],
    ["Context after", view.source.context_after || "None recorded"],
    ["Page markers", view.source.page_markers || []],
    ["Annotations", view.source.annotations || []],
  ]) {
    context.append(node("div", { className: "context-card" }, [
      node("h4", { text: heading }),
      typeof value === "string" ? node("p", { text: value }) : node("pre", { text: stringify(value) }),
    ]));
  }
}

function recordCard(finding, origin = "model") {
  const severity = statusClass(finding.severity || "unknown");
  const findingId = primaryId(finding);
  const card = node("article", {
    className: `record-card related-record ${origin}`,
    attrs: { tabindex: "0" },
    dataset: { ...relatedDataset(finding.source_unit_ids), findingId },
  });
  card.append(node("div", { className: "record-meta" }, [
    pill(finding.type || "finding"),
    pill(finding.severity || finding.status || "ungraded", `severity-pill ${severity}`),
    node("span", { className: "model-line", text: finding.finding_id || finding.issue_id || finding.request_id || "" }),
  ]));
  card.append(node("h4", { text: finding.message || finding.issue || finding.missing_evidence || finding.reason || humanize(finding.type || "Finding") }));
  if (finding.latin) card.append(node("p", { className: "latin-quote", text: finding.latin }));
  if (finding.reason) card.append(node("p", { text: finding.reason }));
  if (finding.action) card.append(node("p", { text: `Review action: ${finding.action}` }));
  if (finding.resolution) card.append(node("p", { text: `Resolution: ${finding.resolution}` }));
  if ((finding.evidence_ids || []).length) card.append(node("p", { className: "provenance-line", text: `Evidence · ${finding.evidence_ids.join(" · ")}` }));
  card.addEventListener("click", () => selectReviewTarget({
    id: findingId,
    type: origin,
    sourceUnitIds: finding.source_unit_ids || [],
    findingIds: [findingId],
    evidenceIds: finding.evidence_ids || [],
    editIds: [],
    issueIds: [],
    label: finding.message || finding.reason || finding.type,
    decisionTrailId: origin === "deterministic" ? "decision-challenges" : "decision-adjudicator",
    raw: finding,
  }, { scroll: true, focusIssues: true }));
  return card;
}

function renderFindingStack(container, findings, origin, unavailableState = null) {
  clear(container);
  if (unavailableState && unavailableState !== "complete") { container.append(emptyState("This stage did not produce valid findings.", unavailableState)); return; }
  for (const finding of findings || []) container.append(recordCard(finding, origin));
  if (!(findings || []).length) container.append(emptyState("No findings recorded."));
}

function resolutionFor(issueId) {
  if (!state.resolutions.has(issueId)) state.resolutions.set(issueId, { issue_id: issueId, outcome: "deferred", note: "", reusable: false, approved_english: "" });
  return state.resolutions.get(issueId);
}

function resolutionChanged(issueId, patch) {
  Object.assign(resolutionFor(issueId), patch);
  setDirty(true);
  renderResolutionList();
}

function renderResolutionList() {
  const list = clear($("#resolution-list"));
  const issues = state.view?.issues?.items || [];
  const filter = state.issueFilter;
  let displayed = 0;
  for (const issue of issues) {
    const existing = state.resolutions.get(issue.issue_id);
    const outcome = existing?.outcome || "open";
    const isResolved = outcome === "resolved" || outcome === "accepted_as_is";
    if (filter === "open" && isResolved) continue;
    if (filter === "resolved" && !isResolved) continue;
    displayed += 1;
    const annotation = state.reviewIndex?.byIssue.get(issue.issue_id);
    const details = node("details", {
      className: "resolution-card related-record",
      attrs: { tabindex: "0" },
      dataset: { ...relatedDataset(issue.source_unit_ids), outcome, issueId: issue.issue_id, findingId: issue.source_record_id },
    });
    details.append(node("summary", {}, [node("span", { className: "resolution-summary" }, [
      node("b", { text: issue.message || humanize(issue.type || issue.origin) }),
      node("small", { text: `${humanize(issue.origin)} · ${humanize(issue.severity || issue.status || "ungraded")}` }),
    ])]));
    const body = node("div", { className: "resolution-body" });
    if (issue.latin) body.append(node("p", { className: "latin-quote", text: issue.latin }));
    if (issue.english) body.append(node("p", { className: "mapping-note", text: `Machine/context text · ${issue.english}` }));
    if (!(issue.source_unit_ids || []).length) body.append(node("p", { className: "mapping-note", text: "No persisted source-unit mapping is available for this issue." }));
    if (!annotation?.textQuote) body.append(node("p", { className: "mapping-note", text: "No persisted translation span mapping is available for this issue." }));
    if (annotation?.decisionTrailId) {
      const trail = node("button", { className: "text-button", text: "View in Decision Trail", attrs: { type: "button" } });
      trail.addEventListener("click", (event) => { event.stopPropagation(); jumpToDecisionTrail(annotation.decisionTrailId); });
      body.append(trail);
    }

    const outcomeSelect = node("select", { attrs: { "aria-label": `Outcome for ${issue.issue_id}` } });
    for (const [value, label] of [["deferred", "Still open / defer"], ["resolved", "Resolved by editor"], ["accepted_as_is", "Reviewed · accept as is"]]) {
      const option = node("option", { text: label, attrs: { value } });
      option.selected = outcome === value;
      outcomeSelect.append(option);
    }
    outcomeSelect.addEventListener("change", () => resolutionChanged(issue.issue_id, { outcome: outcomeSelect.value }));
    body.append(node("label", { className: "field" }, [node("span", { text: "Resolution" }), outcomeSelect]));

    const note = node("textarea", { attrs: { placeholder: "Record why this is resolved or deferred…" } });
    note.value = existing?.note || "";
    note.addEventListener("input", () => { Object.assign(resolutionFor(issue.issue_id), { note: note.value }); setDirty(true); });
    body.append(node("label", { className: "field" }, [node("span", { text: "Editorial note" }), note]));

    const approved = node("input", { attrs: { type: "text", placeholder: "Approved English for this exact Latin phrase" } });
    approved.value = existing?.approved_english || "";
    approved.disabled = !issue.reusable_eligible;
    approved.addEventListener("input", () => { Object.assign(resolutionFor(issue.issue_id), { approved_english: approved.value }); setDirty(true); });
    body.append(node("label", { className: "field" }, [node("span", { text: "Reusable approved wording" }), approved]));

    const reuse = node("input", { attrs: { type: "checkbox" } });
    reuse.checked = existing?.reusable === true;
    reuse.disabled = !issue.reusable_eligible;
    reuse.addEventListener("change", () => resolutionChanged(issue.issue_id, { reusable: reuse.checked }));
    body.append(node("label", { className: "reuse-field" }, [reuse, node("span", { text: issue.reusable_eligible ? "Reuse this resolution as human-approved editorial precedent" : "No exact Latin was recorded, so this cannot become precedent" })]));
    details.append(body);
    details.addEventListener("click", (event) => {
      if (["SELECT", "TEXTAREA", "INPUT", "OPTION", "BUTTON"].includes(event.target.tagName)) return;
      if (annotation) selectReviewTarget(targetFromAnnotation(annotation), { scroll: true });
    });
    details.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target === details && annotation) {
        event.preventDefault();
        selectReviewTarget(targetFromAnnotation(annotation), { scroll: true });
      }
    });
    list.append(details);
  }
  if (!displayed) list.append(emptyState(filter === "open" ? "No open issues in this revision." : filter === "resolved" ? "No resolved issues in this revision." : "No resolvable issues were recorded."));
  applySelection();
}

function loadEditorialState(view) {
  const latest = view.editorial?.latest;
  const editorial = latest?.editorial || null;
  state.resolutions = new Map();
  for (const item of editorial?.issue_resolutions || []) state.resolutions.set(item.issue_id, { ...item });
  renderMachineFinal();
  const editor = $("#editor-translation");
  editor.value = editorial?.translation || view.machine.final_draft || "";
  editor.disabled = !view.machine.final_draft_digest;
  $("#save-draft").disabled = editor.disabled;
  $("#approve-revision").disabled = editor.disabled;
  const badge = $("#revision-badge");
  badge.textContent = latest ? `Revision ${latest.revision_number} · ${humanize(editorial.state)}` : "No editorial revision";
  badge.className = `revision-badge${editorial?.state === "approved" ? " approved" : ""}`;
  const history = clear($("#revision-history"));
  for (const item of view.editorial?.history || []) {
    history.append(node("div", { className: "history-row" }, [
      node("span", {}, [node("b", { text: `Revision ${item.revision_number} · ${humanize(item.state)}` }), node("small", { text: ` ${item.resolution_count} resolutions · ${item.reusable_resolution_count} reusable` })]),
      node("small", { text: item.created_at || "" }),
    ]));
  }
  if (!history.children.length) history.append(emptyState("No editorial revisions saved yet."));
  $("#revision-history-summary").textContent = `Revision history · ${view.editorial?.revision_count || 0}`;
  $("#issue-total").textContent = String(view.issues?.count || 0);
  renderEditorialPreview();
  renderResolutionList();
  setDirty(false);
}

function annotationsForMachineText() {
  return [...(state.reviewIndex?.annotations || [])];
}

function renderMachineFinal() {
  const final = state.view?.machine?.final_draft || "No complete machine final is available.";
  const container = $("#machine-final");
  const selectedUnitId = state.selectedReviewTarget?.type === "source_unit" ? state.selectedReviewTarget.sourceUnitIds?.[0] : null;
  const selectedMapping = selectedUnitId ? mappingForUnit(selectedUnitId, state.view?.final?.source_mappings || []) : null;
  container.classList.add("annotated-text");
  renderAnnotatedText(container, final, annotationsForMachineText(), { preferReplacement: true });
  if (selectedUnitId && !selectedMapping) {
    container.append(node("span", { className: "mapping-missing selected-mapping-missing", text: ` ${selectedUnitId}` }));
  } else if (state.view?.final && !state.view.final.mapping_available) {
    container.append(node("span", { className: "mapping-missing", text: "" }));
  }
}

function renderEditorialPreview() {
  const editor = $("#editor-translation");
  const preview = $("#editorial-preview");
  if (!editor || !preview) return;
  renderAnnotatedText(preview, editor.value || "", annotationsForMachineText(), { preferReplacement: true });
}

function rerenderReviewSurfaces() {
  document.body.classList.toggle("clean-reading", state.reviewMode === "clean");
  renderMachineFinal();
  renderEditorialPreview();
  renderSource(state.view);
  renderResolutionList();
  applySelection();
}

async function saveRevision(revisionState) {
  if (state.saving || !state.view?.machine?.final_draft_digest) return;
  const reusable = Array.from(state.resolutions.values()).filter((item) => item.reusable);
  if (revisionState === "approved" && reusable.length && !window.confirm(`${reusable.length} reusable resolution${reusable.length === 1 ? "" : "s"} will become editorial precedent for later matching Latin. Approve this new revision?`)) return;
  state.saving = true;
  setDirty(state.dirty);
  $("#save-message").className = "save-message";
  $("#save-message").textContent = "Creating a separate editorial revision file…";
  const latest = state.view.editorial?.latest;
  const payload = {
    state: revisionState,
    translation: $("#editor-translation").value,
    base_revision_id: latest?.revision_id || null,
    machine_final_digest: state.view.machine.final_draft_digest,
    issue_resolutions: Array.from(state.resolutions.values()),
  };
  try {
    await requestJson(`/api/chunks/${encodeURIComponent(state.currentChunkId)}/editorial/revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.dirty = false;
    state.saving = false;
    await loadChunk(state.currentChunkId, { skipDirtyCheck: true });
    $("#save-message").className = "save-message success";
    $("#save-message").textContent = `${humanize(revisionState)} revision saved as a new file. The machine output is unchanged.`;
  } catch (error) {
    state.saving = false;
    setDirty(true);
    $("#save-message").className = "save-message error";
    $("#save-message").textContent = error.message;
  }
}

function renderWitnesses(view) {
  const grid = clear($("#witness-grid"));
  for (const witness of view.witnesses || []) {
    const eligible = witness.eligible_as_adjudicator_base === true;
    const card = node("article", { className: `witness-card${eligible ? "" : " invalid-witness"}` }, [
      node("h3", { text: witness.label }),
      node("p", { className: "model-line", text: witness.available ? `${witness.provider || "provider unrecorded"} · ${witness.model || "model unrecorded"}` : humanize(witness.state) }),
    ]);
    if (witness.validation_recorded) {
      card.append(node("p", {
        className: eligible ? "save-message success" : "save-message error",
        text: eligible
          ? "Validated · eligible as adjudicator base"
          : `Not eligible as adjudicator base · ${(witness.validation.blocking_failures || []).map(humanize).join(" · ")}`,
      }));
      if (!eligible) card.append(node("p", { className: "mapping-note", text: "Non-authoritative clue only · preserved for audit · not evidence or corroboration" }));
    } else {
      card.append(node("p", { className: "save-message error", text: "Witness validation not recorded" }));
    }
    if (witness.available) {
      const text = node("p", { className: "witness-text annotated-text" });
      const mapped = (witness.source_mappings || []).map((mapping) => annotationRecord({
        id: `witness-map:${witness.witness_id}:${mapping.source_unit_id}`,
        type: "source_mapping",
        layer: "source_mapping",
        sourceUnitIds: [mapping.source_unit_id],
        textQuote: mappingQuote(mapping),
        label: `${witness.label} source mapping`,
        decisionTrailId: "decision-witnesses",
        raw: mapping,
      }));
      renderAnnotatedText(text, witness.translation || "", mapped);
      card.append(text);
    } else {
      card.append(emptyState("No valid witness translation is available.", witness.state));
    }
    if (witness.validation_recorded) card.append(node("details", {}, [node("summary", { text: "Witness validation receipt" }), node("pre", { text: stringify(witness.validation) })]));
    if (witness.uncertainty_recorded) card.append(node("details", {}, [node("summary", { text: "Recorded uncertainty" }), node("pre", { text: stringify(witness.uncertainty) })]));
    grid.append(card);
  }
  $("#disagreement-note").textContent = view.disagreements.note || `${view.disagreements.items.length} explicitly recorded`;
  renderFindingStack($("#disagreement-list"), view.disagreements.items, "model", view.disagreements.available ? null : "unavailable");
}

function renderAnalysis(view) {
  const deterministicSummary = view.deterministic.summary || {};
  $("#deterministic-summary").textContent = `${humanize(view.deterministic.state)} · ${Object.entries(deterministicSummary).map(([key, value]) => `${value} ${humanize(key).toLowerCase()}`).join(" · ") || "no count summary recorded"}`;
  $("#prosecutor-initial-summary").textContent = `${humanize(view.prosecutor.initial.status || view.prosecutor.initial.state)} · ${view.prosecutor.initial.summary || "No summary recorded."}`;
  $("#prosecutor-grounded-summary").textContent = `${humanize(view.prosecutor.grounded.status || view.prosecutor.grounded.state)} · ${view.prosecutor.grounded.summary || "No summary recorded."}`;
  $("#prosecutor-initial-requests").textContent = stringify(view.prosecutor.initial.evidence_requests || []);
  $("#prosecutor-grounded-requests").textContent = stringify(view.prosecutor.grounded.evidence_requests || []);
  renderFindingStack($("#deterministic-findings"), view.deterministic.substantive_findings, "deterministic", view.deterministic.state);
  renderFindingStack($("#prosecutor-initial"), view.prosecutor.initial.findings, "model", view.prosecutor.initial.state);
  renderFindingStack($("#prosecutor-grounded"), view.prosecutor.grounded.findings, "model", view.prosecutor.grounded.state);
  $("#prosecutor-transition-note").textContent = view.prosecutor.transition_note || "";

  const verification = view.verification;
  const grid = clear($("#verification-grid"));
  for (const [value, label] of [
    [verification.coverage_assertion === true ? "Complete asserted" : verification.coverage_assertion === false ? "Not complete" : "Not recorded", "Clause coverage"],
    [verification.source_units_accounted_for ?? "Not mapped", `${verification.source_units_total} source units expected`],
    [humanize(verification.exact_edit_validation), "Exact edit validation"],
    [humanize(verification.schema_status_validation), "Final schema gate"],
  ]) grid.append(node("div", { className: "verification-card" }, [node("b", { text: value }), node("span", { text: label })]));
  const finalChecks = (verification.final_checks?.findings || []).map((raw, index) => ({ finding_id: `final-${index}`, type: raw.check, severity: raw.severity, status: raw.status, message: raw.message, reason: raw.evidence ? stringify(raw.evidence) : null }));
  const missing = (verification.incomplete_stages || []).map((item) => ({ finding_id: `stage-${item.stage}`, type: "pipeline_stage", severity: "high", status: item.state, message: `${humanize(item.stage)} is ${humanize(item.state)}`, reason: item.error?.message }));
  renderFindingStack($("#final-checks"), [...finalChecks, ...missing], "deterministic");

  $("#structural-state").textContent = humanize(view.structural.state);
  const structural = clear($("#structural-body"));
  if (!view.structural.available) structural.append(emptyState("The blind structural analysis is unavailable.", view.structural.state));
  for (const [index, sentence] of (view.structural.sentences || []).entries()) structural.append(node("article", { className: "structural-card" }, [node("h4", { text: `Sentence ${index + 1}` }), node("p", { className: "latin-quote", text: sentence.latin || "" }), node("pre", { text: stringify(sentence) })]));
  structural.append(node("article", { className: "structural-card" }, [node("h4", { text: "Recorded uncertainty" }), node("pre", { text: stringify({ intrinsic_ambiguity: view.structural.intrinsic_ambiguity, context_dependent: view.structural.context_dependent, unverified_analyses: view.structural.unverified_analyses }) })]));

  $("#morphology-state").textContent = humanize(view.morphology.state);
  const morphology = clear($("#morphology-body"));
  if (!view.morphology.available) morphology.append(emptyState("Deterministic morphology is unavailable.", view.morphology.state));
  for (const flag of view.morphology.flags || []) morphology.append(node("article", { className: "morphology-card related-record", dataset: relatedDataset(flag.source_unit_ids) }, [node("h4", { text: `${flag.token || flag.surface || "Form"} · ${humanize(flag.flag_type)}` }), node("pre", { text: stringify(flag) })]));
  const allEntries = node("details", { className: "morphology-card" }, [node("summary", { text: `All ${view.morphology.entries.length} morphology entries` }), node("pre", { text: stringify(view.morphology.entries) })]);
  morphology.append(allEntries);
}

function renderAdjudicator(view) {
  const adjudicator = view.adjudicator;
  $("#base-witness").textContent = adjudicator.base_witness ? `Base witness ${String(adjudicator.base_witness).toUpperCase()}` : "Base witness unrecorded";
  $("#adjudicator-summary").textContent = adjudicator.summary || (adjudicator.available ? "No decision summary recorded." : `${humanize(adjudicator.state)} · no valid decision`);

  const basis = clear($("#decision-basis"));
  for (const [index, item] of (adjudicator.decision_basis || []).entries()) {
    const card = node("article", { className: "record-card" });
    card.append(
      node("div", { className: "record-meta" }, [
        pill(item.grade || "ungraded", `evidence-grade grade-${String(item.grade || "?").toLowerCase()}`),
        node("span", { className: "model-line", text: `Basis ${index + 1}` }),
      ]),
      node("h4", { text: item.claim || "Decision claim not recorded" })
    );
    if ((item.evidence_ids || []).length) card.append(node("p", { className: "provenance-line", text: `Evidence · ${item.evidence_ids.join(" · ")}` }));
    basis.append(card);
  }
  if (!(adjudicator.decision_basis || []).length) basis.append(emptyState("No structured decision basis was recorded.", adjudicator.state));
  renderFindingStack($("#adjudicator-findings"), adjudicator.findings, "model", adjudicator.state);
  $("#adjudicator-coverage").textContent = stringify(adjudicator.coverage || {});
  $("#adjudicator-evidence-requests").textContent = stringify(adjudicator.evidence_requests || []);

  const edits = clear($("#edit-list"));
  for (const edit of adjudicator.edits || []) {
    const card = node("article", { className: "record-card edit-card related-record", attrs: { tabindex: "0" }, dataset: { ...relatedDataset(edit.source_unit_ids), editId: edit.edit_id } }, [node("code", { text: edit.old || "" }), node("span", { text: "→" }), node("code", { text: edit.new || "" }), node("p", { text: edit.reason || "No reason recorded" })]);
    card.addEventListener("click", () => {
      const annotation = state.reviewIndex?.byEdit.get(edit.edit_id);
      selectReviewTarget(annotation ? targetFromAnnotation(annotation) : {
        id: edit.edit_id,
        type: "adjudicator_edit",
        sourceUnitIds: edit.source_unit_ids || [],
        findingIds: [],
        evidenceIds: edit.evidence_ids || [],
        editIds: [edit.edit_id],
        issueIds: [],
        label: edit.reason || "Adjudicator edit",
        decisionTrailId: "decision-adjudicator",
        raw: edit,
      }, { scroll: true, focusIssues: true });
    });
    edits.append(card);
  }
  if (!(adjudicator.edits || []).length) edits.append(emptyState(adjudicator.available ? "No edits were applied." : "Edits unavailable.", adjudicator.state));
  renderFindingStack($("#unresolved-list"), adjudicator.unresolved_issues, "model", adjudicator.state);
  renderFindingStack($("#human-review-list"), adjudicator.human_review_requests, "model", adjudicator.state);
}

function evidenceResult(result) {
  const unitId = result.source_unit_id || result.provenance?.source_unit_id;
  const card = node("div", { className: "evidence-result related-record", dataset: relatedDataset(unitId ? [unitId] : []) });
  card.append(node("p", { text: result.text || result.match || result.reference || result.token || "Structured result" }));
  card.append(node("pre", { text: stringify(result) }));
  return card;
}

function renderEvidence(view) {
  const list = clear($("#evidence-list"));
  for (const receipt of view.evidence.receipts || []) {
    const request = receipt.request || {};
    const grade = receipt.grade || "?";
    const card = node("details", { className: "receipt-card related-record", dataset: { ...relatedDataset(receipt.source_unit_ids), evidenceId: receipt.evidence_id } });
    card.append(node("summary", {}, [node("div", { className: "receipt-heading" }, [node("div", {}, [node("h4", { text: request.query || receipt.source_type || "Evidence receipt" }), node("p", { className: "provenance-line", text: `${receipt.evidence_id} · ${humanize(receipt.status)} · ${humanize(receipt.source_type)}` })]), node("span", { className: `evidence-grade grade-${String(grade).toLowerCase()}`, text: grade })])]));
    const body = node("div", { className: "receipt-body" }, [node("p", { text: request.reason || "Request rationale not recorded." })]);
    for (const result of receipt.results || []) body.append(evidenceResult(result));
    if (!(receipt.results || []).length) body.append(emptyState("This receipt has no retrieved results.", receipt.status));
    card.append(body);
    list.append(card);
  }
  if (!(view.evidence.receipts || []).length) list.append(emptyState("No evidence receipts are available."));
}

function renderProvenance(view) {
  const final = clear($("#final-translation"));
  if (view.final.available && view.final.translation) {
    final.classList.add("annotated-text");
    renderAnnotatedText(final, view.final.translation, annotationsForMachineText(), { preferReplacement: true });
  } else {
    final.append(emptyState("No complete machine final is available.", view.final.state));
  }
  const diff = clear($("#translation-diff"));
  for (const segment of view.final.diff || []) {
    const tag = segment.kind === "delete" ? "del" : segment.kind === "insert" ? "ins" : "span";
    diff.append(node(tag, { text: segment.text }));
  }
  $("#final-method").textContent = view.final.base_witness
    ? `Witness ${String(view.final.base_witness).toUpperCase()} + ${view.final.applied_edit_count} validated edit${view.final.applied_edit_count === 1 ? "" : "s"}`
    : "Reconstruction method unavailable";
  const mappings = clear($("#source-mappings"));
  for (const [index, mapping] of (view.final.source_mappings || []).entries()) {
    mappings.append(node("article", { className: "record-card" }, [
      node("h4", { text: `Mapping ${index + 1}` }),
      node("pre", { text: stringify(mapping) }),
    ]));
  }
  if (!(view.final.source_mappings || []).length) mappings.append(emptyState(view.final.mapping_available ? "No mappings were returned." : "Source mappings were not persisted for this machine final."));
  const runs = clear($("#run-details-body"));
  for (const stage of view.run_details || []) {
    const card = node("details", { className: "section-card stage-card" });
    card.append(node("summary", {}, [node("div", { className: "stage-heading" }, [node("h3", { text: humanize(stage.stage) }), pill(stage.state, `severity-pill ${statusClass(stage.state)}`)])]));
    card.append(node("div", { className: "stage-meta" }, [node("span", { text: `${stage.provider || "no provider"} · ${stage.model || "deterministic/no model"}` }), node("span", { text: `elapsed ${stage.elapsed_seconds ?? "—"}s` }), node("span", { text: `artifact ${compactId(stage.artifact_id)}` }), node("span", { text: `history ${stage.history_records}` })]));
    card.append(node("pre", { text: stringify({ prompt_version: stage.prompt_version, prompt_digest: stage.prompt_digest, input_digest: stage.input_digest, model_options: stage.model_options, dependencies: stage.dependencies, provider_attempts: stage.provider_attempts, input_budget: stage.input_budget, error: stage.error }) }));
    if (stage.raw_response !== null && stage.raw_response !== undefined) card.append(node("details", {}, [node("summary", { text: "Raw persisted model response" }), node("pre", { text: String(stage.raw_response) })]));
    runs.append(card);
  }
}

function renderArtifactErrors(view) {
  const errors = view.artifact_errors || [];
  const witnessWarnings = (view.witnesses || []).filter((witness) => witness.validation_recorded && witness.eligible_as_adjudicator_base !== true).map((witness) => `${witness.label} invalid/incomplete`);
  const missingUnits = view.verification?.missing_source_unit_ids || [];
  const coverageWarnings = [
    view.witness_quorum?.mode === "degraded" ? `Witness quorum degraded (${humanize(view.witness_quorum.quorum)})` : null,
    view.witness_quorum?.recorded && view.witness_quorum?.automatic_acceptance_allowed === false ? "Automatic acceptance disabled" : null,
    view.verification?.coverage_assertion === false ? "Final coverage not complete" : null,
    missingUnits.length ? `${missingUnits.length} source unit${missingUnits.length === 1 ? "" : "s"} missing final coverage` : null,
    view.final?.mapping_available ? null : "Final source mappings not persisted",
  ].filter(Boolean);
  const warnings = [...errors.map((error) => error.message || "Malformed artifact"), ...witnessWarnings, ...coverageWarnings];
  const alert = $("#artifact-alert");
  alert.hidden = !warnings.length;
  alert.textContent = warnings.length ? warnings.join(" · ") : "";
}

function renderView(view) {
  state.view = view;
  state.selectedUnit = null;
  state.selectedReviewTarget = null;
  state.reviewIndex = buildReviewIndex(view);
  const chunk = view.chunk;
  $("#chunk-kicker").textContent = `Book ${chunk.book ?? "—"} · PL ${chunk.pl_start || "—"}–${chunk.pl_end || "—"} · ${chunk.source_unit_count} source units`;
  $("#chunk-title").textContent = `Edit chunk · ${humanize(chunk.final_status)}`;
  $("#chunk-id").textContent = chunk.chunk_id;
  const status = $("#final-status");
  status.textContent = humanize(chunk.final_status);
  status.className = `status-badge ${statusClass(chunk.final_status)}`;
  $("#previous-chunk").disabled = !chunk.navigation.previous;
  $("#next-chunk").disabled = !chunk.navigation.next;
  $("#previous-chunk").onclick = () => chunk.navigation.previous && loadChunk(chunk.navigation.previous);
  $("#next-chunk").onclick = () => chunk.navigation.next && loadChunk(chunk.navigation.next);
  renderMetrics(chunk.counts || {});
  renderSource(view);
  loadEditorialState(view);
  renderWitnesses(view);
  renderAdjudicator(view);
  renderEvidence(view);
  renderAnalysis(view);
  renderProvenance(view);
  renderArtifactErrors(view);
  renderLayerControls();
  applySelection();
  showContent();
}

async function loadChunk(chunkId, { skipDirtyCheck = false } = {}) {
  if (!chunkId) return;
  if (!skipDirtyCheck && state.dirty && chunkId !== state.currentChunkId && !window.confirm("Discard unsaved editorial changes and open another chunk?")) return;
  showLoading();
  try {
    const view = await requestJson(`/api/chunks/${encodeURIComponent(chunkId)}`);
    state.currentChunkId = chunkId;
    renderView(view);
    renderChunkList();
    history.replaceState(null, "", `#${encodeURIComponent(chunkId)}`);
  } catch (error) { showError(error); }
}

async function loadApplication({ preserveChunk = true } = {}) {
  if (state.dirty && preserveChunk && !window.confirm("Reload and discard unsaved editorial changes?")) return;
  showLoading();
  try {
    state.overview = await requestJson("/api/chunks");
    const hashChunk = decodeURIComponent(location.hash.replace(/^#/, ""));
    const requested = preserveChunk && state.currentChunkId ? state.currentChunkId : hashChunk || state.overview.chunks?.[0]?.chunk_id;
    renderChunkList();
    if (!requested) throw new Error("No Book I chunks are available. Run preprocessing first.");
    await loadChunk(requested, { skipDirtyCheck: true });
  } catch (error) { showError(error); }
}

for (const button of $$(".mini-filter")) button.addEventListener("click", () => {
  state.issueFilter = button.dataset.issueFilter;
  for (const item of $$(".mini-filter")) item.classList.toggle("active", item === button);
  renderResolutionList();
});
$("#editor-translation").addEventListener("input", () => { setDirty(true); renderEditorialPreview(); applySelection(); });
$("#clear-unit").addEventListener("click", () => selectUnit(null));
$("#clear-selection").addEventListener("click", () => selectReviewTarget(null));
$("#save-draft").addEventListener("click", () => saveRevision("draft"));
$("#approve-revision").addEventListener("click", () => saveRevision("approved"));
$("#refresh-button").addEventListener("click", () => loadApplication({ preserveChunk: true }));
$("#retry-button").addEventListener("click", () => loadApplication({ preserveChunk: true }));
$("#chunk-search").addEventListener("input", renderChunkList);
$("#show-all-layers").addEventListener("click", () => {
  for (const key of Object.keys(state.layers)) state.layers[key] = true;
  renderLayerControls();
  rerenderReviewSurfaces();
});
$("#hide-all-layers").addEventListener("click", () => {
  for (const key of Object.keys(state.layers)) state.layers[key] = false;
  renderLayerControls();
  rerenderReviewSurfaces();
});
$("#mode-review").addEventListener("click", () => {
  state.reviewMode = "review";
  $("#mode-review").classList.add("active");
  $("#mode-clean").classList.remove("active");
  rerenderReviewSurfaces();
});
$("#mode-clean").addEventListener("click", () => {
  state.reviewMode = "clean";
  $("#mode-clean").classList.add("active");
  $("#mode-review").classList.remove("active");
  rerenderReviewSurfaces();
});
$("#previous-issue").addEventListener("click", () => navigateIssue(-1));
$("#next-issue").addEventListener("click", () => navigateIssue(1));
$("#toggle-machine").addEventListener("click", () => {
  const reference = $(".machine-reference");
  const collapsed = reference.classList.toggle("collapsed");
  $("#toggle-machine").textContent = collapsed ? "Expand" : "Collapse";
  $("#toggle-machine").setAttribute("aria-expanded", collapsed ? "false" : "true");
});
window.addEventListener("beforeunload", (event) => { if (state.dirty) event.preventDefault(); });

loadApplication({ preserveChunk: false });
