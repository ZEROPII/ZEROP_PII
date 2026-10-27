// 프론트엔드 ↔ 백엔드 경계. UI는 이 인터페이스만 안다.
// Mock(mock/mockApi.ts)과 실제 HTTP(httpApi.ts)가 같은 계약을 구현한다.

import type {
  CaseId,
  CaseRiskState,
  CaseSummary,
  ConversationSession,
  DisclosureHistory,
  PatientContext,
  PolicyDecisionRationale,
  PreflightRiskAssessment,
  ProtectionPolicy,
  SendQuestionRequest,
  SendQuestionResponse,
  WorkspaceEnvironment,
} from '../types/domain';

export interface ClinicalCaseApi {
  getWorkspaceEnvironment(signal?: AbortSignal): Promise<WorkspaceEnvironment>;
  getProtectionPolicy(signal?: AbortSignal): Promise<ProtectionPolicy>;
  getPatientContext(signal?: AbortSignal): Promise<PatientContext>;
  /** 현재 환자 맥락은 id만 넘긴다. 환자 정보 자체는 사례 데이터로 흘려보내지 않는다. */
  listSimilarCases(patientContextId: string, signal?: AbortSignal): Promise<CaseSummary[]>;
  getConversation(caseId: CaseId, signal?: AbortSignal): Promise<ConversationSession>;
  /** 백엔드는 전송 시점에 공개 정책을 다시 검증한다. 사전 평가는 보조 기능일 뿐이다. */
  sendQuestion(request: SendQuestionRequest, signal?: AbortSignal): Promise<SendQuestionResponse>;
  assessPreflight(caseId: CaseId, sessionId: string, question: string, signal?: AbortSignal): Promise<PreflightRiskAssessment>;
  listRiskStates(signal?: AbortSignal): Promise<CaseRiskState[]>;
  getDisclosureHistory(caseId: CaseId, signal?: AbortSignal): Promise<DisclosureHistory>;
  getPolicyDecision(caseId: CaseId, signal?: AbortSignal): Promise<PolicyDecisionRationale>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
