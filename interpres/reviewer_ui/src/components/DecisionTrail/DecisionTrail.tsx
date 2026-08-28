import type { ReviewView, SelectionTarget } from '../../app/types';

interface Props {
  view: ReviewView;
  selectedTarget: SelectionTarget | null;
  layers: Record<string, boolean>;
  onSelectTarget: (target: SelectionTarget | null) => void;
}

export const DecisionTrail = ({ view, selectedTarget, layers, onSelectTarget }: Props) => {
  return (
    <>
      <div className="decision-trail-heading">
        <div>
          <p className="eyebrow">Complete immutable audit</p>
          <h2>Decision trail</h2>
          <p>Everything the models, deterministic gates, and evidence service recorded for this chunk.</p>
        </div>
        <span>Machine record · read-only</span>
      </div>
      <nav className="decision-jumps" aria-label="Decision trail sections">
        {[
          ['Witnesses', 'decision-witnesses'], ['Challenges', 'decision-challenges'], ['Adjudicator', 'decision-adjudicator'],
          ['Final & diff', 'decision-final'], ['Verification', 'decision-verification'], ['Evidence', 'decision-evidence'],
          ['Structural', 'decision-structural'], ['Morphology', 'decision-morphology'], ['Provenance', 'decision-provenance'],
        ].map(([label, id]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </nav>
      <section className="audit-section" id="decision-witnesses" aria-label="Witness comparison">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stage 1 · independent drafts</p>
              <h3>Witness comparison</h3>
            </div>
            <p id="disagreement-note">{view.disagreements.note || `${view.disagreements.items.length} explicitly recorded`}</p>
          </div>
          <div className="witness-grid" id="witness-grid">
            {view.witnesses.map((witness) => (
              <article
                key={witness.witness_id}
                className={`witness-card ${witness.eligible_as_adjudicator_base ? '' : 'invalid-witness'}`}
                onClick={() => onSelectTarget({
                  id: witness.witness_id,
                  type: 'witness',
                  sourceUnitIds: [],
                  findingIds: [],
                  evidenceIds: [],
                  editIds: [],
                  issueIds: [],
                  decisionTrailId: null,
                  label: witness.label,
                  raw: witness as unknown as Record<string, unknown>,
                })}
              >
                <h3>{witness.label}</h3>
                <p className="model-line">
                  {witness.available ? `${witness.provider || 'provider unrecorded'} · ${witness.model || 'model unrecorded'}` : humanize(witness.state)}
                </p>
                {witness.validation_recorded && (
                  <p className={witness.eligible_as_adjudicator_base ? 'save-message success' : 'save-message error'}>
                    {witness.eligible_as_adjudicator_base ? 'Validated · eligible as adjudicator base' : `Not eligible as adjudicator base`}
                  </p>
                )}
                {witness.authority_role === 'non_authoritative_clue_not_evidence' && (
                  <p className="mapping-note">Non-authoritative clue only · preserved for audit · not evidence or corroboration</p>
                )}
                <div className="witness-translation">{witness.translation || 'Witness translation unavailable.'}</div>
                <details>
                  <summary>Mappings, uncertainty, and validation</summary>
                  <pre>{JSON.stringify({ source_mappings: witness.source_mappings, uncertainty: witness.uncertainty, validation: witness.validation }, null, 2)}</pre>
                </details>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section className="audit-section" id="decision-challenges" aria-label="Checks and prosecutor challenges">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stages 2–4 · challenge pipeline</p>
              <h3>Checks and objections</h3>
            </div>
            <span className="evidence-key">Deterministic evidence ≠ model inference</span>
          </div>
          <div className="analysis-grid">
            <div>
              <h4>Deterministic findings</h4>
              <p className="stage-summary">{humanize(view.deterministic.state)}</p>
              <div id="deterministic-findings">
                {(view.deterministic.substantive_findings || []).map((f: Record<string, unknown>, i: number) => (
                  <article key={i} className="record-card related-record" onClick={() => onSelectTarget(targetForRecord(f, 'finding', 'decision-challenges'))}>
                    <div className="record-meta">
                      <span className="pill">{humanize((f.type as string) || 'finding')}</span>
                      <span className={`severity-pill ${f.severity}`}>{humanize((f.severity as string) || 'ungraded')}</span>
                    </div>
                    <h4>{f.message as string || 'Finding'}</h4>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <h4>Prosecutor · initial</h4>
              <p className="stage-summary">{humanize((view.prosecutor.initial as Record<string, unknown>).status as string || (view.prosecutor.initial as Record<string, unknown>).state as string)}</p>
              <div id="prosecutor-initial">
                {((view.prosecutor.initial as { findings?: Record<string, unknown>[] }).findings || []).map((f: Record<string, unknown>, i: number) => (
                  <article key={i} className="record-card related-record" onClick={() => onSelectTarget(targetForRecord(f, 'finding', 'decision-challenges'))}>
                    <div className="record-meta">
                      <span className="pill">{humanize((f.type as string) || 'finding')}</span>
                    </div>
                    <h4>{f.message as string || 'Finding'}</h4>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <h4>Prosecutor · grounded</h4>
              <p className="stage-summary">{humanize((view.prosecutor.grounded as Record<string, unknown>).status as string || (view.prosecutor.grounded as Record<string, unknown>).state as string)}</p>
              <div id="prosecutor-grounded">
                {((view.prosecutor.grounded as { findings?: Record<string, unknown>[] }).findings || []).map((f: Record<string, unknown>, i: number) => (
                  <article key={i} className="record-card related-record" onClick={() => onSelectTarget(targetForRecord(f, 'finding', 'decision-challenges'))}>
                    <div className="record-meta">
                      <span className="pill">{humanize((f.type as string) || 'finding')}</span>
                    </div>
                    <h4>{f.message as string || 'Finding'}</h4>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="audit-section" id="decision-adjudicator" aria-label="Adjudicator decision">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stage 5 · decision layer</p>
              <h3>Adjudicator decision and exact edits</h3>
            </div>
            <span className="base-witness">{view.adjudicator.base_witness ? `Base witness ${String(view.adjudicator.base_witness).toUpperCase()}` : 'Base witness unrecorded'}</span>
          </div>
          <p className="decision-summary">{view.adjudicator.summary || (view.adjudicator.available ? 'No decision summary recorded.' : `${humanize(view.adjudicator.state)} · no valid decision`)}</p>
          <div className="decision-columns">
            <div>
              <h4>Decision basis</h4>
              <div className="record-list" id="decision-basis">
                {(view.adjudicator.decision_basis || []).map((item: Record<string, unknown>, i: number) => (
                  <article key={i} className="record-card" onClick={() => onSelectTarget(targetForRecord(item, 'finding', 'decision-adjudicator'))}>
                    <div className="record-meta">
                      <span className={`severity-pill ${item.grade}`}>{humanize((item.grade as string) || 'ungraded')}</span>
                      <span className="model-line">Basis {i + 1}</span>
                    </div>
                    <h4>{item.claim as string || 'Decision claim not recorded'}</h4>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <h4>Adjudicator findings</h4>
              <div className="record-list" id="adjudicator-findings">
                {view.adjudicator.findings.map((f: Record<string, unknown>, i: number) => (
                  <article key={i} className="record-card related-record" onClick={() => onSelectTarget(targetForRecord(f, 'finding', 'decision-adjudicator'))}>
                    <div className="record-meta">
                      <span className="pill">{humanize((f.type as string) || 'finding')}</span>
                    </div>
                    <h4>{f.message as string || 'Finding'}</h4>
                  </article>
                ))}
              </div>
            </div>
          </div>
          <div className="decision-raw-grid">
            <details>
              <summary>Coverage record</summary>
              <pre id="adjudicator-coverage">{JSON.stringify(view.adjudicator.coverage || {}, null, 2)}</pre>
            </details>
            <details>
              <summary>Adjudicator evidence requests</summary>
              <pre id="adjudicator-evidence-requests">{JSON.stringify(view.adjudicator.evidence_requests || [], null, 2)}</pre>
            </details>
          </div>
          <div className="subsection-heading"><h4>Applied exact edits</h4></div>
          <div className="record-list" id="edit-list">
            {view.adjudicator.edits.map((edit: Record<string, unknown>, i: number) => (
              <article key={i} className="record-card edit-card related-record" data-edit-id={edit.edit_id as string} onClick={() => onSelectTarget({
                id: edit.edit_id as string,
                type: 'adjudicator_edit',
                sourceUnitIds: (edit.source_unit_ids as string[]) || [],
                findingIds: [],
                evidenceIds: (edit.evidence_ids as string[]) || [],
                editIds: [edit.edit_id as string],
                issueIds: [],
                decisionTrailId: 'decision-adjudicator',
                label: (edit.reason as string) || 'Adjudicator edit',
                raw: edit,
              })}>
                <code>{(edit.old as string) || ''}</code>
                <span>→</span>
                <code>{(edit.new as string) || ''}</code>
                <p>{(edit.reason as string) || 'No reason recorded'}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section className="audit-section" id="decision-final" aria-label="Machine final and diff">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stage 6 · deterministic reconstruction</p>
              <h3>Machine final and exact diff</h3>
            </div>
            <span className="section-note" id="final-method"></span>
          </div>
          <div className="final-translation" id="final-translation">
            {view.final.translation || 'No complete machine final is available.'}
          </div>
          <div className="subsection-heading"><h4>Base-to-final diff</h4></div>
          <div className="translation-diff" id="translation-diff">
            {view.final.diff.map((segment: { kind: string; text: string }, i: number) => {
              if (segment.kind === 'delete') return <del key={i}>{segment.text}</del>;
              if (segment.kind === 'insert') return <ins key={i}>{segment.text}</ins>;
              return <span key={i}>{segment.text}</span>;
            })}
          </div>
        </div>
      </section>
      <section className="audit-section" id="decision-verification" aria-label="Verification and coverage">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stage 7 · post-adjudication gate</p>
              <h3>Verification and coverage</h3>
            </div>
          </div>
          <div className="verification-grid" id="verification-grid">
            {[
              [view.verification.coverage_assertion === true ? 'Complete asserted' : view.verification.coverage_assertion === false ? 'Not complete' : 'Not recorded', 'Clause coverage'],
              [`${view.verification.source_units_accounted_for ?? 'Not mapped'} / ${view.verification.source_units_total} source units`],
              [humanize(view.verification.exact_edit_validation), 'Exact edit validation'],
              [humanize(view.verification.schema_status_validation), 'Final schema gate'],
            ].map(([value, label], i) => (
              <div key={i} className="verification-card">
                <b>{value as string}</b>
                <span>{label as string}</span>
              </div>
            ))}
          </div>
          <div id="final-checks">
            {(((view.verification.final_checks.findings as Record<string, unknown>[]) || [])).map((f: Record<string, unknown>, i: number) => (
              <article key={i} className="record-card related-record" onClick={() => onSelectTarget(targetForRecord(f, 'finding', 'decision-verification'))}>
                <div className="record-meta">
                  <span className="pill">{humanize((f.type as string) || 'check')}</span>
                  <span className={`severity-pill ${f.severity}`}>{humanize((f.severity as string) || 'ungraded')}</span>
                </div>
                <h4>{f.message as string || 'Check'}</h4>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section className="audit-section" id="decision-evidence" aria-label="Evidence receipts">
        <div className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Bounded research rounds</p>
              <h3>Research evidence</h3>
            </div>
          </div>
          <div id="evidence-list">
            {view.evidence.receipts.map((receipt: Record<string, unknown>, i: number) => (
              <article key={i} className="receipt-card" onClick={() => onSelectTarget(targetForRecord(receipt, 'evidence', 'decision-evidence'))}>
                <summary className="receipt-heading">
                  <span>
                    <b>{receipt.evidence_id as string}</b>
                    <span className={`context-badge evidence-grade grade-${String(receipt.grade || '?').toLowerCase()}`}>{receipt.grade as string || '?'}</span>
                    <span className={`context-badge ${evidenceStatusClass(receipt.status as string)}`}>{humanize(receipt.status as string || 'UNAVAILABLE').toUpperCase()}</span>
                  </span>
                </summary>
                <div className="receipt-body">
                  {((receipt.results as Record<string, unknown>[]) || []).map((result: Record<string, unknown>, j: number) => (
                    <div key={j} className="evidence-result">
                      <p>{result.text as string || result.match as string || result.reference as string || 'Result'}</p>
                      {result.provenance && <pre>{JSON.stringify(result.provenance, null, 2)}</pre>}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
      <details className="audit-section section-card analysis-disclosure" id="decision-structural">
        <summary>
          <span>
            <b>Blind structural analysis</b>
            <small>Original syntax, ambiguity, alternatives, and uncertainty</small>
          </span>
          <span>{humanize(view.structural.state)}</span>
        </summary>
        <div className="details-body" id="structural-body">
          {view.structural.sentences.map((sentence: Record<string, unknown>, i: number) => (
            <article key={i} className="structural-card" onClick={() => onSelectTarget({
              id: `sentence-${i}`,
              type: 'finding',
              sourceUnitIds: [],
              findingIds: [`sentence-${i}`],
              evidenceIds: [],
              editIds: [],
              issueIds: [],
              decisionTrailId: null,
              label: `Sentence ${i + 1}`,
              raw: sentence,
            })}>
              <h4>Sentence {i + 1}</h4>
              <p className="latin-quote">{sentence.latin as string || ''}</p>
              <pre>{JSON.stringify(sentence, null, 2)}</pre>
            </article>
          ))}
        </div>
      </details>
      <details className="audit-section section-card analysis-disclosure" id="decision-morphology">
        <summary>
          <span>
            <b>Morphology and lexical flags</b>
            <small>Deterministic candidates kept separate from model claims</small>
          </span>
          <span>{humanize(view.morphology.state)}</span>
        </summary>
        <div className="details-body" id="morphology-body">
          {view.morphology.flags.map((flag: Record<string, unknown>, i: number) => (
            <article key={i} className="morphology-card related-record" onClick={() => onSelectTarget(targetForRecord(flag, 'finding', 'decision-morphology'))}>
              <h4>{flag.token as string || flag.surface as string || 'Form'} · {humanize(flag.flag_type as string)}</h4>
              <pre>{JSON.stringify(flag, null, 2)}</pre>
            </article>
          ))}
        </div>
      </details>
      <section className="audit-section" id="decision-provenance" aria-label="Run provenance">
        <div className="section-card provenance-warning">This is the immutable machine record. Editorial saves are stored separately and never rewrite anything below.</div>
        <div id="run-details-body">
          {view.run_details.map((detail: Record<string, unknown>, i: number) => (
            <div key={i} className="stage-card" onClick={() => onSelectTarget({
              id: `stage-${i}`,
              type: 'finding',
              sourceUnitIds: [],
              findingIds: [`stage-${i}`],
              evidenceIds: [],
              editIds: [],
              issueIds: [],
              decisionTrailId: null,
              label: humanize(detail.stage as string),
              raw: detail,
            })}>
              <div className="stage-heading">
                <span>{humanize(detail.stage as string)}</span>
                <span>{detail.provider as string || 'unknown'} · {detail.model as string || 'unknown'}</span>
              </div>
              <div className="stage-meta">
                <span>{detail.cache_status as string}</span>
                <span>{detail.elapsed_seconds ? `${detail.elapsed_seconds}s` : ''}</span>
              </div>
            </div>
          ))}
        </div>
        <details className="section-card lineage-history">
          <summary>Active and historical lineage · {Number(view.lineage?.historical_record_count || 0)} historical records</summary>
          <pre>{JSON.stringify(view.lineage || {}, null, 2)}</pre>
          <div className="history-records">
            {(view.stage_history || []).map((record, index) => (
              <article key={index} className={`history-record ${record.is_active ? 'active' : 'historical'}`}>
                <b>{humanize(String(record.stage || 'unknown'))}</b>
                <span>{record.is_active ? 'Active branch' : 'Historical'}</span>
                <code>{String(record.artifact_id || 'No artifact ID')}</code>
                <small>{String(record.finished_at || '')}</small>
              </article>
            ))}
          </div>
        </details>
      </section>
    </>
  );
};

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function evidenceStatusClass(value: string): string {
  return String(value || 'unavailable').toLowerCase().replaceAll(/[_\s]+/g, '-');
}

function targetForRecord(record: Record<string, unknown>, type: string, decisionTrailId: string | null): SelectionTarget {
  const persistedId = record.finding_id || record.issue_id || record.request_id || record.edit_id || record.evidence_id || record.flag_id || record.entry_id;
  const label = String(record.message || record.claim || record.reason || record.issue || record.type || record.evidence_id || type);
  const id = String(persistedId || `${type}:${label}`);
  return {
    id,
    type,
    sourceUnitIds: (record.source_unit_ids as string[]) || [],
    findingIds: type === 'finding' && persistedId ? [String(persistedId)] : [],
    evidenceIds: type === 'evidence' ? [id] : ((record.evidence_ids as string[]) || []),
    editIds: record.edit_id ? [String(record.edit_id)] : [],
    issueIds: record.issue_id ? [String(record.issue_id)] : [],
    decisionTrailId,
    label,
    raw: record,
  };
}
