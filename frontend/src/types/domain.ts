// ZEROOP2 Clinical Case Finder 도메인 타입
//
// 원칙
// - 현재 환자(PatientContext)와 검색된 사례(CaseSummary 이하)는 서로 다른 데이터 영역이다.
//   PatientContext는 질문 전송·응답 표시 어디에도 섞이지 않는다.
// - k 계산, QI 결합, 누적 State 판정은 백엔드(risk_defender / medical.defense)의 몫이다.
//   프론트엔드는 백엔드가 확정해 보낸 값만 표시한다.
// - 보호 대상 원본 값(일반화 이전의 정확한 나이·날짜 등)은 어떤 타입에도 담지 않는다.

export type IsoDateTime = string;
export type CaseId = string;

/** 데이터 출처. mock이면 UI에 Mock 표시를 붙인다. */
export type DataSource = 'mock' | 'backend';

// ── 현재 환자 맥락 (의료진의 진료 맥락, 사례 데이터와 분리) ──────────────────────

export interface PatientContext {
  contextId: string;
  ageSexLabel: string;
  primaryDiagnosis: string;
  comorbidities: string[];
  plannedProcedure: string;
  queryPurpose: string;
  source: DataSource;
  /** 데모 백엔드만: 질의 환자 trial 번호 (POC와 같은 번호) */
  trialId?: string;
}

// ── 검색된 사례 ────────────────────────────────────────────────────────────────

export interface CaseSummary {
  caseId: CaseId;
  /** 화면 표시용 별칭 (예: "사례 A"). 실제 환자 식별자가 아니다. */
  label: string;
  diagnosis: string;
  description: string;
  similarityRank: number;
  /** 검색 유사도 (있을 때만) */
  similarity?: number;
}

// ── 보호 조치 ──────────────────────────────────────────────────────────────────

/** 공개 항목에 적용된 조치. medical/defense.py의 allow·generalize·suppress와 같다. */
export type PrivacyAction = 'allow' | 'generalize' | 'suppress';

/** 응답 속 한 공개 항목에 적용된 보호 조치 (백엔드 판정 결과). */
export interface PrivacyTransformation {
  id: string;
  /** QI 종류 코드 (AGE, DATE, LOC, SEX, DX, PROC, COMORBID …) */
  attribute: string;
  attributeLabel: string;
  action: PrivacyAction;
  /** 실제로 공개된 값. suppress면 null. */
  disclosedValue: string | null;
  /** 안전한 수준 설명. 예: "정확한 연령 → 5세 구간". 원본 값은 담지 않는다. */
  levelDescription?: string;
  /** 데모 백엔드만: 이 조치가 걸린 사례 표기 (사례1 …) */
  caseRef?: string;
}

/** 응답 본문 조각. 보호 조치가 걸린 조각은 transformationId로 메타데이터를 가리킨다. */
export type MessageSegment =
  | { kind: 'text'; text: string }
  | { kind: 'disclosure'; text: string; transformationId: string };

/** 답변 한 건에 대한 보호 처리 결과. */
export interface ProtectionResult {
  decision: PrivacyAction;
  transformations: PrivacyTransformation[];
  /** 백엔드가 만든 보호 처리 설명 문장. */
  explanation: string;
  kBefore: number;
  kAfter: number;
  /** 실제 백엔드만: 공개 방식 (RAW · REWRITTEN · REWRITTEN_FALLBACK · REFUSAL · REFUSAL_EXTRACTION_FAILED) */
  releaseMode?: string;
  /** 실제 백엔드만: 원 응답 QI 추출 성공 여부. false면 이번 답변의 공개가 k에 반영되지 않았을 수 있다. */
  extractionOk?: boolean;
}

// ── 대화 ──────────────────────────────────────────────────────────────────────

export type ChatRole = 'user' | 'assistant';
export type MessageDeliveryStatus = 'sent' | 'pending' | 'failed';

export interface ChatMessage {
  messageId: string;
  caseId: CaseId;
  role: ChatRole;
  turn: number;
  createdAt: IsoDateTime;
  segments: MessageSegment[];
  /** assistant 메시지에만. 보호 조치가 없었다면 생략될 수 있다. */
  protection?: ProtectionResult;
  status: MessageDeliveryStatus;
  /** 데모 백엔드만: 대화 전체의 턴 번호 (공개 이력 turn과 같은 번호). 답할 기록이 없었으면 null. */
  engineTurn?: number | null;
}

export interface ConversationSession {
  sessionId: string;
  caseId: CaseId;
  messages: ChatMessage[];
  questionCount: number;
}

// ── 공개 이력 ─────────────────────────────────────────────────────────────────

export interface DisclosureHistoryEntry {
  entryId: string;
  turn: number;
  attribute: string;
  attributeLabel: string;
  action: PrivacyAction;
  /** 안전한 설명만. 예: "정확한 연령 → 5세 구간" */
  description: string;
  /** 데모 백엔드만: 답에 실제로 나간 값 (그대로면 원래 값, 넓혔으면 넓힌 값, 가렸으면 null) */
  value?: string | null;
}

export interface DisclosureHistory {
  caseId: CaseId;
  entries: DisclosureHistoryEntry[];
}

// ── 누적 위험 상태 ────────────────────────────────────────────────────────────

export type RiskLevel = 'safe' | 'caution' | 'danger' | 'blocked';

/** Defender의 정책 판정 상태. restrict = 추가 QI 공개 제한(k가 기준 이하). */
export type PolicyDecisionState = 'allow' | 'generalize' | 'suppress' | 'restrict';

export interface CaseRiskState {
  caseId: CaseId;
  /** 백엔드가 확정한 최신 누적 k (후보 수) */
  k: number;
  riskLevel: RiskLevel;
  /** 백엔드 표시 문구. 예: "주의", "여유", "추가 공개 제한" */
  statusLabel: string;
  disclosureAllowed: boolean;
  policyDecision: PolicyDecisionState;
  /** 단조 증가 버전. 오래된 응답이 새 상태를 덮어쓰지 않게 한다. */
  version: number;
  updatedAt: IsoDateTime;
}

// ── 보호 정책 / 근무 환경 ─────────────────────────────────────────────────────

export interface ProtectionPolicy {
  modeLabel: string;
  /** C0 방어 없음 / C1 누적 State Defender / C1S 매 턴 빈 State */
  arm: 'C0' | 'C1' | 'C1S';
  stateModeLabel: string;
  /** 이 값 초과일 때만 그대로 공개 (generalize_threshold) */
  minK: number;
  /** 원래 값으로 k가 이 값 이하이면 억제 (suppress_threshold) */
  suppressK: number;
  /** 로그 눈금 막대의 최대 후보 수 (모집단 규모) */
  populationSize: number;
  source: DataSource;
}

export interface WorkspaceEnvironment {
  roleLabel: string;
  locationLabel: string;
}

// ── 사전 위험 평가 / 판정 근거 ────────────────────────────────────────────────

export interface SuggestedQuestion {
  label: string;
  question: string;
}

export interface PreflightRiskAssessment {
  caseId: CaseId;
  question: string;
  requiresWarning: boolean;
  currentK: number;
  projectedK: number | null;
  message: string | null;
  affectedAttributes: string[];
  suggestions: SuggestedQuestion[];
  source: DataSource;
  /** false면 백엔드에 사전 평가 기능이 없다 (실제 연구 모듈에는 질문만으로 k를 계산하는 기능이 없음). */
  supported?: boolean;
  /** 데모 백엔드만: 질문에서 묻는 항목을 찾았는지 */
  understood?: boolean;
  /** 데모 백엔드만: 보내면 어떻게 답할지. 의료진 화면은 후보 수 대신 이것으로 안내한다. */
  plannedAction?: 'suppress' | 'generalize' | null;
  /** 데모 백엔드만: 질문이 가리킨 사례 (고른 사례와 다를 수 있다. 예: 사례 1 탭에서 '사례5 환자의 나이는?') */
  targetCaseId?: CaseId | null;
  targetCaseLabel?: string | null;
}

// ── 의료진 ↔ 개인정보 보호 담당자 메시지 ────────────────────────────────────────

export type ClinicMessageSender = 'clinician' | 'security';
/** access_request: 의료진의 세부 정보 요청 · check_request: 보호 담당자의 확인 요청 · reply: 답장 */
export type ClinicMessageKind = 'access_request' | 'check_request' | 'reply';

export interface ClinicMessage {
  messageId: string;
  createdAt: IsoDateTime;
  sender: ClinicMessageSender;
  kind: ClinicMessageKind;
  kindLabel: string;
  caseId: CaseId | null;
  caseLabel: string | null;
  text: string;
}

export interface PostClinicMessageRequest {
  kind: 'access_request' | 'reply';
  text: string;
  caseId?: CaseId | null;
}

/** 데모 백엔드의 질의 환자 목록 (다른 환자로 대화를 새로 시작할 때) */
export interface PatientOption {
  trialId: string;
  qtypeLabel: string;
  featured: boolean;
  ageSex?: string;
  mainDx?: string;
  item?: string;
}

export interface PolicyDecisionRationale {
  caseId: CaseId;
  currentK: number;
  minK: number;
  suppressK: number;
  arm: ProtectionPolicy['arm'];
  disclosedQis: { attributeLabel: string; levelDescription: string }[];
  generalized: { attributeLabel: string; levelDescription: string }[];
  suppressed: { attributeLabel: string }[];
  finalDecision: PolicyDecisionState;
  finalDecisionLabel: string;
  notes: string[];
  stateVersion: number;
  source: DataSource;
}

// ── API 입출력 ────────────────────────────────────────────────────────────────

export interface SendQuestionRequest {
  caseId: CaseId;
  sessionId: string;
  question: string;
  /** 클라이언트 쪽 임시 메시지와 응답을 잇는 키 */
  clientMessageId: string;
}

export interface SendQuestionResponse {
  userMessage: ChatMessage;
  assistantMessage: ChatMessage;
  riskState: CaseRiskState;
  newDisclosures: DisclosureHistoryEntry[];
  /** 이 답변이 다른 사례도 언급해 그 사례의 State가 바뀐 경우, 그 사례들의 최신 상태 (각 사례 State는 따로 쌓인다). */
  relatedRiskStates?: CaseRiskState[];
}
