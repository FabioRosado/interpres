import type { ReviewIndex, ReviewView, SelectionTarget } from '../../app/types';
import { useEffect, useRef } from 'preact/hooks';
import { SourceUnitTabs } from './SourceUnitTabs';
import { SourceUnitCard } from './SourceUnitCard';
import { ContextDrawer } from './ContextDrawer';
import { targetFromUnit } from '../../lib/annotations';

interface Props {
  view: ReviewView;
  reviewIndex: ReviewIndex | null;
  selectedTarget: SelectionTarget | null;
  layers: Record<string, boolean>;
  onSelectTarget: (target: SelectionTarget | null) => void;
}

export const SourcePane = ({ view, reviewIndex, selectedTarget, onSelectTarget }: Props) => {
  const panelRef = useRef<HTMLElement>(null);
  const activeUnit = selectedTarget?.sourceUnitIds?.[0] || null;
  const sourceLabel = view.source.label || 'Latin';
  const finalMapped = new Set(view.final.source_mappings.map((mapping) => String(mapping.source_unit_id || '')));
  const witnessMapped = new Set(view.witnesses.flatMap((witness) => witness.source_mappings.map((mapping) => String(mapping.source_unit_id || ''))));

  useEffect(() => {
    if (!activeUnit || !panelRef.current) return;
    const card = Array.from(panelRef.current.querySelectorAll<HTMLElement>('[data-unit-id]'))
      .find((item) => item.dataset.unitId === activeUnit && item.classList.contains('latin-unit'));
    card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [activeUnit]);

  const handleSelectUnit = (unitId: string | null) => {
    if (unitId) {
      onSelectTarget(targetFromUnit(unitId, reviewIndex as any) as SelectionTarget);
    } else {
      onSelectTarget(null);
    }
  };

  return (
    <section ref={panelRef} className="reference-pane source-reference" id="reference-source" aria-labelledby="source-pane-heading">
      <header className="pane-heading">
        <div>
          <p className="eyebrow">Authoritative source</p>
          <h3 id="source-pane-heading">{sourceLabel}</h3>
        </div>
        <span className="context-badge">{view.source.units.length} PL units</span>
      </header>
      <SourceUnitTabs units={view.source.units} activeUnit={activeUnit} onSelect={handleSelectUnit} />
      <div className="reference-scroll latin-units">
        {view.source.units.map((unit) => (
          <SourceUnitCard
            key={unit.source_unit_id}
            unit={unit}
            isSelected={activeUnit === unit.source_unit_id}
            hasFinalMapping={finalMapped.has(unit.source_unit_id)}
            hasWitnessMapping={witnessMapped.has(unit.source_unit_id)}
            onClick={() => handleSelectUnit(unit.source_unit_id)}
          />
        ))}
        {!view.source.units.length && <div className="empty-state">Source units are unavailable.</div>}
      </div>
      <ContextDrawer source={view.source} />
    </section>
  );
};




