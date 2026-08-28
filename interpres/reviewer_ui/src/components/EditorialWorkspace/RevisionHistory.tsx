import { useState } from 'preact/hooks';

interface Props {
  history: Record<string, unknown>[];
  revisionCount: number;
}

export const RevisionHistory = ({ history, revisionCount }: Props) => {
  const [open, setOpen] = useState(false);

  return (
    <details className="revision-history" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary id="revision-history-summary">Revision history · {revisionCount}</summary>
      <div id="revision-history">
        {history.map((item, i) => (
          <div key={i} className="history-row">
            <span>
              <b>Revision {(item.revision_number as number) || i + 1} · {(item.state as string) || 'unknown'}</b>
              <small> {(item.resolution_count as number) || 0} resolutions · {(item.reusable_resolution_count as number) || 0} reusable</small>
            </span>
            <small>{(item.created_at as string) || ''}</small>
          </div>
        ))}
        {!history.length && <div className="empty-state">No editorial revisions saved yet.</div>}
      </div>
    </details>
  );
};



