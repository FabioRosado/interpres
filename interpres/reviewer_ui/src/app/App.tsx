import { useEffect, useMemo, useState } from 'preact/hooks';
import { AppHeader } from '../components/AppHeader';
import { ChunkNavigator } from '../components/ChunkNavigator';
import { ChunkToolbar } from '../components/ChunkToolbar';
import { ReviewControls } from '../components/ReviewControls';
import { SourcePane } from '../components/SourcePane/SourcePane';
import { MachineFinalPane } from '../components/MachineFinalPane/MachineFinalPane';
import { EditorialWorkspace } from '../components/EditorialWorkspace/EditorialWorkspace';
import { IssueNavigator } from '../components/IssueLedger/IssueNavigator';
import { IssueLedger } from '../components/IssueLedger/IssueLedger';
import { EvidenceInspector } from '../components/Evidence/EvidenceInspector';
import { DecisionTrail } from '../components/DecisionTrail/DecisionTrail';
import { LoadingPanel, ErrorPanel } from '../components/LoadingPanel';
import { getProjects, getOverview, getChunk, saveRevision } from '../api/reviewApi';
import type {
  AppState,
  EditorialAnnotation,
  IssueResolution,
  ReviewProjectCatalog,
  ReviewIndex,
  ReviewView,
  SelectionTarget,
} from './types';
import { initialState } from './ReviewProvider';
import { buildReviewIndex } from '../lib/annotations';

const LAST_SELECTION_KEY = 'interpres.review.lastSelection';

interface ProjectSelection {
  projectId: string;
  book: number;
}

function editorialPayload(view: ReviewView) {
  return (view.editorial?.latest as {
    editorial?: {
      translation?: string;
      annotations?: EditorialAnnotation[];
      issue_resolutions?: IssueResolution[];
      content_format?: string;
    };
    revision_id?: string;
  } | null)?.editorial;
}

function resolutionMap(items: IssueResolution[] = []): Map<string, IssueResolution> {
  return new Map(items.map((item) => [item.issue_id, { ...item }]));
}

function storedSelection(): Partial<ProjectSelection> {
  try {
    const raw = window.localStorage.getItem(LAST_SELECTION_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<ProjectSelection>;
    return {
      projectId: typeof parsed.projectId === 'string' ? parsed.projectId : undefined,
      book: Number.isFinite(Number(parsed.book)) ? Number(parsed.book) : undefined,
    };
  } catch {
    return {};
  }
}

function chooseSelection(catalog: ReviewProjectCatalog): ProjectSelection {
  const params = new URLSearchParams(window.location.search);
  const stored = storedSelection();
  const projectId = params.get('project') || stored.projectId || catalog.default_project_id;
  const project = catalog.projects.find((item) => item.id === projectId) || catalog.projects[0];
  const requestedBook = Number(params.get('book') || stored.book || project?.books[0] || 1);
  const book = project?.books.includes(requestedBook) ? requestedBook : project?.books[0] || 1;
  return { projectId: project?.id || catalog.default_project_id, book };
}

export const App = () => {
  const [state, setState] = useState<AppState>({ ...initialState, loading: true });
  const [editorialText, setEditorialText] = useState('');
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [forensicsOpen, setForensicsOpen] = useState(false);
  const [referenceMode, setReferenceMode] = useState<'latin' | 'machine'>('latin');

  useEffect(() => {
    void initialize();
  }, []);

  useEffect(() => {
    document.body.classList.toggle('editor-focus-mode', state.focusEditor);
    return () => document.body.classList.remove('editor-focus-mode');
  }, [state.focusEditor]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!state.dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [state.dirty]);

  const currentSelection = (): ProjectSelection | null => {
    if (!state.selectedProjectId) return null;
    return { projectId: state.selectedProjectId, book: state.selectedBook };
  };

  const initialize = async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const catalog = await getProjects();
      const selection = chooseSelection(catalog);
      const preferred = new URLSearchParams(window.location.search).get('chunk');
      await loadOverview(preferred, selection, catalog);
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
        loading: false,
      }));
    }
  };

  const loadOverview = async (
    preferredChunk: string | null = state.currentChunkId,
    selection: ProjectSelection | null = currentSelection(),
    catalog: ReviewProjectCatalog | null = state.projectCatalog,
  ) => {
    if (!selection || !catalog) {
      await initialize();
      return;
    }
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const overview = await getOverview(selection);
      const desired = overview.chunks.some((chunk) => chunk.chunk_id === preferredChunk)
        ? preferredChunk
        : overview.chunks[0]?.chunk_id || null;
      if (!desired) {
        installEmptyOverview(catalog, overview, selection);
        return;
      }
      const view = await getChunk(desired, selection);
      installView(catalog, overview, view, desired, selection);
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
        loading: false,
      }));
    }
  };

  const rememberSelection = (selection: ProjectSelection, chunkId: string | null) => {
    window.localStorage.setItem(LAST_SELECTION_KEY, JSON.stringify(selection));
    const url = new URL(window.location.href);
    url.searchParams.set('project', selection.projectId);
    url.searchParams.set('book', String(selection.book));
    if (chunkId) url.searchParams.set('chunk', chunkId);
    else url.searchParams.delete('chunk');
    window.history.replaceState(null, '', url);
  };

  const installEmptyOverview = (
    catalog: ReviewProjectCatalog,
    overview: AppState['overview'],
    selection: ProjectSelection,
  ) => {
    setEditorialText('');
    setSaveMessage(null);
    setForensicsOpen(false);
    setState((prev) => ({
      ...prev,
      projectCatalog: catalog,
      selectedProjectId: selection.projectId,
      selectedBook: selection.book,
      overview,
      view: null,
      reviewIndex: null,
      currentChunkId: null,
      selectedReviewTarget: null,
      selectedUnit: null,
      annotations: [],
      resolutions: new Map(),
      dirty: false,
      saving: false,
      loading: false,
      error: null,
    }));
    rememberSelection(selection, null);
  };

  const installView = (
    catalog: ReviewProjectCatalog,
    overview: AppState['overview'],
    view: ReviewView,
    chunkId: string,
    selection: ProjectSelection,
  ) => {
    const editorial = editorialPayload(view);
    const reviewIndex = buildReviewIndex(view as unknown as Record<string, unknown>) as unknown as ReviewIndex;
    setEditorialText(editorial?.translation || view.machine.final_draft || '');
    setSaveMessage(null);
    setForensicsOpen(false);
    setState((prev) => ({
      ...prev,
      projectCatalog: catalog,
      selectedProjectId: selection.projectId,
      selectedBook: selection.book,
      overview,
      view,
      reviewIndex,
      currentChunkId: chunkId,
      selectedReviewTarget: null,
      selectedUnit: null,
      evidenceInspectorOpen: false,
      issueLedgerOpen: true,
      annotations: (editorial?.annotations || []) as unknown as Record<string, unknown>[],
      resolutions: resolutionMap(editorial?.issue_resolutions),
      dirty: false,
      saving: false,
      loading: false,
      error: null,
    }));
    rememberSelection(selection, chunkId);
  };

  const loadChunk = async (chunkId: string, selection: ProjectSelection = currentSelection() || { projectId: '', book: 1 }) => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const view = await getChunk(chunkId, selection);
      installView(state.projectCatalog as ReviewProjectCatalog, state.overview, view, chunkId, selection);
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error: error instanceof Error ? error.message : String(error),
        loading: false,
      }));
    }
  };

  const requestChunk = (chunkId: string | null) => {
    if (!chunkId || chunkId === state.currentChunkId) return;
    if (state.dirty && !window.confirm('Discard unsaved editorial changes and open another chunk?')) return;
    const selection = currentSelection();
    if (!selection) return;
    void loadChunk(chunkId, selection);
  };

  const requestProject = (projectId: string) => {
    if (!state.projectCatalog || projectId === state.selectedProjectId) return;
    if (state.dirty && !window.confirm('Discard unsaved editorial changes and open another project?')) return;
    const project = state.projectCatalog.projects.find((item) => item.id === projectId);
    void loadOverview(null, { projectId, book: project?.books[0] || 1 }, state.projectCatalog);
  };

  const requestBook = (book: number) => {
    if (!state.projectCatalog || !state.selectedProjectId || book === state.selectedBook) return;
    if (state.dirty && !window.confirm('Discard unsaved editorial changes and open another book?')) return;
    void loadOverview(null, { projectId: state.selectedProjectId, book }, state.projectCatalog);
  };

  const handleSaveRevision = async (revisionState: 'draft' | 'approved') => {
    if (!state.view || !state.currentChunkId) return;
    setState((prev) => ({ ...prev, saving: true, error: null }));
    setSaveMessage(null);
    try {
      const payload = {
        state: revisionState,
        translation: editorialText,
        content_format: 'markdown',
        annotations: state.annotations,
        base_revision_id: (state.view.editorial?.latest as { revision_id?: string } | undefined)?.revision_id || null,
        machine_final_digest: state.view.machine.final_draft_digest,
        issue_resolutions: Array.from(state.resolutions.values()),
      };
      const selection = currentSelection();
      if (!selection) throw new Error('No review project is selected.');
      const result = await saveRevision(state.currentChunkId, payload, selection);
      const savedEditorial = (result.editorial.latest as { editorial?: { annotations?: EditorialAnnotation[]; issue_resolutions?: IssueResolution[] } } | null)?.editorial;
      setState((prev) => ({
        ...prev,
        dirty: false,
        saving: false,
        annotations: (savedEditorial?.annotations || prev.annotations) as unknown as Record<string, unknown>[],
        resolutions: resolutionMap(savedEditorial?.issue_resolutions || Array.from(prev.resolutions.values())),
        view: { ...prev.view, editorial: result.editorial } as ReviewView,
      }));
      setSaveMessage({ type: 'success', text: `${revisionState === 'approved' ? 'Approved' : 'Draft'} revision saved.` });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState((prev) => ({ ...prev, saving: false, error: null }));
      setSaveMessage({ type: 'error', text: message });
    }
  };

  const requestRefresh = () => {
    if (state.dirty && !window.confirm('Discard the unsaved editorial changes and refresh this chunk?')) return;
    void loadOverview(state.currentChunkId);
  };

  const handleSelectTarget = (target: SelectionTarget | null, openInspector = true) => {
    setState((prev) => ({
      ...prev,
      selectedReviewTarget: target,
      selectedUnit: target?.sourceUnitIds?.[0] || null,
      evidenceInspectorOpen: Boolean(target) && openInspector ? true : prev.evidenceInspectorOpen,
    }));
  };

  const handleClearSelection = () => {
    setState((prev) => ({ ...prev, selectedReviewTarget: null, selectedUnit: null, evidenceInspectorOpen: false }));
  };

  const updateResolution = (issueId: string, patch: Partial<IssueResolution>) => {
    setState((prev) => {
      const next = new Map(prev.resolutions);
      const existing = next.get(issueId) || {
        issue_id: issueId,
        outcome: 'deferred' as const,
        note: '',
        reusable: false,
        approved_english: '',
      };
      next.set(issueId, { ...existing, ...patch });
      return { ...prev, resolutions: next, dirty: true };
    });
  };

  const updateAnnotations = (annotations: EditorialAnnotation[]) => {
    setState((prev) => ({ ...prev, annotations: annotations as unknown as Record<string, unknown>[], dirty: true }));
  };

  const jumpToDecisionTrail = (sectionId: string | null) => {
    setForensicsOpen(true);
    window.setTimeout(() => {
      document.getElementById(sectionId || 'decision-trail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  };

  const unresolvedCount = useMemo(
    () => state.view?.issues.items.filter((issue) => (state.resolutions.get(issue.issue_id)?.outcome || 'deferred') === 'deferred').length || 0,
    [state.view, state.resolutions],
  );

  if (state.loading) return <LoadingPanel />;
  if (state.error) return <ErrorPanel error={state.error} onRetry={() => void loadOverview()} />;
  if (!state.overview || !state.projectCatalog || !state.selectedProjectId) return <ErrorPanel error="No reviewable chunks are available." onRetry={() => void loadOverview()} />;
  if (!state.view) {
    return (
      <div className={`app-shell review-mode-${state.reviewMode}${state.focusEditor ? ' editor-focus-mode' : ''}`}>
        <AppHeader onRefresh={requestRefresh} />
        <ChunkNavigator
          projectCatalog={state.projectCatalog}
          selectedProjectId={state.selectedProjectId}
          selectedBook={state.selectedBook}
          overview={state.overview}
          currentChunkId={state.currentChunkId}
          onSelectChunk={requestChunk}
          onSelectProject={requestProject}
          onSelectBook={requestBook}
        />
        <main className="review-main" id="review-main" tabIndex={-1}>
          <ErrorPanel error="No reviewable chunks are available for this project/book." onRetry={() => void loadOverview()} />
        </main>
      </div>
    );
  }
  const sourceLabel = state.view.source.label || 'Latin';

  return (
    <div className={`app-shell review-mode-${state.reviewMode}${state.focusEditor ? ' editor-focus-mode' : ''}`}>
      <AppHeader onRefresh={requestRefresh} />
      <ChunkNavigator
        projectCatalog={state.projectCatalog}
        selectedProjectId={state.selectedProjectId}
        selectedBook={state.selectedBook}
        overview={state.overview}
        currentChunkId={state.currentChunkId}
        onSelectChunk={requestChunk}
        onSelectProject={requestProject}
        onSelectBook={requestBook}
      />
      <main className="review-main" id="review-main" tabIndex={-1}>
        <div id="review-content">
          <ChunkToolbar
            chunk={state.view.chunk}
            onPrevious={() => requestChunk(state.view?.chunk.navigation.previous || null)}
            onNext={() => requestChunk(state.view?.chunk.navigation.next || null)}
          />
          <ReviewControls
            reviewMode={state.reviewMode}
            layers={state.layers}
            onModeChange={(mode) => setState((prev) => ({ ...prev, reviewMode: mode }))}
            onLayerToggle={(key, value) => setState((prev) => ({ ...prev, layers: { ...prev.layers, [key]: value } }))}
            onShowAll={() => setState((prev) => ({ ...prev, layers: Object.fromEntries(Object.keys(prev.layers).map((key) => [key, true])) }))}
            onHideIssueLayers={() => setState((prev) => ({
              ...prev,
              layers: Object.fromEntries(Object.keys(prev.layers).map((key) => [key, key === 'source_mapping' || key === 'editorial_note'])),
            }))}
            onClearSelection={handleClearSelection}
          />

          <div className="editor-workspace">
            <div className="workstation-grid">
              <aside className="reference-sidebar" aria-label={`Authoritative Source · ${sourceLabel} and immutable Machine Final`}>
                <div className="reference-tabs" role="tablist" aria-label="Reference text">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={referenceMode === 'latin'}
                    aria-controls="reference-latin"
                    className={referenceMode === 'latin' ? 'active' : ''}
                    onClick={() => setReferenceMode('latin')}
                  >
                    {sourceLabel}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={referenceMode === 'machine'}
                    aria-controls="reference-machine"
                    className={referenceMode === 'machine' ? 'active' : ''}
                    onClick={() => setReferenceMode('machine')}
                  >
                    Final review
                  </button>
                </div>
                <div className="reference-tab-panel">
                  {referenceMode === 'latin' ? (
                    <SourcePane
                      view={state.view}
                      reviewIndex={state.reviewIndex}
                      selectedTarget={state.selectedReviewTarget}
                      layers={state.layers}
                      onSelectTarget={handleSelectTarget}
                    />
                  ) : (
                    <MachineFinalPane
                      view={state.view}
                      reviewIndex={state.reviewIndex}
                      selectedTarget={state.selectedReviewTarget}
                      layers={state.layers}
                      onSelectTarget={handleSelectTarget}
                    />
                  )}
                </div>
              </aside>

              <div className="editor-column">
                <EditorialWorkspace
                  view={state.view}
                  text={editorialText}
                  annotations={state.annotations as unknown as EditorialAnnotation[]}
                  dirty={state.dirty}
                  saving={state.saving}
                  saveMessage={saveMessage}
                  focusEditor={state.focusEditor}
                  onTextChange={(text) => {
                    setEditorialText(text);
                    setState((prev) => ({ ...prev, dirty: true }));
                  }}
                  onAnnotationsChange={updateAnnotations}
                  onSave={handleSaveRevision}
                  onFocusEditorChange={(focusEditor) => setState((prev) => ({ ...prev, focusEditor }))}
                  selectedTarget={state.selectedReviewTarget}
                />

              </div>

              <aside className="issue-sidebar" aria-label="Resolution Ledger">
                <IssueNavigator
                  issues={state.view.issues.items}
                  unresolvedCount={unresolvedCount}
                  selectedTarget={state.selectedReviewTarget}
                  ledgerOpen
                  docked
                  inspectorOpen={state.evidenceInspectorOpen}
                  onSelectTarget={handleSelectTarget}
                  onToggleLedger={() => undefined}
                  onReopenInspector={() => setState((prev) => ({ ...prev, evidenceInspectorOpen: Boolean(prev.selectedReviewTarget) }))}
                />
                <IssueLedger
                  view={state.view}
                  selectedTarget={state.selectedReviewTarget}
                  resolutions={state.resolutions}
                  onResolutionChange={updateResolution}
                  onSelectTarget={handleSelectTarget}
                  docked
                />
              </aside>
            </div>
          </div>

          <details className="forensic-disclosure" open={forensicsOpen} onToggle={(event) => setForensicsOpen((event.currentTarget as HTMLDetailsElement).open)}>
            <summary>
              <span>
                <span className="eyebrow">Complete immutable record</span>
                <b>Witnesses · Evidence · Adjudication · Decision Trail</b>
              </span>
              <span>{forensicsOpen ? 'Collapse' : 'Open forensic record'}</span>
            </summary>
            <div id="decision-trail">
              <DecisionTrail view={state.view} selectedTarget={state.selectedReviewTarget} layers={state.layers} onSelectTarget={handleSelectTarget} />
            </div>
          </details>
        </div>
      </main>

      <EvidenceInspector
        open={state.evidenceInspectorOpen}
        view={state.view}
        target={state.selectedReviewTarget}
        onClose={() => setState((prev) => ({ ...prev, evidenceInspectorOpen: false }))}
        onViewDecisionTrail={jumpToDecisionTrail}
      />
    </div>
  );
};
