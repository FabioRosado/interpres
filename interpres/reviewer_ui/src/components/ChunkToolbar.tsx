import type { ChunkInfo } from '../app/types';

interface Props {
  chunk: ChunkInfo;
  onPrevious: () => void;
  onNext: () => void;
}

export const ChunkToolbar = ({ chunk, onPrevious, onNext }: Props) => (
  <section className="chunk-toolbar" aria-labelledby="chunk-title">
    <div className="chunk-heading">
      <div>
        <p className="eyebrow" id="chunk-kicker">Book {chunk.book || 1} · PL {chunk.pl_start || '—'}</p>
        <h2 id="chunk-title">{chunk.chunk_id}</h2>
        <p className="chunk-id" id="chunk-id">{chunk.source_unit_count} source units</p>
      </div>
      <div className="toolbar-status">
        <span className={`status-badge ${chunk.final_status}`}>{humanize(chunk.final_status)}</span>
        {chunk.editorial && (
          <span className={`revision-badge ${chunk.editorial.state === 'approved' ? 'approved' : ''}`}>
            Revision {chunk.editorial.revision_count} · {chunk.editorial.state ? humanize(chunk.editorial.state) : 'No editorial revision'}
          </span>
        )}
        {!chunk.editorial && <span className="revision-badge">No editorial revision</span>}
        <div className="nav-pair">
          <button className="quiet-button" onClick={onPrevious} type="button" disabled={!chunk.navigation.previous}>← Previous</button>
          <button className="quiet-button" onClick={onNext} type="button" disabled={!chunk.navigation.next}>Next →</button>
        </div>
      </div>
    </div>
  </section>
);

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
