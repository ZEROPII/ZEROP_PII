// 실제 백엔드 HTTP 구현.
//
// 백엔드는 저장소 루트의 api_server/ (python -m api_server, 경로 접두사 /api). 아래 경로와 응답 모양이 그대로 맞는다.
// UI 코드는 ClinicalCaseApi만 사용한다.
// 인증은 쿠키 세션(credentials: 'include')을 전제로 해 토큰을 브라우저 저장소·로그에 두지 않는다.

import type { CaseId, SendQuestionRequest } from '../types/domain';
import { ApiError, type ClinicalCaseApi } from './types';

export function createHttpApi(baseUrl: string): ClinicalCaseApi {
  const root = baseUrl.replace(/\/+$/, '');

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${root}${path}`, {
        ...init,
        credentials: 'include',
        headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError('서버에 연결할 수 없습니다.');
    }
    if (!response.ok) {
      // 본문에 의료 데이터가 들어 있을 수 있으므로 상태 코드만 노출한다.
      throw new ApiError(`요청이 실패했습니다 (HTTP ${response.status}).`, response.status);
    }
    return (await response.json()) as T;
  }

  const c = (caseId: CaseId) => `/cases/${encodeURIComponent(caseId)}`;

  return {
    getWorkspaceEnvironment: (signal) => request('/workspace', { signal }),
    getProtectionPolicy: (signal) => request('/protection-policy', { signal }),
    getPatientContext: (signal) => request('/patient-context', { signal }),
    listSimilarCases: (patientContextId, signal) =>
      request(`/cases?patientContextId=${encodeURIComponent(patientContextId)}`, { signal }),
    getConversation: (caseId, signal) => request(`${c(caseId)}/session`, { signal }),
    sendQuestion: (req: SendQuestionRequest, signal) =>
      request(`${c(req.caseId)}/messages`, {
        method: 'POST',
        body: JSON.stringify({ sessionId: req.sessionId, question: req.question, clientMessageId: req.clientMessageId }),
        signal,
      }),
    assessPreflight: (caseId, sessionId, question, signal) =>
      request(`${c(caseId)}/preflight`, { method: 'POST', body: JSON.stringify({ sessionId, question }), signal }),
    listRiskStates: (signal) => request('/risk-states', { signal }),
    getDisclosureHistory: (caseId, signal) => request(`${c(caseId)}/disclosures`, { signal }),
    getPolicyDecision: (caseId, signal) => request(`${c(caseId)}/policy-decision`, { signal }),
  };
}
