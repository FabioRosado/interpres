import { useEffect, useState } from 'preact/hooks';
import type { EditorialAnnotation } from '../../app/types';

interface Props {
  open: boolean;
  annotation: EditorialAnnotation | null;
  selectedText: string;
  onCancel: () => void;
  onSave: (kind: string, text: string) => void;
}

export const AnnotationDialog = ({ open, annotation, selectedText, onCancel, onSave }: Props) => {
  const [kind, setKind] = useState('editorial_note');
  const [text, setText] = useState('');

  useEffect(() => {
    setKind(annotation?.kind || 'editorial_note');
    setText(annotation?.text || '');
  }, [annotation, open]);

  if (!open) return null;
  return (
    <dialog className="annotation-dialog" open onCancel={(event) => { event.preventDefault(); onCancel(); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (text.trim()) onSave(kind, text.trim()); }}>
        <header>
          <div>
            <p className="eyebrow">Structured editorial metadata</p>
            <h3>{annotation ? 'Edit annotation' : 'Annotate selected text'}</h3>
          </div>
          <button className="text-button" type="button" onClick={onCancel} aria-label="Close annotation dialog">Close</button>
        </header>
        <p className="annotation-selection">{selectedText}</p>
        <label className="field">
          <span>Kind</span>
          <select value={kind} onChange={(event) => setKind((event.currentTarget as HTMLSelectElement).value)}>
            <option value="editorial_note">Editorial note</option>
            <option value="translation_decision">Translation decision</option>
            <option value="context_note">Patristic / context note</option>
            <option value="scripture_reference">Scripture cross-reference</option>
            <option value="lexical_note">Lexical note</option>
            <option value="todo">TODO / research</option>
          </select>
        </label>
        <label className="field">
          <span>Note</span>
          <textarea value={text} onInput={(event) => setText((event.currentTarget as HTMLTextAreaElement).value)} maxLength={20000} required autoFocus />
        </label>
        <footer>
          <button className="quiet-button" type="button" onClick={onCancel}>Cancel</button>
          <button className="primary-button" type="submit" disabled={!text.trim()}>Save annotation</button>
        </footer>
      </form>
    </dialog>
  );
};
