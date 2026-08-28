export function unique<T>(values: T[] | null | undefined): T[] {
  return Array.from(new Set((values || []).filter(Boolean)));
}

export function containsAny(left: string[] | null | undefined, right: string[] | null | undefined): boolean {
  const rightSet = new Set(right || []);
  return (left || []).some((item) => rightSet.has(item));
}

export function humanize(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function statusClass(value: unknown): string {
  return String(value || 'incomplete').toLowerCase().replaceAll(' ', '_');
}

export function evidenceStatusClass(value: unknown): string {
  return String(value || 'unavailable').toLowerCase().replaceAll(/[_\s]+/g, '-');
}

export function compactId(value: unknown): string {
  if (!value) return '—';
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-6)}` : text;
}

export function stringify(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function primaryId(record: Record<string, unknown> | null | undefined): string | null {
  if (!record) return null;
  return (
    record.issue_id || record.finding_id || record.request_id || record.edit_id || record.evidence_id || record.flag_id || record.entry_id || null
  ) as string | null;
}

export function relatedDataset(ids: string[] | null | undefined): { unitIds: string } {
  return { unitIds: (ids || []).join(' ') };
}