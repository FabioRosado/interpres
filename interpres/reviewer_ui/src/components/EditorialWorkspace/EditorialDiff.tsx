import { textDiff } from '../../lib/mappings';

interface Props {
  base: string;
  editorial: string;
}

export const EditorialDiff = ({ base, editorial }: Props) => {
  const diff = textDiff(base, editorial);

  return (
    <details className="editorial-diff-drawer">
      <summary>Editorial diff from machine final</summary>
      <div className="editorial-diff">
        {diff.map((segment, i) => {
          if (segment.kind === 'equal') return <span key={i}>{segment.text}</span>;
          if (segment.kind === 'delete') return <del key={i}>{segment.text}</del>;
          if (segment.kind === 'insert') return <ins key={i}>{segment.text}</ins>;
          return <span key={i}>{segment.text}</span>;
        })}
      </div>
    </details>
  );
};