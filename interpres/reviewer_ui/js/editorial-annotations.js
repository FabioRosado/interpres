export function validateAnnotationSpan(annotation, editorialText) {
  const target = annotation?.target;
  if (!target || target.surface !== "editorial") return "stale";
  const { start, end, selected_text: selectedText } = target;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > editorialText.length) return "stale";
  return editorialText.slice(start, end) === selectedText ? "valid" : "stale";
}

export function annotationFromSelection(textarea, { kind, text, sourceUnitIds = [] }) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selectedText = textarea.value.slice(start, end);
  if (!selectedText || start === end) throw new Error("Select editorial text before adding an annotation.");
  const now = new Date().toISOString();
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return {
    annotation_id: `annotation-${random}`,
    kind,
    text: String(text || "").trim(),
    target: { surface: "editorial", start, end, selected_text: selectedText },
    source_unit_ids: Array.from(new Set(sourceUnitIds.filter(Boolean).map(String))),
    created_at: now,
    updated_at: now,
    span_status: "valid",
  };
}

export function editorialAnnotationRecord(annotation) {
  return {
    id: annotation.annotation_id,
    type: "editorial_annotation",
    layer: "editorial_note",
    sourceUnitIds: annotation.source_unit_ids || [],
    findingIds: [],
    evidenceIds: [],
    editIds: [],
    issueIds: [],
    textQuote: annotation.target?.selected_text || null,
    label: annotation.text,
    decisionTrailId: null,
    raw: annotation,
  };
}
