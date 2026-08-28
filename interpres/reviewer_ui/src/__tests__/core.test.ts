import { describe, it, expect } from 'vitest';
import { buildReviewIndex, annotationRange, targetMatchesAnnotation, targetFromAnnotation } from '../lib/annotations';
import { textDiff } from '../lib/mappings';
import { markdownToSafeHtml } from '../lib/markdown';
import { humanize } from '../lib/formatting';

describe('annotations', () => {
  const view = {
    issues: {
      items: [
        { issue_id: 'issue-1', origin: 'deterministic', source_unit_ids: ['unit-1'], evidence_ids: [], message: 'Test issue', type: 'test', severity: 'high', status: 'open', english: null, latin: null, source_record_id: 'finding-1', reusable_eligible: false },
      ],
    },
    adjudicator: { edits: [], findings: [], decision_basis: [], coverage: {}, evidence_requests: [], unresolved_issues: [], human_review_requests: [] },
    source: { units: [{ source_unit_id: 'unit-1', text: 'Hello world' }] },
    final: { source_mappings: [] },
    verification: { incomplete_stages: [], missing_source_unit_ids: [] },
  };

  it('builds review index from view', () => {
    const index = buildReviewIndex(view as unknown as Record<string, unknown>);
    expect(index.annotations).toHaveLength(1);
    expect(index.annotations[0].id).toBe('issue-1');
    expect(index.byUnit.has('unit-1')).toBe(true);
  });

  it('computes annotation range from offset', () => {
    const annotation = { raw: { english_start_offset: 0, english_end_offset: 5 }, textQuote: 'Hello', startQuote: null, endQuote: null, replacementQuote: null };
    const range = annotationRange('Hello world', annotation);
    expect(range).toEqual({ start: 0, end: 5 });
  });

  it('matches target to annotation', () => {
    const annotation = { id: 'issue-1', sourceUnitIds: ['unit-1'], issueIds: ['issue-1'], findingIds: [], evidenceIds: [], editIds: [] };
    expect(targetMatchesAnnotation({ id: 'issue-1', sourceUnitIds: [], issueIds: [], findingIds: [], evidenceIds: [], editIds: [] }, annotation)).toBe(true);
    expect(targetMatchesAnnotation({ id: 'other', sourceUnitIds: [], issueIds: [], findingIds: [], evidenceIds: [], editIds: [] }, annotation)).toBe(false);
  });
});

describe('mappings', () => {
  it('computes text diff', () => {
    const diff = textDiff('Hello world', 'Hello there');
    expect(diff.some((d) => d.kind === 'equal' && d.text.includes('Hello'))).toBe(true);
    expect(diff.some((d) => d.kind === 'delete' && d.text.includes('world'))).toBe(true);
    expect(diff.some((d) => d.kind === 'insert' && d.text.includes('there'))).toBe(true);
  });
});

describe('markdown', () => {
  it('renders safe markdown', () => {
    const html = markdownToSafeHtml('<script>alert(1)</script> **bold**');
    expect(html).not.toContain('<script>');
    expect(html).toContain('<strong>bold</strong>');
  });
});

describe('formatting', () => {
  it('humanizes values', () => {
    expect(humanize('hello_world')).toBe('Hello World');
    expect(humanize(null)).toBe('Not recorded');
  });
});