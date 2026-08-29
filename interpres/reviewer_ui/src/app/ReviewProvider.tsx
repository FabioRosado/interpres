import { buildReviewIndex, targetFromUnit } from '../lib/annotations';
import type { AppState, AppAction, SelectionTarget, ReviewIndex, IssueResolution } from './types';

export const initialState: AppState = {
  projectCatalog: null,
  selectedProjectId: null,
  selectedBook: 1,
  overview: null,
  view: null,
  currentChunkId: null,
  selectedUnit: null,
  selectedReviewTarget: null,
  referenceTab: 'source',
  editorMode: 'edit',
  evidenceInspectorOpen: false,
  evidenceInspectorMinimized: false,
  issueLedgerOpen: true,
  splitPercent: 48,
  focusEditor: false,
  issueFilter: 'open',
  reviewMode: 'review',
  layers: {
    deterministic: true,
    witness_disagreement: true,
    prosecutor: true,
    evidence: true,
    adjudicator: true,
    adjudicator_edit: true,
    unresolved: true,
    human_review: true,
    verification: true,
    source_mapping: true,
    editorial_note: true,
  },
  reviewIndex: null,
  resolutions: new Map(),
  annotations: [],
  dirty: false,
  saving: false,
  loading: false,
  error: null,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_OVERVIEW':
      return { ...state, overview: action.payload, loading: false, error: null };
    case 'SET_VIEW': {
      const reviewIndex = buildReviewIndex(action.payload as unknown as Record<string, unknown>);
      return {
        ...state,
        view: action.payload,
        reviewIndex: reviewIndex as unknown as ReviewIndex,
        annotations: [],
        resolutions: new Map(),
        loading: false,
        error: null,
      };
    }
    case 'RESOLVE_EDITORIAL':
      return { ...state, view: { ...state.view, editorial: action.payload } as AppState['view'] };
    case 'SET_CURRENT_CHUNK':
      return { ...state, currentChunkId: action.payload, selectedUnit: null, selectedReviewTarget: null };
    case 'SELECT_UNIT': {
      if (!action.payload) return { ...state, selectedUnit: null, selectedReviewTarget: null };
      const target = targetFromUnit(action.payload, state.reviewIndex);
      return { ...state, selectedUnit: action.payload, selectedReviewTarget: target as SelectionTarget };
    }
    case 'SELECT_TARGET':
      return { ...state, selectedReviewTarget: action.payload, selectedUnit: action.payload?.sourceUnitIds?.[0] || null };
    case 'SET_REFERENCE_TAB':
      return { ...state, referenceTab: action.payload };
    case 'SET_EDITOR_MODE':
      return { ...state, editorMode: action.payload };
    case 'SET_EVIDENCE_INSPECTOR_OPEN':
      return { ...state, evidenceInspectorOpen: action.payload };
    case 'SET_EVIDENCE_INSPECTOR_MINIMIZED':
      return { ...state, evidenceInspectorMinimized: action.payload };
    case 'SET_ISSUE_LEDGER_OPEN':
      return { ...state, issueLedgerOpen: action.payload };
    case 'SET_SPLIT_PERCENT':
      return { ...state, splitPercent: action.payload };
    case 'SET_FOCUS_EDITOR':
      return { ...state, focusEditor: action.payload };
    case 'SET_ISSUE_FILTER':
      return { ...state, issueFilter: action.payload };
    case 'SET_REVIEW_MODE':
      return { ...state, reviewMode: action.payload };
    case 'SET_LAYER':
      return { ...state, layers: { ...state.layers, [action.payload.key]: action.payload.value } };
    case 'SET_REVIEW_INDEX':
      return { ...state, reviewIndex: action.payload };
    case 'SET_RESOLUTION': {
      const next = new Map(state.resolutions);
      const existing = next.get(action.payload.issue_id) || {
        issue_id: action.payload.issue_id,
        outcome: 'deferred',
        note: '',
        reusable: false,
        approved_english: '',
      } as IssueResolution;
      next.set(action.payload.issue_id, { ...existing, ...action.payload.patch } as IssueResolution);
      return { ...state, resolutions: next };
    }
    case 'SET_ANNOTATIONS':
      return { ...state, annotations: action.payload };
    case 'ADD_ANNOTATION':
      return { ...state, annotations: [...state.annotations, action.payload] };
    case 'UPDATE_ANNOTATION':
      return { ...state, annotations: state.annotations.map((a) => (a.annotation_id === action.payload.id ? { ...a, ...action.payload.patch } : a)) };
    case 'DELETE_ANNOTATION':
      return { ...state, annotations: state.annotations.filter((a) => a.annotation_id !== action.payload) };
    case 'SET_DIRTY':
      return { ...state, dirty: action.payload };
    case 'SET_SAVING':
      return { ...state, saving: action.payload };
    case 'SET_LOADING':
      return { ...state, loading: action.payload, error: null };
    case 'SET_ERROR':
      return { ...state, error: action.payload, loading: false };
    default:
      return state;
  }
}
