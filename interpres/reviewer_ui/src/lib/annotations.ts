export function annotationRecord(params: {
  id: string;
  type: string;
  layer: string;
  sourceUnitIds?: string[];
  findingIds?: string[];
  evidenceIds?: string[];
  editIds?: string[];
  issueIds?: string[];
  textQuote?: string | null;
  startQuote?: string | null;
  endQuote?: string | null;
  replacementQuote?: string | null;
  label?: string | null;
  decisionTrailId?: string | null;
  raw?: Record<string, unknown>;
}): Record<string, unknown> {
  return {
    id: params.id,
    type: params.type,
    layer: params.layer,
    sourceUnitIds: unique(params.sourceUnitIds || []),
    findingIds: unique(params.findingIds || []),
    evidenceIds: unique(params.evidenceIds || []),
    editIds: unique(params.editIds || []),
    issueIds: unique(params.issueIds || []),
    textQuote: params.textQuote ?? null,
    startQuote: params.startQuote ?? null,
    endQuote: params.endQuote ?? null,
    replacementQuote: params.replacementQuote ?? null,
    label: params.label ?? null,
    decisionTrailId: params.decisionTrailId ?? null,
    raw: params.raw ?? {},
  };
}

export function annotationsForMachineText(view: Record<string, unknown>): Record<string, unknown>[] {
  return [...((view as { reviewIndex?: { annotations?: Record<string, unknown>[] } }).reviewIndex?.annotations || [])];
}

export function buildReviewIndex(view: Record<string, unknown>): {
  annotations: Record<string, unknown>[];
  byIssue: Map<string, Record<string, unknown>>;
  byUnit: Map<string, Record<string, unknown>[]>;
  byEdit: Map<string, Record<string, unknown>>;
} {
  const annotations: Record<string, unknown>[] = [];
  const byIssue = new Map<string, Record<string, unknown>>();
  const byUnit = new Map<string, Record<string, unknown>[]>();
  const byEdit = new Map<string, Record<string, unknown>>();

  const add = (record: Record<string, unknown>) => {
    annotations.push(record);
    for (const id of record.sourceUnitIds as string[]) {
      const existing = byUnit.get(id) || [];
      existing.push(record);
      byUnit.set(id, existing);
    }
    for (const id of record.issueIds as string[]) byIssue.set(id, record);
    for (const id of record.editIds as string[]) byEdit.set(id, record);
  };

  const issues = (view.issues as { items?: Record<string, unknown>[] } | null)?.items || [];
  for (const issue of issues) {
    const origin = issue.origin as string;
    const layer = origin === 'adjudicator' ? 'adjudicator' : origin;
    const english = issue.english as string | null;
    const quote = english && typeof english === 'string' && !english.startsWith('witness_') ? english : null;
    const trail =
      ['deterministic', 'prosecutor'].includes(origin) ? 'decision-challenges'
      : ['adjudicator', 'unresolved', 'human_review'].includes(origin) ? 'decision-adjudicator'
      : origin === 'witness_disagreement' ? 'decision-witnesses'
      : null;
    add(annotationRecord({
      id: issue.issue_id as string,
      type: 'issue',
      layer,
      sourceUnitIds: (issue.source_unit_ids as string[]) || [],
      findingIds: [(issue.source_record_id as string)],
      evidenceIds: (issue.evidence_ids as string[]) || [],
      issueIds: [(issue.issue_id as string)],
      textQuote: quote,
      label: (issue.message || issue.type || issue.origin) as string,
      decisionTrailId: trail,
      raw: issue,
    }));
    if (((issue.evidence_ids as string[]) || []).length && quote) {
      add(annotationRecord({
        id: `evidence-link:${issue.issue_id as string}`,
        type: 'evidence',
        layer: 'evidence',
        sourceUnitIds: (issue.source_unit_ids as string[]) || [],
        findingIds: issue.source_record_id ? [String(issue.source_record_id)] : [],
        evidenceIds: (issue.evidence_ids as string[]) || [],
        issueIds: issue.issue_id ? [String(issue.issue_id)] : [],
        textQuote: quote,
        label: `Evidence linked · ${String(issue.message || issue.type || issue.origin)}`,
        decisionTrailId: 'decision-evidence',
        raw: issue,
      }));
    }
  }

  const adjudicator = view.adjudicator as { edits?: Record<string, unknown>[] } | null;
  for (const edit of adjudicator?.edits || []) {
    add(annotationRecord({
      id: edit.edit_id as string,
      type: 'adjudicator_edit',
      layer: 'adjudicator_edit',
      sourceUnitIds: (edit.source_unit_ids as string[]) || [],
      editIds: [(edit.edit_id as string)],
      evidenceIds: (edit.evidence_ids as string[]) || [],
      textQuote: edit.old as string,
      replacementQuote: edit.new as string,
      label: (edit.reason || 'Adjudicator edit') as string,
      decisionTrailId: 'decision-adjudicator',
      raw: edit,
    }));
  }

  const sourceUnits = (view.source as { units?: { source_unit_id: string }[] } | null)?.units || [];
  const finalMappings = (view.final as { source_mappings?: Record<string, unknown>[] } | null)?.source_mappings || [];
  for (const unit of sourceUnits) {
    const mapping = mappingForUnit(unit.source_unit_id as string, finalMappings);
    const quote = mappingQuote(mapping);
    if (quote) {
      add(annotationRecord({
        id: `source-map:${unit.source_unit_id}`,
        type: 'source_mapping',
        layer: 'source_mapping',
        sourceUnitIds: [unit.source_unit_id as string],
        textQuote: quote,
        label: `${unit.source_unit_id} final source mapping`,
        decisionTrailId: 'decision-final',
        raw: mapping,
      }));
    }
  }

  const verification = view.verification as { incomplete_stages?: Record<string, unknown>[]; missing_source_unit_ids?: string[] } | null;
  for (const item of verification?.incomplete_stages || []) {
    if (item.state !== 'complete') {
      add(annotationRecord({
        id: `verification:${item.stage}`,
        type: 'verification',
        layer: 'verification',
        sourceUnitIds: (sourceUnits || []).map((u) => u.source_unit_id as string),
        label: `${humanize(item.stage)} is ${humanize(item.state)}`,
        decisionTrailId: 'decision-verification',
        raw: item,
      }));
    }
  }
  for (const unitId of verification?.missing_source_unit_ids || []) {
    add(annotationRecord({
      id: `coverage:${unitId}`,
      type: 'verification',
      layer: 'verification',
      sourceUnitIds: [unitId],
      label: 'Coverage missing for this source unit',
      decisionTrailId: 'decision-verification',
      raw: { source_unit_id: unitId },
    }));
  }

  return { annotations, byIssue, byUnit, byEdit };
}

export function mappingForUnit(unitId: string, mappings: Record<string, unknown>[]): Record<string, unknown> | undefined {
  return mappings.find((mapping) => String(mapping.source_unit_id || '') === String(unitId));
}

export function mappingQuote(mapping: Record<string, unknown> | undefined): string | null {
  if (!mapping) return null;
  return (mapping.english_start_quote || mapping.english_quote || mapping.text || mapping.translation) as string | null;
}

export function annotationRange(
  text: string,
  annotation: Record<string, unknown>,
  options: { preferReplacement?: boolean; editorial?: boolean } = {},
): { start: number; end: number } | null {
  const source = String(text || '');
  if (!source || !annotation) return null;
  const raw = annotation.raw as Record<string, unknown> | undefined;
  if (options.editorial && raw?.target && typeof raw.target === 'object') {
    const target = raw.target as { surface?: string; start?: number; end?: number; selected_text?: string };
    if (target.surface === 'editorial') {
      const start = target.start as number;
      const end = target.end as number;
      const selectedText = target.selected_text as string;
      if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= source.length && source.slice(start, end) === selectedText) {
        return { start, end };
      }
      return null;
    }
  }
  const startOffset = raw?.english_start_offset as number | undefined;
  const endOffset = raw?.english_end_offset as number | undefined;
  if (Number.isInteger(startOffset) && Number.isInteger(endOffset) && startOffset >= 0 && endOffset > startOffset && endOffset <= source.length) {
    return { start: startOffset, end: endOffset };
  }
  const finalStartOffset = raw?.final_start_offset as number | undefined;
  const finalEndOffset = raw?.final_end_offset as number | undefined;
  if (Number.isInteger(finalStartOffset) && Number.isInteger(finalEndOffset) && finalStartOffset! >= 0 && finalEndOffset! > finalStartOffset! && finalEndOffset! <= source.length) {
    return { start: finalStartOffset!, end: finalEndOffset! };
  }
  const startQuote = (annotation.startQuote || raw?.english_start_quote) as string | undefined;
  const endQuote = (annotation.endQuote || raw?.english_end_quote) as string | undefined;
  if (startQuote && endQuote) {
    const start = source.indexOf(String(startQuote));
    const endStart = start >= 0 ? source.indexOf(String(endQuote), start) : -1;
    if (endStart >= 0) return { start, end: endStart + String(endQuote).length };
  }
  return findQuoteRange(source, options.preferReplacement ? (annotation.replacementQuote || annotation.textQuote) as string : (annotation.textQuote || annotation.replacementQuote) as string);
}

export function findQuoteRange(text: string, quote: string | null, from = 0): { start: number; end: number } | null {
  const source = String(text || '');
  const needle = String(quote || '').trim();
  if (!source || !needle) return null;
  const direct = source.indexOf(needle, from);
  return direct >= 0 ? { start: direct, end: direct + needle.length } : null;
}

export function targetMatchesAnnotation(target: { id?: string; sourceUnitIds?: string[]; findingIds?: string[]; evidenceIds?: string[]; editIds?: string[]; issueIds?: string[] } | null | undefined, annotation: Record<string, unknown> | null | undefined): boolean {
  if (!target || !annotation) return false;
  return target.id === annotation.id
    || containsAny(target.sourceUnitIds, annotation.sourceUnitIds as string[])
    || containsAny(target.issueIds, annotation.issueIds as string[])
    || containsAny(target.findingIds, annotation.findingIds as string[])
    || containsAny(target.evidenceIds, annotation.evidenceIds as string[])
    || containsAny(target.editIds, annotation.editIds as string[]);
}

export function targetFromAnnotation(annotation: Record<string, unknown>): {
  id: string;
  type: string;
  sourceUnitIds: string[];
  findingIds: string[];
  evidenceIds: string[];
  editIds: string[];
  issueIds: string[];
  decisionTrailId: string | null;
  label: string;
  raw: Record<string, unknown>;
} {
  return {
    id: annotation.id as string,
    type: annotation.type as string,
    sourceUnitIds: (annotation.sourceUnitIds as string[]) || [],
    findingIds: (annotation.findingIds as string[]) || [],
    evidenceIds: (annotation.evidenceIds as string[]) || [],
    editIds: (annotation.editIds as string[]) || [],
    issueIds: (annotation.issueIds as string[]) || [],
    decisionTrailId: (annotation.decisionTrailId as string) ?? null,
    label: (annotation.label as string) || '',
    raw: (annotation.raw as Record<string, unknown>) || {},
  };
}

export function targetFromUnit(unitId: string, reviewIndex: { byUnit: Map<string, { findingIds: string[]; evidenceIds: string[]; editIds: string[]; issueIds: string[] }[]> } | null): {
  id: string;
  type: 'source_unit';
  sourceUnitIds: string[];
  findingIds: string[];
  evidenceIds: string[];
  editIds: string[];
  issueIds: string[];
  decisionTrailId: string | null;
  label: string;
  raw: Record<string, unknown>;
} {
  const records = reviewIndex?.byUnit.get(unitId) || [];
  return {
    id: unitId,
    type: 'source_unit',
    sourceUnitIds: [unitId],
    findingIds: unique(records.flatMap((item) => item.findingIds)),
    evidenceIds: unique(records.flatMap((item) => item.evidenceIds)),
    editIds: unique(records.flatMap((item) => item.editIds)),
    issueIds: unique(records.flatMap((item) => item.issueIds)),
    decisionTrailId: null,
    label: unitId,
    raw: { source_unit_id: unitId },
  };
}

function unique<T>(values: T[]): T[] {
  return Array.from(new Set(values));
}

function containsAny(left: string[], right: string[]): boolean {
  const rightSet = new Set(right);
  return left.some((item) => rightSet.has(item));
}

function humanize(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function validateAnnotationSpan(annotation: Record<string, unknown>, editorialText: string): 'valid' | 'stale' {
  const target = annotation?.target as { surface?: string; start?: number; end?: number; selected_text?: string } | undefined;
  if (!target || target.surface !== 'editorial') return 'stale';
  const { start, end, selected_text } = target;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > editorialText.length) return 'stale';
  return editorialText.slice(start, end) === selected_text ? 'valid' : 'stale';
}

export function annotationFromSelection(textarea: HTMLTextAreaElement, params: { kind: string; text: string; sourceUnitIds?: string[] }): Record<string, unknown> {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selectedText = textarea.value.slice(start, end);
  if (!selectedText || start === end) throw new Error('Select editorial text before adding an annotation.');
  const now = new Date().toISOString();
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return {
    annotation_id: `annotation-${random}`,
    kind: params.kind,
    text: String(params.text || '').trim(),
    target: { surface: 'editorial', start, end, selected_text: selectedText },
    source_unit_ids: Array.from(new Set((params.sourceUnitIds || []).filter(Boolean).map(String))),
    created_at: now,
    updated_at: now,
    span_status: 'valid' as const,
  };
}

export function editorialAnnotationRecord(annotation: Record<string, unknown>): Record<string, unknown> {
  return {
    id: annotation.annotation_id,
    type: 'editorial_annotation',
    layer: 'editorial_note',
    sourceUnitIds: (annotation.source_unit_ids as string[]) || [],
    findingIds: [],
    evidenceIds: [],
    editIds: [],
    issueIds: [],
    textQuote: (annotation.target as { selected_text?: string } | undefined)?.selected_text || null,
    label: annotation.text as string,
    decisionTrailId: null,
    raw: annotation,
  };
}
