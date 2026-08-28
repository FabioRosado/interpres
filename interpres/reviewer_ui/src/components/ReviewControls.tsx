import type { AppState } from '../app/types';

interface Props {
  reviewMode: AppState['reviewMode'];
  layers: AppState['layers'];
  onModeChange: (mode: AppState['reviewMode']) => void;
  onLayerToggle: (key: string, value: boolean) => void;
  onShowAll: () => void;
  onHideIssueLayers: () => void;
  onClearSelection: () => void;
}

export const ReviewControls = ({ reviewMode, layers, onModeChange, onLayerToggle, onShowAll, onHideIssueLayers, onClearSelection }: Props) => {
  const layerEntries = Object.entries(layers);

  return (
    <section className="review-controls" aria-label="Review highlight controls">
      <div>
        <p className="eyebrow">Review mode</p>
        <div className="mode-switch" role="group" aria-label="Reading mode">
          {(['review', 'focus', 'clean'] as const).map((mode) => (
            <button
              key={mode}
              className={`mini-filter ${reviewMode === mode ? 'active' : ''}`}
              onClick={() => onModeChange(mode)}
              type="button"
            >
              {mode === 'review' ? 'Review' : mode === 'focus' ? 'Focus' : 'Clean reading'}
            </button>
          ))}
        </div>
      </div>
      <div className="layer-controls" aria-label="Annotation layers">
        {layerEntries.map(([key, visible]) => (
          <label key={key} className="layer-toggle">
            <input
              type="checkbox"
              checked={visible}
              onChange={(e) => onLayerToggle(key, (e.target as HTMLInputElement).checked)}
            />
            <span>{humanizeLayer(key)}</span>
          </label>
        ))}
      </div>
      <div className="review-actions">
        <button className="quiet-button" type="button" onClick={onShowAll}>Show all</button>
        <button className="quiet-button" type="button" onClick={onHideIssueLayers}>Hide issue layers</button>
        <button className="quiet-button" type="button" onClick={onClearSelection}>Clear selection</button>
      </div>
    </section>
  );
};

function humanizeLayer(key: string): string {
  const labels: Record<string, string> = {
    deterministic: 'Deterministic',
    witness_disagreement: 'Disagreements',
    prosecutor: 'Prosecutor',
    evidence: 'Evidence',
    adjudicator: 'Adjudicator findings',
    adjudicator_edit: 'Adjudicator edits',
    unresolved: 'Unresolved',
    human_review: 'Human review',
    verification: 'Verification',
    source_mapping: 'Source mappings',
    editorial_note: 'Editorial notes',
  };
  return labels[key] || key;
}
