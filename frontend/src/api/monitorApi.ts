// 보안 담당자 관제 API. 데모 백엔드(python -m webdemo)에만 있다.
// Mock 모드나 api_server(실제 LLM)에서는 쓸 수 없다는 오류를 돌려주고, 화면이 그 사유를 보여 준다.

import type { AuditEntry, MonitorDetail, MonitorOverview, PocResult, RedTeamJob, ReviewAction, MonitorRow } from '../types/monitor';
import { apiMode } from './index';
import { ApiError } from './types';

export const MONITOR_UNAVAILABLE = '관제 화면은 데모 서버(python -m webdemo)에 연결했을 때만 볼 수 있습니다.';

function base(): string {
  return (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (apiMode !== 'http') throw new ApiError(MONITOR_UNAVAILABLE, 0);
  let res: Response;
  try {
    res = await fetch(`${base()}${path}`, {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('서버에 연결할 수 없습니다. 데모 서버가 켜져 있는지 확인하세요.');
  }
  if (res.status === 404 && path.startsWith('/monitor/overview')) throw new ApiError(MONITOR_UNAVAILABLE, 404);
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(detail || `요청이 실패했습니다 (HTTP ${res.status}).`, res.status);
  }
  return (await res.json()) as T;
}

export type PocSummary = Record<string, PocResult> & { fuzzer_compare?: Record<string, unknown> };

export const monitorApi = {
  overview: (signal?: AbortSignal) => request<MonitorOverview>('/monitor/overview', { signal }),
  detail: (sid: string, signal?: AbortSignal) => request<MonitorDetail>(`/monitor/sessions/${encodeURIComponent(sid)}`, { signal }),
  reveal: (sid: string, reason: string) =>
    request<MonitorDetail>(`/monitor/sessions/${encodeURIComponent(sid)}/reveal`, { method: 'POST', body: JSON.stringify({ reason }) }),
  review: (sid: string, action: ReviewAction, note?: string) =>
    request<MonitorRow>(`/monitor/sessions/${encodeURIComponent(sid)}/review`, { method: 'POST', body: JSON.stringify({ action, note }) }),
  audit: (signal?: AbortSignal) => request<AuditEntry[]>('/monitor/audit', { signal }),
  poc: (signal?: AbortSignal) => request<PocSummary>('/poc', { signal }),
  startRedTeam: (per_type: number | null, fuzzer: string) =>
    request<RedTeamJob>('/redteam', { method: 'POST', body: JSON.stringify({ per_type, fuzzer, profile: 'staged' }) }),
  job: (id: string, signal?: AbortSignal) => request<RedTeamJob>(`/redteam/${encodeURIComponent(id)}`, { signal }),
};
