interface Props {
  onRefresh: () => void;
  onExport: () => void;
  onImport: (file: File) => void;
  transferMessage: string | null;
}

export const AppHeader = ({ onRefresh, onExport, onImport, transferMessage }: Props) => (
  <header className="masthead">
    <div className="brand-lockup">
      <div className="brand-mark" aria-hidden="true">H</div>
      <div>
        <p className="eyebrow">Commentaria in Ezechielem</p>
        <h1>Editorial desk</h1>
      </div>
    </div>
    <div className="masthead-actions">
      <span className="safety-pill">Machine record locked</span>
      {transferMessage ? <span className="transfer-message">{transferMessage}</span> : null}
      <button className="quiet-button dark" onClick={onExport} type="button">Export</button>
      <label className="quiet-button dark import-button">
        Import
        <input
          type="file"
          accept="application/json,.json"
          onChange={(event) => {
            const input = event.target as HTMLInputElement;
            const file = input.files?.[0];
            if (file) onImport(file);
            input.value = '';
          }}
        />
      </label>
      <button className="quiet-button dark" onClick={onRefresh} type="button">Refresh</button>
    </div>
  </header>
);
