import { useMemo, useState } from 'preact/hooks';
import type { EditorialAnnotation, ReviewView, SelectionTarget } from '../../app/types';
import { validateAnnotationSpan } from '../../lib/annotations';
import { EditorialEditor } from './EditorialEditor';
import { MarkdownPreview } from './MarkdownPreview';
import { EditorialDiff } from './EditorialDiff';
import { AnnotationLedger } from './AnnotationLedger';
import { AnnotationDialog } from './AnnotationDialog';
import { RevisionHistory } from './RevisionHistory';

interface Props {
  view: ReviewView;
  text: string;
  annotations: EditorialAnnotation[];
  dirty: boolean;
  saving: boolean;
  saveMessage: { type: 'success' | 'error'; text: string } | null;
  focusEditor: boolean;
  selectedTarget: SelectionTarget | null;
  onTextChange: (text: string) => void;
  onAnnotationsChange: (annotations: EditorialAnnotation[]) => void;
  onSave: (state: 'draft' | 'approved') => Promise<void>;
  onFocusEditorChange: (focus: boolean) => void;
}

interface PendingSelection {
  start: number;
  end: number;
  selectedText: string;
}

export const EditorialWorkspace = ({
  view,
  text,
  annotations,
  dirty,
  saving,
  saveMessage,
  focusEditor,
  selectedTarget,
  onTextChange,
  onAnnotationsChange,
  onSave,
  onFocusEditorChange,
}: Props) => {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [editing, setEditing] = useState<EditorialAnnotation | null>(null);
  const disabled = !view.machine.final_draft_digest;
  const displayAnnotations = useMemo(
    () => annotations.map((annotation) => ({ ...annotation, span_status: validateAnnotationSpan(annotation as unknown as Record<string, unknown>, text) })),
    [annotations, text],
  );

  const startAnnotation = (textarea: HTMLTextAreaElement) => {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = textarea.value.slice(start, end);
    if (!selectedText || start === end) {
      textarea.focus();
      return;
    }
    setEditing(null);
    setPending({ start, end, selectedText });
  };

  const editAnnotation = (annotation: EditorialAnnotation) => {
    setEditing(annotation);
    setPending({
      start: annotation.target.start,
      end: annotation.target.end,
      selectedText: annotation.target.selected_text,
    });
  };

  const saveAnnotation = (kind: string, note: string) => {
    if (!pending) return;
    const now = new Date().toISOString();
    if (editing) {
      onAnnotationsChange(annotations.map((annotation) => annotation.annotation_id === editing.annotation_id
        ? { ...annotation, kind, text: note, updated_at: now }
        : annotation));
    } else {
      const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      onAnnotationsChange([...annotations, {
        annotation_id: `annotation-${random}`,
        kind,
        text: note,
        target: {
          surface: 'editorial',
          start: pending.start,
          end: pending.end,
          selected_text: pending.selectedText,
        },
        source_unit_ids: selectedTarget?.sourceUnitIds || [],
        created_at: now,
        updated_at: now,
        span_status: 'valid',
      }]);
    }
    setPending(null);
    setEditing(null);
  };

  return (
    <section className="writing-pane" aria-labelledby="editor-heading">
      <div className="editor-heading-row">
        <div>
          <p className="eyebrow">Human editorial copy · Markdown</p>
          <h2 id="editor-heading">Working translation</h2>
        </div>
        <div className="editor-heading-actions">
          <span className={`save-state${saving ? ' saving' : dirty ? ' unsaved' : ''}`}>{saving ? 'Saving…' : dirty ? 'Unsaved' : 'Saved'}</span>
          <div className="editor-view-tabs" role="tablist" aria-label="Editorial view">
            <button className={`mini-filter ${mode === 'edit' ? 'active' : ''}`} onClick={() => setMode('edit')} type="button" role="tab" aria-selected={mode === 'edit'}>Edit</button>
            <button className={`mini-filter ${mode === 'preview' ? 'active' : ''}`} onClick={() => setMode('preview')} type="button" role="tab" aria-selected={mode === 'preview'}>Preview</button>
          </div>
        </div>
      </div>

      {mode === 'edit' ? (
        <EditorialEditor
          chunkId={view.chunk.chunk_id}
          text={text}
          dirty={dirty}
          saving={saving}
          disabled={disabled}
          focusEditor={focusEditor}
          saveMessage={saveMessage}
          onTextChange={onTextChange}
          onSave={onSave}
          onAddAnnotation={startAnnotation}
          onFocusEditorChange={onFocusEditorChange}
        />
      ) : <MarkdownPreview markdown={text} />}

      <EditorialDiff base={view.machine.final_draft || ''} editorial={text} />
      <AnnotationLedger
        annotations={displayAnnotations}
        onEdit={editAnnotation}
        onDelete={(annotationId) => onAnnotationsChange(annotations.filter((annotation) => annotation.annotation_id !== annotationId))}
      />
      <RevisionHistory history={view.editorial?.history || []} revisionCount={view.editorial?.revision_count || 0} />
      <AnnotationDialog
        open={Boolean(pending)}
        annotation={editing}
        selectedText={pending?.selectedText || ''}
        onCancel={() => { setPending(null); setEditing(null); }}
        onSave={saveAnnotation}
      />
    </section>
  );
};
