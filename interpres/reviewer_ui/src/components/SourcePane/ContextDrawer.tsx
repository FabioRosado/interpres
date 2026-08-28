import type { SourceView } from '../../app/types';
import { stringify } from '../../lib/formatting';

interface Props {
  source: SourceView;
}

export const ContextDrawer = ({ source }: Props) => {
  const contextBefore = source.context_before || 'None recorded';
  const contextAfter = source.context_after || 'None recorded';

  return (
    <details className="context-drawer">
      <summary>Adjacent context and source annotations</summary>
      <div id="context-grid">
        {[
          ['Context before', contextBefore],
          ['Context after', contextAfter],
          ['Page markers', source.page_markers || []],
          ['Annotations', source.annotations || []],
        ].map(([heading, value]) => (
          <div key={heading} className="context-card">
            <h4>{heading}</h4>
            {typeof value === 'string' ? <p>{value}</p> : <pre>{stringify(value)}</pre>}
          </div>
        ))}
      </div>
    </details>
  );
};