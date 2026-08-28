import type { IssueView, SelectionTarget } from '../../app/types';

interface Props {
  issues: IssueView[];
  unresolvedCount: number;
  selectedTarget: SelectionTarget | null;
  ledgerOpen: boolean;
  inspectorOpen: boolean;
  docked?: boolean;
  onSelectTarget: (target: SelectionTarget) => void;
  onToggleLedger: () => void;
  onReopenInspector: () => void;
}

function trailForIssue(issue: IssueView): string | null {
  if (issue.origin === 'witness_disagreement') return 'decision-witnesses';
  if (issue.origin === 'deterministic' || issue.origin === 'prosecutor') return 'decision-challenges';
  if (['adjudicator', 'unresolved', 'human_review'].includes(issue.origin)) return 'decision-adjudicator';
  return null;
}

export function targetFromIssue(issue: IssueView): SelectionTarget {
  return {
    id: issue.issue_id,
    type: 'issue',
    sourceUnitIds: issue.source_unit_ids || [],
    findingIds: issue.source_record_id ? [issue.source_record_id] : [],
    evidenceIds: issue.evidence_ids || [],
    editIds: [],
    issueIds: [issue.issue_id],
    decisionTrailId: trailForIssue(issue),
    label: issue.message || issue.origin,
    raw: issue as unknown as Record<string, unknown>,
  };
}

export const IssueNavigator = ({
  issues,
  unresolvedCount,
  selectedTarget,
  ledgerOpen,
  inspectorOpen,
  docked = false,
  onSelectTarget,
  onToggleLedger,
  onReopenInspector,
}: Props) => {
  const selectedIssueId = selectedTarget?.issueIds?.[0] || null;
  const selectedIndex = selectedIssueId ? issues.findIndex((issue) => issue.issue_id === selectedIssueId) : -1;

  const move = (delta: number) => {
    if (!issues.length) return;
    const nextIndex = selectedIndex < 0
      ? (delta > 0 ? 0 : issues.length - 1)
      : (selectedIndex + delta + issues.length) % issues.length;
    onSelectTarget(targetFromIssue(issues[nextIndex]));
  };

  return (
    <section className="issue-strip" aria-label="Issue navigation">
      <div>
        <b>{issues.length} issues · {unresolvedCount} unresolved</b>
        <span id="issue-position">{selectedIndex >= 0 ? `Issue ${selectedIndex + 1} of ${issues.length}` : 'No issue selected'}</span>
      </div>
      <div className="issue-navigation">
        <button className="quiet-button" type="button" onClick={() => move(-1)} disabled={!issues.length}>← Previous issue</button>
        <button className="quiet-button" type="button" onClick={() => move(1)} disabled={!issues.length}>Next issue →</button>
        {!docked && <button className="quiet-button" type="button" onClick={onToggleLedger} aria-expanded={ledgerOpen}>{ledgerOpen ? 'Close Ledger' : 'Open Ledger'}</button>}
        {selectedTarget && !inspectorOpen && <button className="quiet-button" type="button" onClick={onReopenInspector}>Reopen details</button>}
      </div>
    </section>
  );
};
