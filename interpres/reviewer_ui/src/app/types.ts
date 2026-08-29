export interface SelectionTarget {
  id: string;
  type: 'source_unit' | 'issue' | 'finding' | 'evidence' | 'adjudicator_edit' | 'annotation' | string;
  sourceUnitIds: string[];
  findingIds: string[];
  evidenceIds: string[];
  editIds: string[];
  issueIds: string[];
  sourceSpans?: { start: number; end: number }[];
  finalSpans?: { start: number; end: number; quality?: 'precise' | 'coarse' }[];
  decisionTrailId: string | null;
  label: string;
  raw: Record<string, unknown>;
}

export interface IssueResolution {
  issue_id: string;
  outcome: 'deferred' | 'resolved' | 'accepted_as_is';
  note: string;
  reusable: boolean;
  approved_english: string;
}

export interface EditorialAnnotation {
  annotation_id: string;
  kind: string;
  text: string;
  target: {
    surface: 'editorial';
    start: number;
    end: number;
    selected_text: string;
  };
  source_unit_ids: string[];
  created_at: string;
  updated_at: string;
  span_status?: 'valid' | 'stale';
}

export interface AnnotationRecord {
  id: string;
  type: string;
  layer: string;
  sourceUnitIds: string[];
  findingIds: string[];
  evidenceIds: string[];
  editIds: string[];
  issueIds: string[];
  textQuote: string | null;
  startQuote: string | null;
  endQuote: string | null;
  replacementQuote: string | null;
  label: string | null;
  decisionTrailId: string | null;
  raw: Record<string, unknown>;
  kind?: string;
  text?: string;
  span_status?: string;
}

export interface ReviewIndex {
  annotations: AnnotationRecord[];
  byIssue: Map<string, AnnotationRecord>;
  byUnit: Map<string, AnnotationRecord[]>;
  byEdit: Map<string, AnnotationRecord>;
}

export interface SourceUnit {
  source_unit_id: string;
  book: number;
  page: string | null;
  clean_start: number;
  clean_end: number;
  text: string;
}

export interface SourceView {
  state: string;
  target_latin: string;
  source_text?: string;
  label?: string;
  language?: string;
  context_before: string | null;
  context_after: string | null;
  units: SourceUnit[];
  spans: Record<string, unknown>[];
  page_markers: Record<string, unknown>[];
  annotations: Record<string, unknown>[];
}

export interface MachineView {
  immutable: boolean;
  final_status: string;
  final_draft: string | null;
  final_draft_digest: string;
  pipeline_version: string | null;
  prompt_version: string | null;
  schema_version: string | null;
  execution_profile: string | null;
  source_fingerprint: string | null;
  final_artifact_id: string | null;
}

export interface WitnessView {
  witness_id: string;
  label: string;
  available: boolean;
  state: string;
  provider: string | null;
  model: string | null;
  translation: string | null;
  source_mappings: Record<string, unknown>[];
  uncertainty: Record<string, unknown>[];
  uncertainty_recorded: boolean;
  validation: Record<string, unknown>;
  validation_recorded: boolean;
  eligible_as_adjudicator_base: boolean;
  authority_role: string;
  may_corroborate: boolean;
  is_evidence: boolean;
}

export interface IssueView {
  issue_id: string;
  source_record_id: string;
  origin: string;
  type: string | null;
  severity: string | null;
  status: string | null;
  message: string | null;
  latin: string | null;
  english: string | null;
  source_unit_ids: string[];
  evidence_ids: string[];
  reusable_eligible: boolean;
}

export interface AdjudicatorView {
  available: boolean;
  state: string;
  status: string | null;
  summary: string | null;
  base_witness: string | null;
  findings: Record<string, unknown>[];
  edits: Record<string, unknown>[];
  unresolved_issues: Record<string, unknown>[];
  human_review_requests: Record<string, unknown>[];
  evidence_requests: Record<string, unknown>[];
  decision_basis: Record<string, unknown>[];
  coverage: Record<string, unknown>;
  edit_validation_error: Record<string, unknown> | null;
}

export interface EvidenceView {
  available: boolean;
  stages: Record<string, { available: boolean; state: string }>;
  receipts: Record<string, unknown>[];
}

export interface FinalView {
  available: boolean;
  status: string;
  translation: string | null;
  base_witness: string | null;
  applied_edit_count: number;
  diff: { kind: string; text: string }[];
  source_mappings: Record<string, unknown>[];
  mapping_available: boolean;
}

export interface VerificationView {
  coverage_assertion: boolean | null;
  source_units_total: number;
  source_units_accounted_for: number | null;
  missing_source_unit_ids: string[];
  exact_edit_validation: string;
  schema_status_validation: string;
  final_checks: Record<string, unknown>;
  incomplete_stages: { stage: string; state: string; error: Record<string, unknown> | null }[];
}

export interface StructuralView {
  available: boolean;
  state: string;
  sentences: Record<string, unknown>[];
  intrinsic_ambiguity: Record<string, unknown>[];
  context_dependent: Record<string, unknown>[];
  unverified_analyses: Record<string, unknown>[];
}

export interface MorphologyView {
  available: boolean;
  state: string;
  backend: Record<string, unknown> | null;
  flags: Record<string, unknown>[];
  entries: Record<string, unknown>[];
}

export interface ChunkInfo {
  book: number | null;
  chunk_id: string;
  pl_start: string | null;
  pl_end: string | null;
  pages: string[];
  source_unit_count: number;
  final_status: string;
  witness_quorum: string | null;
  witness_mode: string | null;
  automatic_acceptance_allowed: boolean;
  counts: {
    witness_disagreements: number | null;
    deterministic_findings: number;
    prosecutor_findings: number;
    adjudicator_edits: number;
    unresolved_human_review: number;
  };
  navigation: { previous: string | null; next: string | null };
  editorial?: {
    revision_count: number;
    state: string | null;
    based_on_current_machine_final: boolean;
  };
}

export interface EditorialState {
  schema_version: string;
  storage_mode: string;
  machine_artifacts_immutable: boolean;
  latest: Record<string, unknown> | null;
  history: Record<string, unknown>[];
  revision_count: number;
  based_on_current_machine_final: boolean;
}

export interface ReviewView {
  review_schema_version: string;
  project?: Record<string, unknown>;
  chunk: ChunkInfo;
  source: SourceView;
  machine: MachineView;
  witness_quorum: Record<string, unknown>;
  issues: { items: IssueView[]; count: number; origins: string[]; note: string };
  review_links: {
    persisted: Record<string, unknown>;
    unavailable: Record<string, boolean>;
    note: string;
  };
  witnesses: WitnessView[];
  disagreements: { available: boolean; items: Record<string, unknown>[]; note: string | null };
  structural: StructuralView;
  morphology: MorphologyView;
  deterministic: {
    available: boolean;
    state: string;
    summary: Record<string, unknown>;
    findings: Record<string, unknown>[];
    substantive_findings: Record<string, unknown>[];
    limits: string | null;
  };
  prosecutor: {
    initial: Record<string, unknown>;
    grounded: Record<string, unknown>;
    transition_mapping_recorded: boolean;
    transition_note: string;
  };
  evidence: EvidenceView;
  adjudicator: AdjudicatorView;
  final: FinalView;
  verification: VerificationView;
  run_details: Record<string, unknown>[];
  artifact_errors: Record<string, unknown>[];
  lineage?: Record<string, unknown> & { historical_record_count?: number };
  stage_history?: Record<string, unknown>[];
  filters: Record<string, boolean>;
  editorial?: EditorialState;
}

export interface ChunkOverview {
  review_schema_version: string;
  book: number;
  profile: string;
  chunks: ChunkInfo[];
  artifact_errors: Record<string, unknown>[];
}

export type ReviewMode = 'review' | 'focus' | 'clean';
export type EditorMode = 'edit' | 'preview';
export type IssueFilter = 'open' | 'resolved' | 'all';
export type ReferenceTab = 'source' | 'machine';

export interface AppState {
  overview: ChunkOverview | null;
  view: ReviewView | null;
  currentChunkId: string | null;
  selectedUnit: string | null;
  selectedReviewTarget: SelectionTarget | null;
  referenceTab: ReferenceTab;
  editorMode: EditorMode;
  evidenceInspectorOpen: boolean;
  evidenceInspectorMinimized: boolean;
  issueLedgerOpen: boolean;
  splitPercent: number;
  focusEditor: boolean;
  issueFilter: IssueFilter;
  reviewMode: ReviewMode;
  layers: Record<string, boolean>;
  reviewIndex: ReviewIndex | null;
  resolutions: Map<string, IssueResolution>;
  annotations: Record<string, unknown>[];
  dirty: boolean;
  saving: boolean;
  loading: boolean;
  error: string | null;
}

export type AppAction =
  | { type: 'SET_OVERVIEW'; payload: ChunkOverview }
  | { type: 'SET_VIEW'; payload: ReviewView }
  | { type: 'SET_CURRENT_CHUNK'; payload: string | null }
  | { type: 'SELECT_UNIT'; payload: string | null }
  | { type: 'SELECT_TARGET'; payload: SelectionTarget | null }
  | { type: 'SET_REFERENCE_TAB'; payload: ReferenceTab }
  | { type: 'SET_EDITOR_MODE'; payload: EditorMode }
  | { type: 'SET_EVIDENCE_INSPECTOR_OPEN'; payload: boolean }
  | { type: 'SET_EVIDENCE_INSPECTOR_MINIMIZED'; payload: boolean }
  | { type: 'SET_ISSUE_LEDGER_OPEN'; payload: boolean }
  | { type: 'SET_SPLIT_PERCENT'; payload: number }
  | { type: 'SET_FOCUS_EDITOR'; payload: boolean }
  | { type: 'SET_ISSUE_FILTER'; payload: IssueFilter }
  | { type: 'SET_REVIEW_MODE'; payload: ReviewMode }
  | { type: 'SET_LAYER'; payload: { key: string; value: boolean } }
  | { type: 'SET_REVIEW_INDEX'; payload: ReviewIndex | null }
  | { type: 'SET_RESOLUTION'; payload: { issue_id: string; patch: Record<string, unknown> } }
  | { type: 'SET_ANNOTATIONS'; payload: Record<string, unknown>[] }
  | { type: 'ADD_ANNOTATION'; payload: Record<string, unknown> }
  | { type: 'UPDATE_ANNOTATION'; payload: { id: string; patch: Record<string, unknown> } }
  | { type: 'DELETE_ANNOTATION'; payload: string }
  | { type: 'SET_DIRTY'; payload: boolean }
  | { type: 'SET_SAVING'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'RESOLVE_EDITORIAL'; payload: EditorialState };
