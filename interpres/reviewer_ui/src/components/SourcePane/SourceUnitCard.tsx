import type { SourceUnit } from '../../app/types';

interface Props {
  unit: SourceUnit;
  isSelected: boolean;
  hasFinalMapping: boolean;
  hasWitnessMapping: boolean;
  onClick: () => void;
}

export const SourceUnitCard = ({ unit, isSelected, hasFinalMapping, hasWitnessMapping, onClick }: Props) => {
  return (
    <article
      className={`latin-unit ${isSelected ? 'selected' : ''}`}
      data-unit-id={unit.source_unit_id}
      onClick={onClick}
      tabIndex={0}
      role="button"
      aria-pressed={isSelected}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick();
        }
      }}
    >
      <span className="unit-label">{unit.source_unit_id} · PL {unit.page || '—'}</span>
      <p className="latin-text">{unit.text || ''}</p>
      <div className="source-badges">
        <span className={`source-badge ${hasFinalMapping ? '' : 'warning'}`}>
          {hasFinalMapping ? 'final mapped' : 'final not mapped'}
        </span>
        {!hasWitnessMapping && <span className="source-badge warning">witness not mapped</span>}
      </div>
    </article>
  );
};
