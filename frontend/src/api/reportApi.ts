// 유사 사례 보고서 API (ADR-0042): 만들기(POST, 값이 대화의 공개로 더해진다) · 마지막 보고서 보기 · PDF 내려받기 주소.
// 서버 안내 문장(detail)에는 환자 기록이 들어 있지 않아 그대로 보여 준다.

import type { CaseReport } from '../types/domain';
import { ApiError } from './types';
import { API_BASE, notifyUnauthorized } from './session';

async function call<T>(url: string, init: RequestInit, fallback: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { credentials: 'include', ...init, headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) } });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('서버에 연결할 수 없습니다.');
  }
  if (res.status === 401) notifyUnauthorized();
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const b = (await res.json()) as { detail?: unknown };
      detail = typeof b?.detail === 'string' ? b.detail : null;
    } catch {
      detail = null;
    }
    throw new ApiError(detail ?? `${fallback} (HTTP ${res.status}).`, res.status, res.headers.get('X-MediCloak-State') ?? undefined);
  }
  return (await res.json()) as T;
}

export const reportApi = {
  /** 지금 대화의 보고서를 새로 만든다 (다시 만들면 그때까지의 답까지 합쳐 다시 판정) */
  create: () => call<CaseReport>(`${API_BASE}/clinic/report`, { method: 'POST', body: '{}' }, '보고서를 만들지 못했습니다'),
  /** 마지막으로 만든 보고서. 없으면 404 */
  get: (signal?: AbortSignal) => call<CaseReport>(`${API_BASE}/clinic/report`, { signal }, '보고서를 불러오지 못했습니다'),
  /** PDF 내려받기 (서버가 attachment로 보낸다. 데스크톱 창은 저장 창을 연다) */
  pdfUrl: `${API_BASE}/clinic/report.pdf`,
};
