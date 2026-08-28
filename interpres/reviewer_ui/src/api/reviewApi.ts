import type { ChunkOverview, ReviewView, EditorialState } from '../app/types';

const API_BASE = '/api';

export async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options?.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.message || payload?.error || `Request failed (${response.status})`) as Error & { status: number };
    error.status = response.status;
    throw error;
  }
  return payload as T;
}

export async function getOverview(): Promise<ChunkOverview> {
  return requestJson<ChunkOverview>('/chunks');
}

export async function getChunk(chunkId: string): Promise<ReviewView> {
  return requestJson<ReviewView>(`/chunks/${encodeURIComponent(chunkId)}`);
}

export async function saveRevision(
  chunkId: string,
  payload: Record<string, unknown>,
): Promise<{ saved: boolean; revision: Record<string, unknown>; editorial: EditorialState }> {
  return requestJson(`/chunks/${encodeURIComponent(chunkId)}/editorial/revisions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function checkHealth(): Promise<{ status: string; mode: string; book: string }> {
  return requestJson<{ status: string; mode: string; book: string }>('/health');
}