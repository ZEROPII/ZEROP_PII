// 보안 담당자 관제 API. 데모 백엔드(python -m webdemo)에만 있다.
// Mock 모드나 api_server(실제 LLM)에서는 쓸 수 없다는 오류를 돌려주고, 화면이 그 사유를 보여 준다.

import type {
  Approval,
  AuditEntry,
  HiddenItem,
  MonitorDetail,
  MonitorOverview,
  MonitorPolicy,
  MonitorRow,
  Narrowing,
  PocResult,
  RedTeamJob,
  ReviewAction,
  ThreadResult,
  WatchItem,
} from '../types/monitor';
import { apiMode } from './index';
import { API_BASE, notifyUnauthorized } from './session';
import { ApiError } from './types';

export const MONITOR_UNAVAILABLE = '관제 화면은 데모 서버(python -m webdemo)에 연결했을 때만 볼 수 있습니다.';

function base(): string {
  return API_BASE;
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
    throw new ApiError('서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.');
  }
  if (res.status === 401) notifyUnauthorized();
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
  /** 의료진에게 답장(reply) 또는 확인 요청(check_request). case는 '사례1' 같은 사례 표시. */
  message: (sid: string, kind: 'reply' | 'check_request', text: string, caseRef?: string | null) =>
    request<ThreadResult>(`/monitor/sessions/${encodeURIComponent(sid)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ kind, text, case: caseRef ?? null }),
    }),
  thread: (sid: string, signal?: AbortSignal) => request<ThreadResult>(`/monitor/sessions/${encodeURIComponent(sid)}/messages`, { signal }),
  audit: (signal?: AbortSignal) => request<AuditEntry[]>('/monitor/audit', { signal }),
  /** 지금 적용 중인 보호 정책 (기준값 포함). 보안 담당자 API */
  policy: (signal?: AbortSignal) => request<MonitorPolicy>('/monitor/policy', { signal }),
  /** 의료진 대화 목록 (지난 대화 포함). 고른 대화는 /api/watch/{대화}/… 계약으로 본다 */
  watchList: (signal?: AbortSignal) => request<WatchItem[]>('/watch', { signal }),
  poc: (signal?: AbortSignal) => request<PocSummary>('/poc', { signal }),
  /** llm: live(서버의 실제 LLM) · oracle(결정적 응답기) · auto(실제 LLM이 있으면 live) */
  startRedTeam: (per_type: number | null, fuzzer: string, llm: 'auto' | 'live' | 'oracle' = 'auto') =>
    request<RedTeamJob>('/redteam', { method: 'POST', body: JSON.stringify({ per_type, fuzzer, profile: 'staged', llm }) }),
  cancelRedTeam: (id: string) => request<RedTeamJob>(`/redteam/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  jobs: (signal?: AbortSignal) => request<RedTeamJob[]>('/redteam', { signal }),
  job: (id: string, signal?: AbortSignal) => request<RedTeamJob>(`/redteam/${encodeURIComponent(id)}`, { signal }),
  /** 사례 하나에서 후보가 줄어든 과정 (보안 담당자 API, 숫자 그대로) */
  narrowing: (sid: string, caseId: string, signal?: AbortSignal) =>
    request<Narrowing>(`/watch/${encodeURIComponent(sid)}/cases/${encodeURIComponent(caseId)}/narrowing`, { signal }),
  /** 가리거나 넓힌 값 목록 (값 없음). 승인 공개를 고를 때 */
  hidden: (sid: string, signal?: AbortSignal) => request<HiddenItem[]>(`/monitor/sessions/${encodeURIComponent(sid)}/hidden`, { signal }),
  approve: (sid: string, items: string[], reason: string) =>
    request<{ approval: Approval; detail: MonitorDetail }>(`/monitor/sessions/${encodeURIComponent(sid)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ items, reason }),
    }),
  addRule: (sid: string, caseRef: string, attribute: string, note?: string) =>
    request<MonitorDetail>(`/monitor/sessions/${encodeURIComponent(sid)}/rules`, {
      method: 'POST',
      body: JSON.stringify({ case: caseRef, attribute, note: note || null }),
    }),
  removeRule: (sid: string, ruleId: string) =>
    request<MonitorDetail>(`/monitor/sessions/${encodeURIComponent(sid)}/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' }),
};
