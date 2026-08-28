import { useEffect, useRef } from 'preact/hooks';
import { wrapMarkdownSelection } from '../../lib/markdown';

interface Props {
  chunkId: string;
  text: string;
  dirty: boolean;
  saving: boolean;
  disabled: boolean;
  focusEditor: boolean;
  saveMessage: { type: 'success' | 'error'; text: string } | null;
  onTextChange: (text: string) => void;
  onSave: (state: 'draft' | 'approved') => Promise<void>;
  onAddAnnotation: (textarea: HTMLTextAreaElement) => void;
  onFocusEditorChange: (focus: boolean) => void;
}

export const EditorialEditor = ({
  chunkId,
  text,
  dirty,
  saving,
  disabled,
  focusEditor,
  saveMessage,
  onTextChange,
  onSave,
  onAddAnnotation,
  onFocusEditorChange,
}: Props) => {
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const saved = sessionStorage.getItem(`interpres:editor-scroll:${chunkId}`);
    if (saved && editorRef.current) editorRef.current.scrollTop = Number(saved) || 0;
  }, [chunkId]);

  const handleToolbar = (action: string) => {
    if (!editorRef.current) return;
    wrapMarkdownSelection(editorRef.current, action);
    onTextChange(editorRef.current.value);
  };

  return (
    <>
      <div className="markdown-toolbar" role="toolbar" aria-label="Markdown formatting">
        {[
          { action: 'emphasis', label: 'Emphasis' },
          { action: 'strong', label: 'Strong' },
          { action: 'quote', label: 'Quote' },
          { action: 'heading', label: 'Heading' },
          { action: 'link', label: 'Link' },
          { action: 'footnote', label: 'Footnote' },
        ].map(({ action, label }) => (
          <button key={action} type="button" onClick={() => handleToolbar(action)} aria-label={label}>{label}</button>
        ))}
        <span className="toolbar-divider" aria-hidden="true" />
        <button id="add-annotation" type="button" onClick={() => editorRef.current && onAddAnnotation(editorRef.current)} disabled={disabled}>
          Add annotation
        </button>
        <button type="button" onClick={() => onFocusEditorChange(!focusEditor)} aria-pressed={focusEditor}>
          {focusEditor ? 'Exit focus' : 'Focus editor'}
        </button>
      </div>
      <label className="editor-label" htmlFor="editor-translation">Raw Markdown editorial text</label>
      <textarea
        ref={editorRef}
        id="editor-translation"
        value={text}
        onInput={(event) => onTextChange((event.currentTarget as HTMLTextAreaElement).value)}
        onScroll={(event) => sessionStorage.setItem(`interpres:editor-scroll:${chunkId}`, String((event.currentTarget as HTMLTextAreaElement).scrollTop))}
        disabled={disabled}
        spellcheck={true}
        aria-describedby="editor-help"
        aria-label="Human editorial Markdown"
      />
      <div className="editor-status-row">
        <span id="editor-help">Machine Final is immutable. Editorial saves create append-only revisions.</span>
        <span className={`save-state${saving ? ' saving' : dirty ? ' unsaved' : ''}`} role="status">
          {saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'Saved'}
        </span>
      </div>
      <div className="editor-actions">
        <button className="primary-button secondary" onClick={() => void onSave('draft')} type="button" disabled={disabled || saving || !text.trim()}>
          Save draft revision
        </button>
        <button className="primary-button" onClick={() => void onSave('approved')} type="button" disabled={disabled || saving || !text.trim()}>
          Approve revision
        </button>
      </div>
      {saveMessage && <div className={`save-message ${saveMessage.type}`} role="status" aria-live="polite">{saveMessage.text}</div>}
    </>
  );
};
