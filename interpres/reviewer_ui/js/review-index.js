import { findQuoteRange, humanize, unique } from "./dom.js";

export function annotationRecord({ id, type, layer, sourceUnitIds = [], findingIds = [], evidenceIds = [], editIds = [], issueIds = [], textQuote = null, startQuote = null, endQuote = null, replacementQuote = null, label = null, decisionTrailId = null, raw = null }) {
  return { id, type, layer, sourceUnitIds: unique(sourceUnitIds), findingIds: unique(findingIds), evidenceIds: unique(evidenceIds), editIds: unique(editIds), issueIds: unique(issueIds), textQuote, startQuote, endQuote, replacementQuote, label, decisionTrailId, raw };
}

export function buildReviewIndex(view) {
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
    const layer = issue.origin === "adjudicator" ? "adjudicator" : issue.origin;
    const quote = issue.english && typeof issue.english === "string" && !issue.english.startsWith("witness_") ? issue.english : null;
    const trail = ["deterministic", "prosecutor"].includes(issue.origin) ? "decision-challenges"
      : ["adjudicator", "unresolved", "human_review"].includes(issue.origin) ? "decision-adjudicator"
      : issue.origin === "witness_disagreement" ? "decision-witnesses" : null;
    add(annotationRecord({ id: issue.issue_id, type: "issue", layer, sourceUnitIds: issue.source_unit_ids, findingIds: [issue.source_record_id], evidenceIds: issue.evidence_ids, issueIds: [issue.issue_id], textQuote: quote, label: issue.message || issue.type || issue.origin, decisionTrailId: trail, raw: issue }));
  }
  for (const edit of view.adjudicator?.edits || []) {
    add(annotationRecord({ id: edit.edit_id, type: "adjudicator_edit", layer: "adjudicator_edit", sourceUnitIds: edit.source_unit_ids, editIds: [edit.edit_id], evidenceIds: edit.evidence_ids, textQuote: edit.old, replacementQuote: edit.new, label: edit.reason || "Adjudicator edit", decisionTrailId: "decision-adjudicator", raw: edit }));
  }
  for (const unit of view.source?.units || []) {
    const mapping = mappingForUnit(unit.source_unit_id, view.final?.source_mappings || []);
    const quote = mappingQuote(mapping);
    if (quote) add(annotationRecord({ id: `source-map:${unit.source_unit_id}`, type: "source_mapping", layer: "source_mapping", sourceUnitIds: [unit.source_unit_id], textQuote: quote, label: `${unit.source_unit_id} final source mapping`, decisionTrailId: "decision-final", raw: mapping }));
  }
  for (const item of view.verification?.incomplete_stages || []) {
    if (item.state !== "complete") add(annotationRecord({ id: `verification:${item.stage}`, type: "verification", layer: "verification", sourceUnitIds: view.source?.units?.map((unit) => unit.source_unit_id), label: `${humanize(item.stage)} is ${humanize(item.state)}`, decisionTrailId: "decision-verification", raw: item }));
  }
  for (const unitId of view.verification?.missing_source_unit_ids || []) {
    add(annotationRecord({ id: `coverage:${unitId}`, type: "verification", layer: "verification", sourceUnitIds: [unitId], label: "Coverage missing for this source unit", decisionTrailId: "decision-verification", raw: { source_unit_id: unitId } }));
  }
  return { annotations, byIssue, byUnit, byEdit };
}

export function mappingForUnit(unitId, mappings = []) {
  return mappings.find((mapping) => String(mapping.source_unit_id || "") === String(unitId));
}
export function mappingQuote(mapping) {
  return mapping?.english_start_quote || mapping?.english_quote || mapping?.text || mapping?.translation || null;
}
export function annotationRange(text, annotation, options = {}) {
  const source = String(text || "");
  if (!source || !annotation) return null;
  const editorialTarget = annotation.raw?.target;
  if (options.editorial && editorialTarget?.surface === "editorial") {
    const start = editorialTarget.start;
    const end = editorialTarget.end;
    if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= source.length && source.slice(start, end) === editorialTarget.selected_text) return { start, end };
    return null;
  }
  const startOffset = annotation.raw?.english_start_offset;
  const endOffset = annotation.raw?.english_end_offset;
  if (Number.isInteger(startOffset) && Number.isInteger(endOffset) && startOffset >= 0 && endOffset > startOffset && endOffset <= source.length) return { start: startOffset, end: endOffset };
  const startQuote = annotation.startQuote || annotation.raw?.english_start_quote;
  const endQuote = annotation.endQuote || annotation.raw?.english_end_quote;
  if (startQuote && endQuote) {
    const start = source.indexOf(String(startQuote));
    const endStart = start >= 0 ? source.indexOf(String(endQuote), start) : -1;
    if (endStart >= 0) return { start, end: endStart + String(endQuote).length };
  }
  return findQuoteRange(source, options.preferReplacement ? annotation.replacementQuote || annotation.textQuote : annotation.textQuote || annotation.replacementQuote);
}
