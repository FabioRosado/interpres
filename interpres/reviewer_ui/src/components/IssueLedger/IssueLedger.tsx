import type { IssueResolution, ReviewView, SelectionTarget } from '../../app/types';
import { useState } from 'preact/hooks';
import { ResolutionCard } from './ResolutionCard';
import { targetFromIssue } from './IssueNavigator';

interface Props {
  view: ReviewView;
  selectedTarget: SelectionTarget | null;
  resolutions: Map<string, IssueResolution>;
  onResolutionChange: (issueId: string, patch: Partial<IssueResolution>) => void;
  onSelectTarget: (target: SelectionTarget | null) => void;
  onClose?: () => void;
  docked?: boolean;
}

export const IssueLedger = ({ view, selectedTarget, resolutions, onResolutionChange, onSelectTarget, onClose, docked = false }: Props) => {
  const [filter, setFilter] = useState<'open' | 'resolved' | 'all'>('open');
  const issues = view.issues.items;

  return (
    <section className="issue-pane section-card" id="issue-ledger" aria-labelledby="issue-heading">
      <div className="compact-heading">
        <div>
          <p className="eyebrow">Full review surface</p>
          <h2 id="issue-heading">Resolution Ledger</h2>
        </div>
        {!docked && onClose && <button className="quiet-button" type="button" onClick={onClose}>Close Ledger</button>}
      </div>
      <div className="issue-filters">
        {(['open', 'resolved', 'all'] as const).map((f) => (
          <button
            key={f}
            className={`mini-filter ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}
            type="button"
          >
            {f === 'open' ? 'Open' : f === 'resolved' ? 'Resolved' : 'All'}
          </button>
        ))}
      </div>
      <div className="resolution-list">
        {issues.map((issue) => (
          <ResolutionCard
            key={issue.issue_id}
            issue={issue}
            filter={filter}
            resolution={resolutions.get(issue.issue_id)}
            isSelected={selectedTarget?.issueIds?.includes(issue.issue_id) || false}
            onChange={(patch) => onResolutionChange(issue.issue_id, patch)}
            onSelect={() => onSelectTarget(targetFromIssue(issue))}
          />
        ))}
      </div>
      <div className="precedent-note">
        <b>Editorial precedent is opt-in.</b>
        <p>Only an approved revision with "reuse" enabled is shown to later review stages. Witnesses remain blind, and precedent is never treated as source evidence.</p>
      </div>
    </section>
  );
};



