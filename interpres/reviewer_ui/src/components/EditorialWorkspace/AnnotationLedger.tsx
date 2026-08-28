import type { EditorialAnnotation } from '../../app/types';
import { useState } from 'preact/hooks';

interface Props {
  annotations: EditorialAnnotation[];
  onEdit: (annotation: EditorialAnnotation) => void;
  onDelete: (annotationId: string) => void;
}

export const AnnotationLedger = ({ annotations, onEdit, onDelete }: Props) => {
  const [open, setOpen] = useState(false);

  return (
    <details className="annotation-ledger" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="compact-heading">
        <span>
          <span className="eyebrow">Private editorial metadata</span>
          <b>Annotations</b>
        </span>
        <span className="issue-total">{annotations.length}</span>
      </summary>
      <div className="annotation-list">
        {annotations.map((annotation) => (
          <article key={annotation.annotation_id} className={`human-annotation ${annotation.span_status || 'valid'}`} data-annotation-id={annotation.annotation_id}>
            <div>
              <span className="pill">{humanize(annotation.kind as string)}</span>
              <b>{annotation.text as string}</b>
              <q>{annotation.target.selected_text || ''}</q>
              <span className={`span-status ${annotation.span_status}`}>
                {annotation.span_status === 'valid' ? 'Linked to text' : 'Stale span · text changed'}
              </span>
            </div>
            <div className="annotation-actions">
              <button className="text-button" type="button" onClick={() => onEdit(annotation)}>Edit</button>
              <button className="text-button danger-text" type="button" onClick={() => onDelete(annotation.annotation_id)}>Delete</button>
            </div>
          </article>
        ))}
        {!annotations.length && <div className="empty-state">Select text in the editor and choose Add annotation.</div>}
      </div>
    </details>
  );
};

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}



