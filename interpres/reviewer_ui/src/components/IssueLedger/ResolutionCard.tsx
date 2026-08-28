import type { IssueResolution, IssueView } from '../../app/types';
interface Props {
  issue: IssueView;
  filter: 'open' | 'resolved' | 'all';
  isSelected: boolean;
  resolution?: IssueResolution;
  onChange: (patch: Partial<IssueResolution>) => void;
  onSelect: () => void;
}

export const ResolutionCard = ({ issue, filter, isSelected, resolution, onChange, onSelect }: Props) => {
  const outcome = resolution?.outcome || 'deferred';
  const isResolved = outcome === 'resolved' || outcome === 'accepted_as_is';

  if (filter === 'open' && isResolved) return null;
  if (filter === 'resolved' && !isResolved) return null;

  return (
    <details className={`resolution-card related-record ${isSelected ? 'selected' : ''}`} data-issue-id={issue.issue_id} onClick={onSelect}>
      <summary>
        <span className="resolution-summary">
          <b>{issue.message || humanize(issue.origin)}</b>
          <small>{humanize(issue.origin)} · {humanize(issue.severity || issue.status || 'ungraded')}</small>
        </span>
      </summary>
      <div className="resolution-body">
        {issue.latin && <p className="latin-quote">{issue.latin}</p>}
        {issue.english && <p className="mapping-note">Machine/context text · {issue.english}</p>}
        {!(issue.source_unit_ids || []).length && <p className="mapping-note">No persisted source-unit mapping is available for this issue.</p>}
        <div className="field">
          <span>Resolution</span>
          <select value={outcome} onClick={(event) => event.stopPropagation()} onChange={(e) => onChange({ outcome: (e.target as HTMLSelectElement).value as IssueResolution['outcome'] })}>
            <option value="deferred">Still open / defer</option>
            <option value="resolved">Resolved by editor</option>
            <option value="accepted_as_is">Reviewed · accept as is</option>
          </select>
        </div>
        <div className="field">
          <span>Editorial note</span>
          <textarea value={resolution?.note || ''} onClick={(event) => event.stopPropagation()} onInput={(event) => onChange({ note: (event.currentTarget as HTMLTextAreaElement).value })} placeholder="Record why this is resolved or deferred…" />
        </div>
        <div className="field">
          <span>Reusable approved wording</span>
          <input type="text" value={resolution?.approved_english || ''} onClick={(event) => event.stopPropagation()} onInput={(event) => onChange({ approved_english: (event.currentTarget as HTMLInputElement).value })} placeholder="Approved English for this exact Latin phrase" disabled={!issue.reusable_eligible} />
        </div>
        <label className="reuse-field" onClick={(event) => event.stopPropagation()}>
          <input type="checkbox" checked={resolution?.reusable || false} onChange={(event) => onChange({ reusable: (event.currentTarget as HTMLInputElement).checked })} disabled={!issue.reusable_eligible} />
          <span>{issue.reusable_eligible ? 'Reuse as human-approved editorial precedent' : 'No exact Latin was recorded; this cannot become precedent'}</span>
        </label>
      </div>
    </details>
  );
};

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}




