import { useEffect, useMemo } from 'preact/hooks';
import type { ReviewView, SelectionTarget } from '../../app/types';
import { stringify } from '../../lib/formatting';

interface Props {
  open: boolean;
  view: ReviewView;
  target: SelectionTarget | null;
  onClose: () => void;
  onViewDecisionTrail: (sectionId: string | null) => void;
}

function shares(left: string[] = [], right: string[] = []) {
  const values = new Set(right);
  return left.some((item) => values.has(item));
}

function related(target: SelectionTarget, item: Record<string, unknown>) {
  const id = String(item.finding_id || item.issue_id || item.request_id || item.edit_id || '');
  return target.id === id
    || target.findingIds.includes(id)
    || target.editIds.includes(id)
    || shares(target.sourceUnitIds, (item.source_unit_ids as string[]) || [])
    || shares(target.evidenceIds, (item.evidence_ids as string[]) || []);
}

function isEmptyValue(value: unknown): boolean {
  return value === null
    || value === undefined
    || value === ''
    || (Array.isArray(value) && value.length === 0)
    || (typeof value === 'object' && !Array.isArray(value) && Object.keys((value as Record<string, unknown>) || {}).length === 0);
}

function ContextValue({ value, fallback = 'None recorded' }: { value: unknown; fallback?: string }) {
  if (isEmptyValue(value)) return <p className="mapping-note">{fallback}</p>;
  if (typeof value === 'string') return <p>{value}</p>;
  return <pre className="context-json">{stringify(value)}</pre>;
}

function humanize(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function recordTitle(item: Record<string, unknown>, fallback: string): string {
  return String(item.message || item.claim || item.reason || item.issue || item.type || item.finding_id || item.issue_id || fallback);
}

function RecordList({ records, fallback }: { records: Record<string, unknown>[]; fallback: string }) {
  if (!records.length) return <p className="mapping-note">{fallback}</p>;
  return (
    <>
      {records.map((item, index) => (
        <article key={index} className="inspector-record">
          <b>{recordTitle(item, `Record ${index + 1}`)}</b>
          {item.latin && <p className="latin-quote">{String(item.latin)}</p>}
          {item.english && <p>{String(item.english)}</p>}
          {item.evidence_id && <small>Evidence: {String(item.evidence_id)}</small>}
          {item.evidence_ids && <small>Evidence: {((item.evidence_ids as string[]) || []).join(', ')}</small>}
          <ContextValue value={item} />
        </article>
      ))}
    </>
  );
}

export const EvidenceInspector = ({ open, view, target, onClose, onViewDecisionTrail }: Props) => {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  const context = useMemo(() => {
    if (!target) return null;
    const units = view.source.units.filter((unit) => target.sourceUnitIds.includes(unit.source_unit_id));
    const issues = view.issues.items.filter((issue) => target.issueIds.includes(issue.issue_id) || shares(target.sourceUnitIds, issue.source_unit_ids));
    const evidenceIds = new Set([...target.evidenceIds, ...issues.flatMap((issue) => issue.evidence_ids)]);
    const receipts = view.evidence.receipts.filter((receipt) => evidenceIds.has(String(receipt.evidence_id || '')) || related(target, receipt));
    const findings = [
      ...(view.disagreements.items || []),
      ...(view.deterministic.substantive_findings || []),
      ...(((view.prosecutor.initial as { findings?: Record<string, unknown>[] }).findings) || []),
      ...(((view.prosecutor.grounded as { findings?: Record<string, unknown>[] }).findings) || []),
      ...(view.adjudicator.findings || []),
      ...(view.adjudicator.unresolved_issues || []),
      ...(view.adjudicator.human_review_requests || []),
    ].filter((item) => related(target, item));
    const edits = view.adjudicator.edits.filter((item) => related(target, item));
    const finalMappings = view.final.source_mappings.filter((mapping) => target.sourceUnitIds.includes(String(mapping.source_unit_id || '')));
    const witnesses = view.witnesses.map((witness) => ({
      witness,
      mappings: witness.source_mappings.filter((mapping) => target.sourceUnitIds.includes(String(mapping.source_unit_id || ''))),
    }));
    const sourceSpans = (view.source.spans || []).filter((span) => {
      const unitId = String((span as Record<string, unknown>).source_unit_id || '');
      const unitIds = ((span as Record<string, unknown>).source_unit_ids as string[]) || [];
      return (unitId && target.sourceUnitIds.includes(unitId)) || shares(target.sourceUnitIds, unitIds);
    });
    const pageMarkers = view.source.page_markers || [];
    const sourceAnnotations = view.source.annotations || [];
    return { units, issues, receipts, findings, edits, finalMappings, witnesses, sourceSpans, pageMarkers, sourceAnnotations };
  }, [target, view]);

  if (!open) return null;

  return (
    <aside className="evidence-inspector" aria-label="Contextual evidence">
      <header className="evidence-inspector-header">
        <div>
          <span className="eyebrow">Selected review context</span>
          <h2>Contextual evidence</h2>
        </div>
        <button className="quiet-button" type="button" onClick={onClose} aria-label="Close contextual evidence">Close</button>
      </header>
      <div className="evidence-inspector-body">
      {!target || !context ? (
        <div className="empty-state">Select a Latin unit, mapped phrase, issue, edit, or evidence receipt to inspect it.</div>
      ) : (
        <div className="context-sidebar-content">
          <div className="inspector-target">
            <span className="eyebrow">{target.type.replaceAll('_', ' ')}</span>
            <h3>{target.label || target.id}</h3>
            <code>{target.id}</code>
          </div>

          <section className="inspector-section">
            <h4>Authoritative source</h4>
            {context.units.map((unit) => <blockquote key={unit.source_unit_id} className="latin-quote"><b>{unit.source_unit_id} · PL {unit.page || '—'}</b>{unit.text}</blockquote>)}
            {!context.units.length && <p className="mapping-note">No persisted source-unit link.</p>}
          </section>

          <details className="inspector-section" open>
            <summary>Adjacent source context</summary>
            <div className="inspector-record">
              <b>Context before</b>
              <ContextValue value={view.source.context_before} />
            </div>
            <div className="inspector-record">
              <b>Context after</b>
              <ContextValue value={view.source.context_after} />
            </div>
          </details>

          <details className="inspector-section" open>
            <summary>Source annotations and page record</summary>
            <div className="inspector-record">
              <b>Page markers</b>
              <ContextValue value={context.pageMarkers} />
            </div>
            <div className="inspector-record">
              <b>Source annotations</b>
              <ContextValue value={context.sourceAnnotations} />
            </div>
            <div className="inspector-record">
              <b>Source spans linked to selection</b>
              <ContextValue value={context.sourceSpans} fallback="No linked source spans recorded." />
            </div>
          </details>

          <section className="inspector-section">
            <h4>Machine Final wording</h4>
            {context.finalMappings.map((mapping, index) => {
              const start = mapping.english_start_offset;
              const end = mapping.english_end_offset;
              const wording = Number.isInteger(start) && Number.isInteger(end)
                ? (view.machine.final_draft || '').slice(Number(start), Number(end))
                : String(mapping.english_start_quote || mapping.english_end_quote || 'Coarse source-unit mapping');
              return <p key={index} className="machine-quote">{wording}</p>;
            })}
            {!context.finalMappings.length && <p className="mapping-note">Not mapped. No semantic alignment is inferred.</p>}
          </section>

          <details className="inspector-section" open>
            <summary>Witness A / Witness B and quorum</summary>
            <p className="mapping-note">Quorum: {String(view.witness_quorum.quorum || 'not recorded')} · valid: {((view.witness_quorum.valid_witnesses as string[]) || []).join(', ') || 'none recorded'}</p>
            {context.witnesses.map(({ witness, mappings }) => (
              <article key={witness.witness_id} className={`inspector-record ${witness.eligible_as_adjudicator_base ? '' : 'invalid-witness'}`}>
                <b>{witness.label} · {witness.validation_recorded ? (witness.eligible_as_adjudicator_base ? 'valid' : 'invalid') : witness.state}</b>
                <p>{witness.translation || 'Translation unavailable.'}</p>
                <small>{mappings.length ? `${mappings.length} persisted mapping(s) for this selection` : 'No selected-unit witness mapping'}</small>
              </article>
            ))}
          </details>

          <details className="inspector-section" open>
            <summary>Findings and issues · {context.findings.length + context.issues.length}</summary>
            {[...context.issues, ...context.findings].map((rawItem, index) => {
              const item = rawItem as unknown as Record<string, unknown>;
              return (
              <article key={index} className="inspector-record">
                <b>{String(item.message || item.issue || item.reason || item.type || item.origin || 'Review record')}</b>
                {item.latin && <p className="latin-quote">{String(item.latin)}</p>}
                {item.english && <p>{String(item.english)}</p>}
              </article>
              );
            })}
            {!context.findings.length && !context.issues.length && <p className="mapping-note">No linked finding.</p>}
          </details>

          <details className="inspector-section" open>
            <summary>Evidence receipts · {context.receipts.length}</summary>
            {context.receipts.map((receipt) => (
              <article key={String(receipt.evidence_id)} className="inspector-record evidence-record">
                <b>{String(receipt.evidence_id)} · grade {String(receipt.grade || '?')}</b>
                <span>{String(receipt.status || 'unavailable')}</span>
                <pre>{stringify(receipt.results || receipt.request || {})}</pre>
              </article>
            ))}
            {!context.receipts.length && <p className="mapping-note">No linked evidence receipt.</p>}
          </details>

          <details className="inspector-section" open>
            <summary>Adjudicator · {context.edits.length} linked edits</summary>
            <p>{view.adjudicator.summary || 'No adjudicator summary recorded.'}</p>
            {context.edits.map((edit) => <p key={String(edit.edit_id)} className="edit-quote"><del>{String(edit.old || '')}</del> → <ins>{String(edit.new || '')}</ins><small>{String(edit.reason || '')}</small></p>)}
          </details>

          <details className="inspector-section" open>
            <summary>Checks and decisions</summary>
            <div className="inspector-record">
              <b>Deterministic findings</b>
              <small>{humanize(view.deterministic.state)}</small>
              <RecordList records={(view.deterministic.substantive_findings || []) as Record<string, unknown>[]} fallback="No deterministic findings recorded." />
            </div>
            <div className="inspector-record">
              <b>Prosecutor · initial</b>
              <small>{humanize((view.prosecutor.initial as Record<string, unknown>).status || (view.prosecutor.initial as Record<string, unknown>).state)}</small>
              <RecordList records={(((view.prosecutor.initial as { findings?: Record<string, unknown>[] }).findings) || [])} fallback="No initial prosecutor findings recorded." />
            </div>
            <div className="inspector-record">
              <b>Prosecutor · grounded</b>
              <small>{humanize((view.prosecutor.grounded as Record<string, unknown>).status || (view.prosecutor.grounded as Record<string, unknown>).state)}</small>
              <RecordList records={(((view.prosecutor.grounded as { findings?: Record<string, unknown>[] }).findings) || [])} fallback="No grounded prosecutor findings recorded." />
            </div>
          </details>

          <details className="inspector-section" open>
            <summary>Adjudicator decision and exact edits</summary>
            <div className="inspector-record">
              <b>{view.adjudicator.base_witness ? `Base witness ${String(view.adjudicator.base_witness).toUpperCase()}` : 'Base witness unrecorded'}</b>
              <p>{view.adjudicator.summary || (view.adjudicator.available ? 'No decision summary recorded.' : `${humanize(view.adjudicator.state)} · no valid decision`)}</p>
            </div>
            <div className="inspector-record">
              <b>Decision basis</b>
              <RecordList records={(view.adjudicator.decision_basis || []) as Record<string, unknown>[]} fallback="No decision basis recorded." />
            </div>
            <div className="inspector-record">
              <b>Adjudicator findings</b>
              <RecordList records={(view.adjudicator.findings || []) as Record<string, unknown>[]} fallback="No adjudicator findings recorded." />
            </div>
            <div className="inspector-record">
              <b>Coverage record</b>
              <ContextValue value={view.adjudicator.coverage || {}} />
            </div>
            <div className="inspector-record">
              <b>Adjudicator evidence requests</b>
              <ContextValue value={view.adjudicator.evidence_requests || []} />
            </div>
            <div className="inspector-record">
              <b>Applied exact edits</b>
              {view.adjudicator.edits.length ? view.adjudicator.edits.map((edit) => (
                <p key={String(edit.edit_id)} className="edit-quote">
                  <del>{String(edit.old || '')}</del>
                  <ins>{String(edit.new || '')}</ins>
                  <small>{String(edit.reason || 'No reason recorded')}</small>
                </p>
              )) : <p className="mapping-note">No exact edits recorded.</p>}
            </div>
            {view.adjudicator.edit_validation_error && (
              <div className="inspector-record">
                <b>Edit validation error</b>
                <ContextValue value={view.adjudicator.edit_validation_error} />
              </div>
            )}
          </details>

          <details className="inspector-section" open>
            <summary>Machine final and exact diff</summary>
            <div className="inspector-record">
              <b>{humanize(view.final.status)}</b>
              <small>Base witness: {view.final.base_witness || 'unrecorded'} · applied edits: {view.final.applied_edit_count ?? 0}</small>
              <p>{view.final.translation || view.machine.final_draft || 'No complete machine final is available.'}</p>
            </div>
            <div className="inspector-record">
              <b>Base-to-final diff</b>
              <div className="translation-diff inspector-diff">
                {(view.final.diff || []).map((segment: { kind: string; text: string }, index: number) => {
                  if (segment.kind === 'delete') return <del key={index}>{segment.text}</del>;
                  if (segment.kind === 'insert') return <ins key={index}>{segment.text}</ins>;
                  return <span key={index}>{segment.text}</span>;
                })}
                {!view.final.diff?.length && <span>No diff segments recorded.</span>}
              </div>
            </div>
            <div className="inspector-record">
              <b>Final source mappings</b>
              <ContextValue value={view.final.source_mappings || []} fallback="No final source mappings recorded." />
            </div>
          </details>

          <details className="inspector-section" open>
            <summary>Verification and coverage</summary>
            <div className="inspector-record">
              <b>Coverage gate</b>
              <small>{view.verification.source_units_accounted_for ?? 'Not mapped'} / {view.verification.source_units_total} source units</small>
              <p>{view.verification.coverage_assertion === true ? 'Complete asserted' : view.verification.coverage_assertion === false ? 'Not complete' : 'Not recorded'}</p>
            </div>
            <div className="inspector-record">
              <b>Exact edit validation</b>
              <p>{humanize(view.verification.exact_edit_validation)}</p>
            </div>
            <div className="inspector-record">
              <b>Final schema gate</b>
              <p>{humanize(view.verification.schema_status_validation)}</p>
            </div>
            <div className="inspector-record">
              <b>Missing source units</b>
              <ContextValue value={view.verification.missing_source_unit_ids || []} fallback="No missing source units recorded." />
            </div>
            <div className="inspector-record">
              <b>Final checks</b>
              <ContextValue value={view.verification.final_checks || {}} fallback="No final checks recorded." />
            </div>
            <div className="inspector-record">
              <b>Incomplete stages</b>
              <ContextValue value={view.verification.incomplete_stages || []} fallback="No incomplete stages recorded." />
            </div>
          </details>

          <section className="inspector-section">
            <h4>Editorial state</h4>
            <p>{view.editorial?.revision_count || 0} saved revisions · {view.editorial?.based_on_current_machine_final ? 'based on current Machine Final' : 'machine base differs or is not recorded'}</p>
          </section>

          <details className="inspector-section">
            <summary>Selected record payload</summary>
            <ContextValue value={target.raw} fallback="No raw selected record payload." />
          </details>

          <button className="primary-button" type="button" onClick={() => onViewDecisionTrail(target.decisionTrailId)}>View in Decision Trail</button>
        </div>
      )}
      </div>
    </aside>
  );
};
