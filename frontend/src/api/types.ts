// 프론트엔드 ↔ 백엔드 경계. UI는 이 인터페이스만 안다.
// Mock(mock/mockApi.ts)과 실제 HTTP(httpApi.ts)가 같은 계약을 구현한다.

import type {
  CaseId,
  CaseRiskState,
  CaseSummary,
  ClinicHistoryItem,
  ClinicMessage,
  ConversationSession,
  DisclosureHistory,
  PatientContext,
  PolicyDecisionRationale,
  PatientOption,
  PostClinicMessageRequest,
  PreflightRiskAssessment,
  ProtectionPolicy,
  SendQuestionRequest,
  SendQuestionResponse,
  SuggestedQuestion,
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
  /** 이 사례에 지금 물어볼 수 있는 예시 질문. 지원하지 않는 백엔드는 빈 목록. */
  listSuggestions?(caseId: CaseId, signal?: AbortSignal): Promise<SuggestedQuestion[]>;
  /** 데모 백엔드만: 다른 질의 환자로 새 대화를 시작할 때 고를 목록 */
  listPatients?(signal?: AbortSignal): Promise<PatientOption[]>;
  /** 새 대화(빈 State)로 다시 시작. trialId를 주면 그 질의 환자로. */
  resetSession?(trialId?: string): Promise<void>;
  /**
   * 지금 대화에서 개인정보 보호 담당자와 주고받은 메시지. null이면 이 백엔드는 메시지를 지원하지 않는다
   * (화면에서 세부 정보 요청 버튼을 숨긴다).
   */
  listClinicMessages?(signal?: AbortSignal): Promise<ClinicMessage[] | null>;
  /** 세부 정보 요청 또는 확인 요청에 대한 답장. 보낸 뒤의 전체 메시지 목록을 돌려준다. */
  postClinicMessage?(request: PostClinicMessageRequest): Promise<ClinicMessage[]>;
  /** 이 의료진의 대화 목록 (지금 대화 · 지난 대화). 지원하지 않는 백엔드는 빈 목록. */
  listHistory?(signal?: AbortSignal): Promise<ClinicHistoryItem[]>;
}

/**
 * 오래 걸린 POST(진료 지원 AI 열기 · 질문 · 보고서)는 서버가 200으로 먼저 열고 공백으로 연결을 살려 두다가,
 * 실패하면 상태 코드 대신 본문 { detail, _status, _state }로 알린다 (ADR-0044). 그 본문이면 실패 내용을, 아니면 null.
 */
export function streamedFailure(body: unknown): { status: number; detail: string | null; flag?: string } | null {
  if (!body || typeof body !== 'object') return null;
  const b = body as { _status?: unknown; detail?: unknown; _state?: unknown };
  if (typeof b._status !== 'number' || b._status < 400) return null;
  return { status: b._status, detail: typeof b.detail === 'string' ? b.detail : null, flag: typeof b._state === 'string' ? b._state : undefined };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    /** 서버가 머리글(X-MediCloak-State)로 알린 상태. 예: 'no-conversation' = 운영 모드에서 아직 연 환자가 없음 */
    readonly state?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** 운영 모드: 의료진이 아직 EMR에서 환자를 열지 않아 진료 지원 AI 대화가 없다. */
export function isNoConversation(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.state === 'no-conversation';
}
