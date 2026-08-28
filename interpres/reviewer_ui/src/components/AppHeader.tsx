interface Props {
  onRefresh: () => void;
}

export const AppHeader = ({ onRefresh }: Props) => (
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
      <button className="quiet-button dark" onClick={onRefresh} type="button">Refresh</button>
    </div>
  </header>
);