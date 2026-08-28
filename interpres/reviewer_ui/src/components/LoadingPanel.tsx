export const LoadingPanel = () => (
  <div className="loading-panel" id="loading-panel">
    <p className="eyebrow">Reading machine and editorial records</p>
    <h2>Preparing the workspace…</h2>
  </div>
);

export const ErrorPanel = ({ error, onRetry }: { error: string; onRetry: () => void }) => (
  <div className="error-panel" id="error-panel">
    <p className="eyebrow">Workspace unavailable</p>
    <h2>These records could not be displayed safely.</h2>
    <p id="error-message">{error}</p>
    <button className="quiet-button" onClick={onRetry}>Try again</button>
  </div>
);