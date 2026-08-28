import type { SourceUnit } from '../../app/types';

interface Props {
  units: SourceUnit[];
  activeUnit: string | null;
  onSelect: (unitId: string | null) => void;
}

export const SourceUnitTabs = ({ units, activeUnit, onSelect }: Props) => (
  <div className="unit-tabs" id="source-unit-tabs" aria-label="Source units">
    {units.map((unit) => (
      <button
        key={unit.source_unit_id}
        className={`unit-button ${activeUnit === unit.source_unit_id ? 'active' : ''}`}
        onClick={() => onSelect(activeUnit === unit.source_unit_id ? null : unit.source_unit_id)}
        type="button"
        data-unit-id={unit.source_unit_id}
      >
        {unit.source_unit_id}
      </button>
    ))}
  </div>
);