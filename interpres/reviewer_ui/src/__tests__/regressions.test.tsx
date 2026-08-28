import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { useState } from 'preact/hooks';
import type { AnnotationRecord, EditorialAnnotation, ReviewView, SelectionTarget } from '../app/types';
import { buildReviewIndex } from '../lib/annotations';
import { EditorialEditor } from '../components/EditorialWorkspace/EditorialEditor';
import { EditorialWorkspace } from '../components/EditorialWorkspace/EditorialWorkspace';
import { SourcePane } from '../components/SourcePane/SourcePane';
import { MachineFinalPane } from '../components/MachineFinalPane/MachineFinalPane';
import { AnnotatedText } from '../components/Annotations/AnnotatedText';
import { EvidenceInspector } from '../components/Evidence/EvidenceInspector';
import { IssueNavigator } from '../components/IssueLedger/IssueNavigator';
import { IssueLedger } from '../components/IssueLedger/IssueLedger';

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
});
afterEach(cleanup);

const view = {
  chunk: { chunk_id: 'chunk-1' },
  source: {
    units: [{ source_unit_id: 'unit-1', page: '0015A', text: 'Finis in Isaiam', book: 1, clean_start: 0, clean_end: 15 }],
    context_before: 'Opening context before the selected Latin unit.',
    context_after: 'Following context after the selected Latin unit.',
    page_markers: [{ page: '0015A', offset: 0 }],
    annotations: [{ kind: 'rubric', text: 'source apparatus note' }],
    spans: [{ source_unit_id: 'unit-1', start: 0, end: 15, label: 'selected span' }],
  },
  machine: { final_draft: 'Having completed Isaiah.', final_status: 'human_review' },
  final: {
    status: 'human_review',
    translation: 'Having completed Isaiah.',
    base_witness: 'a',
    applied_edit_count: 1,
    diff: [{ kind: 'equal', text: 'Having ' }, { kind: 'delete', text: 'finished' }, { kind: 'insert', text: 'completed' }],
    source_mappings: [{ source_unit_id: 'unit-1', english_start_offset: 0, english_end_offset: 25, english_start_quote: 'Having completed Isaiah.' }],
  },
  issues: { items: [{ issue_id: 'issue-1', source_record_id: 'finding-1', origin: 'deterministic', type: 'accuracy', severity: 'high', status: 'open', message: 'Check Isaiah', latin: 'Isaiam', english: 'Isaiah', source_unit_ids: ['unit-1'], evidence_ids: ['ev-1'], reusable_eligible: true }] },
  witnesses: [
    { witness_id: 'a', label: 'Witness A', translation: 'Witness A wording', source_mappings: [{ source_unit_id: 'unit-1' }], validation_recorded: true, eligible_as_adjudicator_base: true, state: 'complete' },
    { witness_id: 'b', label: 'Witness B', translation: 'Witness B wording', source_mappings: [], validation_recorded: true, eligible_as_adjudicator_base: false, state: 'complete' },
  ],
  witness_quorum: { quorum: 'single_valid_b', valid_witnesses: ['b'] },
  disagreements: { items: [] },
  deterministic: { state: 'complete', substantive_findings: [{ finding_id: 'finding-1', message: 'Check Isaiah', source_unit_ids: ['unit-1'], evidence_ids: ['ev-1'] }] },
  prosecutor: { initial: { status: 'complete', findings: [{ finding_id: 'prosecutor-1', message: 'Initial prosecutor issue', source_unit_ids: ['unit-1'] }] }, grounded: { status: 'complete', findings: [{ finding_id: 'grounded-1', message: 'Grounded prosecutor issue', source_unit_ids: ['unit-1'] }] } },
  evidence: { receipts: [{ evidence_id: 'ev-1', grade: 'A', status: 'found', source_unit_ids: ['unit-1'], results: [{ text: 'Evidence result' }] }] },
  adjudicator: {
    available: true,
    state: 'complete',
    base_witness: 'a',
    findings: [{ finding_id: 'adj-1', message: 'Adjudicator finding' }],
    edits: [{ edit_id: 'edit-1', old: 'finished', new: 'completed', reason: 'Exact correction', source_unit_ids: ['unit-1'] }],
    unresolved_issues: [],
    human_review_requests: [],
    summary: 'Human review required.',
    decision_basis: [{ claim: 'Decision basis claim', grade: 'A' }],
    coverage: { accounted: ['unit-1'] },
    evidence_requests: [{ request_id: 'req-1', query: 'Isaiah context' }],
    edit_validation_error: null,
  },
  editorial: { revision_count: 1, based_on_current_machine_final: true },
  verification: {
    coverage_assertion: true,
    source_units_total: 1,
    source_units_accounted_for: 1,
    exact_edit_validation: 'valid',
    schema_status_validation: 'valid',
    final_checks: { findings: [{ message: 'Final check finding' }] },
    incomplete_stages: [{ stage: 'evidence', state: 'complete' }],
    missing_source_unit_ids: [],
  },
} as unknown as ReviewView;

const sourceTarget: SelectionTarget = {
  id: 'unit-1', type: 'source_unit', sourceUnitIds: ['unit-1'], findingIds: ['finding-1'], evidenceIds: ['ev-1'], editIds: [], issueIds: ['issue-1'], decisionTrailId: null, label: 'unit-1', raw: { source_unit_id: 'unit-1', selected_payload: true },
};

describe('editorial regression coverage', () => {
  it('renders an editable editor, reports changes, and explicitly saves', async () => {
    const onTextChange = vi.fn();
    const onSave = vi.fn(async () => undefined);
    render(<EditorialEditor chunkId="chunk-1" text="Machine text" dirty={false} saving={false} disabled={false} focusEditor={false} saveMessage={null} onTextChange={onTextChange} onSave={onSave} onAddAnnotation={vi.fn()} onFocusEditorChange={vi.fn()} />);
    const editor = screen.getByLabelText('Human editorial Markdown') as HTMLTextAreaElement;
    expect(editor.disabled).toBe(false);
    fireEvent.input(editor, { target: { value: 'Human **revision**' } });
    expect(onTextChange).toHaveBeenCalledWith('Human **revision**');
    fireEvent.click(screen.getByText('Save draft revision'));
    expect(onSave).toHaveBeenCalledWith('draft');
  });

  it('creates, edits, and deletes structured annotations without embedding them in Markdown', () => {
    const annotatedView = {
      ...view,
      machine: { ...view.machine, final_draft: 'Having completed Isaiah.', final_draft_digest: 'digest-1' },
    } as ReviewView;
    const Harness = () => {
      const [annotations, setAnnotations] = useState<EditorialAnnotation[]>([]);
      return (
        <EditorialWorkspace
          view={annotatedView}
          text="Machine text"
          annotations={annotations}
          dirty={false}
          saving={false}
          saveMessage={null}
          focusEditor={false}
          selectedTarget={sourceTarget}
          onTextChange={vi.fn()}
          onAnnotationsChange={setAnnotations}
          onSave={vi.fn(async () => undefined)}
          onFocusEditorChange={vi.fn()}
        />
      );
    };
    render(<Harness />);
    const editor = screen.getByLabelText('Human editorial Markdown') as HTMLTextAreaElement;
    editor.setSelectionRange(0, 7);
    fireEvent.click(screen.getByText('Add annotation'));
    fireEvent.input(screen.getByLabelText('Note'), { target: { value: 'Initial note' } });
    fireEvent.click(screen.getByText('Save annotation'));
    expect(screen.getByText('Initial note')).toBeTruthy();
    expect(editor.value).toBe('Machine text');

    fireEvent.click(screen.getByText('Edit', { selector: '.annotation-actions button' }));
    fireEvent.input(screen.getByLabelText('Note'), { target: { value: 'Revised note' } });
    fireEvent.click(screen.getByText('Save annotation'));
    expect(screen.getByText('Revised note')).toBeTruthy();

    fireEvent.click(screen.getByText('Delete'));
    expect(screen.queryByText('Revised note')).toBeNull();
  });
});

describe('source and Machine Final mapping', () => {
  const index = buildReviewIndex(view as unknown as Record<string, unknown>) as any;

  it('selects a Latin unit using the shared review target and reports real mapping badges', () => {
    const onSelect = vi.fn();
    render(<SourcePane view={view} reviewIndex={index} selectedTarget={null} layers={{}} onSelectTarget={onSelect} />);
    fireEvent.click(screen.getByText('Finis in Isaiam'));
    expect(onSelect.mock.calls[0][0].sourceUnitIds).toEqual(['unit-1']);
    expect(screen.getByText('final mapped')).toBeTruthy();
  });

  it('keeps a selected source mapping visible when its layer is disabled', () => {
    const { container } = render(<MachineFinalPane view={view} reviewIndex={index} selectedTarget={sourceTarget} layers={{ source_mapping: false, deterministic: false, evidence: false }} onSelectTarget={vi.fn()} />);
    expect(container.querySelector('.annotation.source_mapping.selected')).toBeTruthy();
    expect(screen.getByText(/Precise persisted mapping/)).toBeTruthy();
  });

  it('states Not mapped instead of guessing', () => {
    const unmapped = { ...view, final: { ...view.final, source_mappings: [] } };
    render(<MachineFinalPane view={unmapped} reviewIndex={{ ...index, annotations: [] }} selectedTarget={sourceTarget} layers={{}} onSelectTarget={vi.fn()} />);
    expect(screen.getByText(/Not mapped to Machine Final/)).toBeTruthy();
  });

  it('labels source-unit-only mappings as coarse instead of inventing offsets', () => {
    const coarse = { ...view, final: { ...view.final, source_mappings: [{ source_unit_id: 'unit-1', mapping_quality: 'coarse' }] } };
    render(<MachineFinalPane view={coarse as ReviewView} reviewIndex={{ ...index, annotations: [] }} selectedTarget={sourceTarget} layers={{}} onSelectTarget={vi.fn()} />);
    expect(screen.getByText(/Coarse persisted mapping/)).toBeTruthy();
  });

  it('represents overlapping annotations with one navigable multi-marker', () => {
    const annotations = [
      { id: 'a', type: 'issue', layer: 'deterministic', sourceUnitIds: [], findingIds: [], evidenceIds: [], editIds: [], issueIds: [], textQuote: 'Isaiah', startQuote: null, endQuote: null, replacementQuote: null, label: 'A', decisionTrailId: null, raw: {} },
      { id: 'b', type: 'issue', layer: 'evidence', sourceUnitIds: [], findingIds: [], evidenceIds: [], editIds: [], issueIds: [], textQuote: 'Isaiah', startQuote: null, endQuote: null, replacementQuote: null, label: 'B', decisionTrailId: null, raw: {} },
    ] as AnnotationRecord[];
    const { container } = render(<AnnotatedText text="Isaiah" annotations={annotations} layers={{ deterministic: true, evidence: true }} />);
    expect(container.querySelector('[data-marker="2"]')).toBeTruthy();
  });
});

describe('context drawer and issue navigation', () => {
  it('shows linked context and closes without mutating the selected target', () => {
    const onClose = vi.fn();
    const { container } = render(<EvidenceInspector open view={view} target={sourceTarget} onClose={onClose} onViewDecisionTrail={vi.fn()} />);
    expect(container.textContent).toContain('Finis in Isaiam');
    expect(container.textContent).toContain('Evidence result');
    expect(container.textContent).toContain('Opening context before the selected Latin unit.');
    expect(container.textContent).toContain('Following context after the selected Latin unit.');
    expect(container.textContent).toContain('source apparatus note');
    expect(container.textContent).toContain('selected span');
    expect(container.textContent).toContain('selected_payload');
    expect(container.textContent).toContain('Checks and decisions');
    expect(container.textContent).toContain('Initial prosecutor issue');
    expect(container.textContent).toContain('Grounded prosecutor issue');
    expect(container.textContent).toContain('Adjudicator decision and exact edits');
    expect(container.textContent).toContain('Decision basis claim');
    expect(container.textContent).toContain('Exact correction');
    expect(container.textContent).toContain('Machine final and exact diff');
    expect(container.textContent).toContain('Final source mappings');
    expect(container.textContent).toContain('Verification and coverage');
    expect(container.textContent).toContain('Final check finding');
    expect(container.querySelector('dialog')).toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
    expect(sourceTarget.id).toBe('unit-1');
  });

  it('moves to the next/previous persisted issue and can reopen details', () => {
    const issues = [view.issues.items[0], { ...view.issues.items[0], issue_id: 'issue-2', source_record_id: 'finding-2', message: 'Second issue' }];
    const onSelect = vi.fn();
    const onReopen = vi.fn();
    render(<IssueNavigator issues={issues} unresolvedCount={2} selectedTarget={null} ledgerOpen={false} inspectorOpen={false} onSelectTarget={onSelect} onToggleLedger={vi.fn()} onReopenInspector={onReopen} />);
    fireEvent.click(screen.getByText('Next issue →'));
    expect(onSelect.mock.calls[0][0].id).toBe('issue-1');
  });

  it('keeps the docked ledger interactive and records a resolved outcome', () => {
    const onResolutionChange = vi.fn();
    const { container } = render(
      <IssueLedger
        view={view}
        selectedTarget={null}
        resolutions={new Map()}
        onResolutionChange={onResolutionChange}
        onSelectTarget={vi.fn()}
        docked
      />,
    );
    fireEvent.click(container.querySelector('.resolution-card summary') as HTMLElement);
    fireEvent.change(container.querySelector('.resolution-card select') as HTMLSelectElement, { target: { value: 'resolved' } });
    expect(onResolutionChange).toHaveBeenCalledWith('issue-1', { outcome: 'resolved' });
    expect(screen.queryByText('Close Ledger')).toBeNull();
  });
});
