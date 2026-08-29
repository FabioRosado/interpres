import { useState } from 'preact/hooks';
import type { ChunkOverview, ReviewProjectCatalog } from '../app/types';

interface Props {
  projectCatalog: ReviewProjectCatalog;
  selectedProjectId: string;
  selectedBook: number;
  overview: ChunkOverview;
  currentChunkId: string | null;
  onSelectChunk: (chunkId: string) => void;
  onSelectProject: (projectId: string) => void;
  onSelectBook: (book: number) => void;
}

export const ChunkNavigator = ({
  projectCatalog,
  selectedProjectId,
  selectedBook,
  overview,
  currentChunkId,
  onSelectChunk,
  onSelectProject,
  onSelectBook,
}: Props) => {
  const [query, setQuery] = useState('');
  const selectedProject = projectCatalog.projects.find((project) => project.id === selectedProjectId) || projectCatalog.projects[0];

  const filtered = overview.chunks.filter((chunk) => {
    if (!query.trim()) return true;
    const haystack = `${chunk.chunk_id} ${chunk.pl_start || ''} ${chunk.pl_end || ''} ${chunk.final_status}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  });

  return (
    <aside className="sidebar" aria-label="Chunk navigation">
      <div className="project-switcher">
        <label htmlFor="project-select">Project</label>
        <select
          id="project-select"
          value={selectedProjectId}
          onChange={(event) => onSelectProject((event.target as HTMLSelectElement).value)}
        >
          {projectCatalog.projects.map((project) => (
            <option key={project.id} value={project.id}>{project.title}</option>
          ))}
        </select>
        <div className="project-switcher-row">
          <span>{selectedProject?.source_label || 'Source'} → {selectedProject?.target_label || 'Target'}</span>
          <select
            aria-label="Book"
            value={selectedBook}
            onChange={(event) => onSelectBook(Number((event.target as HTMLSelectElement).value))}
          >
            {(selectedProject?.books || [overview.book]).map((book) => (
              <option key={book} value={book}>Book {book}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="sidebar-heading">
        <div>
          <p className="eyebrow">Book {overview.book}</p>
          <h2>Chunks</h2>
        </div>
        <span className="chunk-total">{overview.chunks.length}</span>
      </div>
      <div className="sidebar-search">
        <label htmlFor="chunk-search">Find a chunk</label>
        <input
          id="chunk-search"
          type="search"
          placeholder="ID, page, status…"
          value={query}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
        />
      </div>
      <nav className="chunk-list" aria-label="Available chunks">
        {filtered.map((chunk) => {
          const counts = chunk.counts;
          const issueCount = (counts.deterministic_findings || 0) + (counts.prosecutor_findings || 0) + (counts.unresolved_human_review || 0);
          const revisionCount = chunk.editorial?.revision_count || 0;
          const isActive = chunk.chunk_id === currentChunkId;
          return (
            <button
              key={chunk.chunk_id}
              className={`chunk-link${isActive ? ' active' : ''}`}
              onClick={() => onSelectChunk(chunk.chunk_id)}
              type="button"
              title={chunk.chunk_id}
            >
              <span className={`status-dot ${chunk.final_status}`} />
              <span>
                <b>
                  {chunk.chunk_id}
                  {revisionCount ? <i className="editorial-dot" title={`${revisionCount} editorial revisions`} /> : null}
                </b>
                <small>PL {chunk.pl_start || '—'}–{chunk.pl_end || '—'} · {humanize(chunk.final_status)}</small>
              </span>
              <span className="chunk-issue-count">{issueCount}</span>
            </button>
          );
        })}
        {!filtered.length && <div className="empty-state">{query ? 'No chunks match this search.' : 'No chunks are available.'}</div>}
      </nav>
    </aside>
  );
};

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
