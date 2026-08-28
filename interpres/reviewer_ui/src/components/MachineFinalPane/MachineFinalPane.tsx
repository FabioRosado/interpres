import type { ReviewIndex, ReviewView, SelectionTarget } from '../../app/types';
import { AnnotatedText } from '../Annotations/AnnotatedText';

interface Props {
  view: ReviewView;
  reviewIndex: ReviewIndex | null;
  selectedTarget: SelectionTarget | null;
  layers: Record<string, boolean>;
  onSelectTarget: (target: SelectionTarget | null) => void;
}

export const MachineFinalPane = ({ view, reviewIndex, selectedTarget, layers, onSelectTarget }: Props) => {
  const final = view.machine.final_draft || 'No complete machine final is available.';
  const annotations = reviewIndex?.annotations || [];
  const selectedUnit = selectedTarget?.sourceUnitIds?.[0];
  const selectedMapping = selectedUnit
    ? view.final.source_mappings.find((mapping) => String(mapping.source_unit_id || '') === selectedUnit)
    : null;

  const handleSelect = (target: { id: string; type: string; sourceUnitIds: string[]; findingIds: string[]; evidenceIds: string[]; editIds: string[]; issueIds: string[]; decisionTrailId: string | null; label: string; raw: Record<string, unknown> }) => {
    onSelectTarget(target as SelectionTarget);
  };

  return (
    <section className="reference-pane machine-reference" id="reference-machine" aria-labelledby="machine-pane-heading">
      <header className="pane-heading">
        <div>
          <p className="eyebrow">Machine final · locked</p>
          <h3 id="machine-pane-heading">Immutable translation</h3>
        </div>
        <span className={`status-badge ${view.machine.final_status}`}>{view.machine.final_status.replaceAll('_', ' ')}</span>
      </header>
      <div id="machine-final" className="reference-scroll machine-final-text">
        <AnnotatedText
          text={final}
          annotations={annotations as any}
          options={{ preferReplacement: true }}
          selectedTarget={selectedTarget}
          layers={layers}
          onSelect={handleSelect}
        />
      </div>
      {selectedUnit && !selectedMapping && (
        <p className="mapping-status missing" role="status">{selectedUnit} · Not mapped to Machine Final</p>
      )}
      {selectedUnit && selectedMapping && (
        <p className="mapping-status" role="status">
          {selectedUnit} · {Number.isInteger(selectedMapping.english_start_offset) ? 'Precise persisted mapping' : 'Coarse persisted mapping'}
        </p>
      )}
    </section>
  );
};
