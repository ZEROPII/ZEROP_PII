// 실제 백엔드 HTTP 구현.
//
// 백엔드는 저장소 루트의 api_server/ (python -m api_server, 경로 접두사 /api). 아래 경로와 응답 모양이 그대로 맞는다.
// UI 코드는 ClinicalCaseApi만 사용한다.
// 인증은 쿠키 세션(credentials: 'include')을 전제로 해 토큰을 브라우저 저장소·로그에 두지 않는다.

import type { CaseId, PatientOption, SendQuestionRequest, SuggestedQuestion } from '../types/domain';
import { ApiError, type ClinicalCaseApi } from './types';

const STATUS_MESSAGE: Record<number, string> = {
  404: '요청한 사례나 대화를 찾지 못했습니다. 화면을 새로 불러오세요.',
  409: '대화가 새로 시작되어 이 화면의 내용이 오래되었습니다. 화면을 새로 불러오세요.',
  422: '질문을 보낼 수 없습니다. 내용을 확인한 뒤 다시 보내세요.',
  502: '대상 AI 호출에 실패했습니다. 잠시 뒤 다시 보내세요 (상태는 바뀌지 않았습니다).',
};

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
      // 본문에 의료 데이터가 들어 있을 수 있으므로 상태 코드에 맞춘 고정 문구만 보여 준다.
      throw new ApiError(STATUS_MESSAGE[response.status] ?? `요청이 실패했습니다 (HTTP ${response.status}).`, response.status);
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
    // 아래 셋은 데모 백엔드(python -m webdemo)에만 있다. api_server에서는 404 → 빈 목록 / 기능 없음으로 처리.
    listSuggestions: (caseId, signal) =>
      request<SuggestedQuestion[]>(`${c(caseId)}/suggestions`, { signal }).catch((error) => {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }),
    listPatients: (signal) =>
      request<PatientOption[]>('/clinic/patients', { signal }).catch((error) => {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }),
    resetSession: async (trialId) => {
      await request('/session/reset', { method: 'POST', body: JSON.stringify(trialId ? { trialId } : {}) });
    },
  };
}
