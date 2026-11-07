// ZEROOP2 Clinical Case Finder 도메인 타입
//
// 원칙
// - 재식별 위험 숫자(후보 수 k · 기준값 · 기준 집단 크기)는 의료진 화면 API에서 null로 온다 (백엔드 redact.py, ADR-0021).
//   같은 계약을 보안 담당자 '의료진 대화' API(/api/watch/{대화})로 받으면 숫자가 그대로 있다. 그래서 숫자 필드는 number | null.
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
  /** 환자 요약 · 유사 사례 검색의 기준 진료일 */
  visitDate?: string;
  /** 기준 진료의 진단 사건 번호, 의사가 오늘 진단을 골랐는지 */
  visitEvent?: string;
  visitChosen?: boolean;
  /** 운영 모드: EMR에서 연 환자 (차트로 돌아가는 링크) */
  fhirId?: string | null;
  /** 운영 모드: 그 환자의 등록번호 */
  regno?: string | null;
  /** AI(대상 AI 지시문)에 실제로 보내는 환자 요약 줄 */
  aiSummary?: { label: string; value: string }[];
  /** 유사 사례 검색에 쓰는 이 환자 기록: 기준일까지의 진단 · 약 · 시술 코드 수 */
  searchBasis?: { until: string; diagnoses: number; medications: number; procedures: number };
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
  /** 사례 검색 첫 답에 이 사례가 나왔는지 (false면 진단 · 항목은 '가림'이 아니라 아직 모름) */
  mentioned?: boolean;
  /** 보안 담당자가 세부 정보 요청을 승인해 공개한 단서 이름 (예: ['진단']). 카드의 진단 · 대표 항목은 승인한 값으로 보인다 */
  approved?: string[];
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
  /** 보안 담당자 화면만: 이 값을 그대로 냈다면의 후보 수 */
  kIfRaw?: number | null;
  /** 보안 담당자 규칙으로 가린 값 */
  rule?: boolean;
  /** 다시 확인을 통과하지 못해 이 사례 내용을 답에서 뺐다 (공개 방식 CASE_DROPPED) */
  dropped?: boolean;
  /** 위험 때문이 아니라 정해진 공개 단위로 바꾼 값 (나이 5세 구간 · 날짜 월, ADR-0024) */
  floor?: boolean;
  /** 조회 목적에 필요 없는 단서라 가린 값 (거주 지역, ADR-0026) */
  purpose?: boolean;
}

/** 응답 본문 조각. 보호 조치가 걸린 조각은 transformationId로 메타데이터를 가리킨다. */
export type MessageSegment =
  | { kind: 'text'; text: string }
  | {
      kind: 'disclosure';
      text: string;
      transformationId: string;
      /** 실제 LLM 답에서 지워진 가린 값의 자리 표시 (그 사례 단락 끝에 붙는다). label: '시기' · '사례 2 나이' */
      placeholder?: boolean;
      label?: string;
      /** 같은 답에 그 사례의 같은 단서가 다른 값으로 보인다: '다른 처방 약 비공개' */
      partial?: boolean;
    };

/** 답변 한 건에 대한 보호 처리 결과. */
export interface ProtectionResult {
  decision: PrivacyAction;
  transformations: PrivacyTransformation[];
  /** 백엔드가 만든 보호 처리 설명 문장 (후보 수가 들어 있어 의료진 화면 API에서는 null). */
  explanation: string | null;
  /** 의료진 화면 API에서는 null */
  kBefore: number | null;
  kAfter: number | null;
  /** 실제 백엔드만: 공개 방식 (RAW · ROUNDED · REWRITTEN · REWRITTEN_FALLBACK · CASE_DROPPED · REFUSAL · REFUSAL_EXTRACTION_FAILED · REFUSAL_TIMEOUT) */
  releaseMode?: string;
  /** 실제 백엔드만: 원 응답 QI 추출 성공 여부. false면 이번 답변의 공개가 k에 반영되지 않았을 수 있다. */
  extractionOk?: boolean;
  /** 보안 담당자 화면만: 고친 답을 다시 뽑아 확인한 기록 (시도마다) */
  checks?: ReleaseCheck[];
}

export interface ReleaseCheck {
  attempt: number;
  mode: string;
  modeLabel: string;
  ok: boolean;
  /** 이 시도에서 답에서 뺀 사례 (CASE_DROPPED) */
  dropped?: string[] | null;
  /** reason: EXTRACTION_FAILED · RAW_VALUE_LEFT(가리거나 넓히기로 한 원래 값이 글자 그대로 남음) · NO_CASE_FOUND(사례 표기를 찾지 못함) ·
   *  DROPPED_CASE_LEFT(뺀 사례의 단서가 다시 뽑힘) */
  cases: {
    case: string | null;
    kAfter: number | null;
    need: number | null;
    rule: string[] | null;
    reason: string | null;
    ok: boolean | null;
    attributeLabel?: string | null;
  }[];
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
  /** user 메시지: 질문 범위 (all이면 찾은 사례 전체에 물은 질문) */
  scope?: QuestionScope;
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
  /** 보안 담당자가 세부 정보 요청을 승인해 공개한 값 */
  approved?: boolean;
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
  /** 백엔드가 확정한 최신 누적 k (후보 수). 의료진 화면 API에서는 null */
  k: number | null;
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
  /** 이 값 초과일 때만 그대로 공개 (generalize_threshold). 의료진 화면 API에서는 null */
  minK: number | null;
  /** 원래 값으로 k가 이 값 이하이면 억제 (suppress_threshold). 의료진 화면 API에서는 null */
  suppressK: number | null;
  /** 로그 눈금 막대의 최대 후보 수 (모집단 규모). 의료진 화면 API에서는 null */
  populationSize: number | null;
  source: DataSource;
  /** 실제 LLM 대화인지 (모든 사례에 묻기 · 진행 표시는 실제 LLM 대화에서만) */
  live?: boolean;
}

export interface WorkspaceEnvironment {
  roleLabel: string;
  locationLabel: string;
}

// ── 사전 위험 평가 / 판정 근거 ────────────────────────────────────────────────

export interface SuggestedQuestion {
  label: string;
  question: string;
  /** case: 고른 사례에 묻기 · all: 찾은 사례 전체에 묻기 */
  scope?: QuestionScope;
}

/** 질문 범위: 고른 사례 하나(case) · 찾은 사례 전체(all) */
export type QuestionScope = 'case' | 'all';

export interface PreflightRiskAssessment {
  caseId: CaseId;
  question: string;
  requiresWarning: boolean;
  /** 의료진 화면 API에서는 null */
  currentK: number | null;
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
  /** oracle: 실제 LLM 대화에서 '기록대로 답한다면'으로 미리 센 값 (실제 답은 받은 뒤 다시 판정한다) */
  estimate?: 'oracle' | null;
  /** 왜 그렇게 답하는지: count 후보 수(실제 LLM은 추정) · rule 보호 담당자 규칙 · purpose 조회 목적. rule · purpose는 확정 */
  basis?: 'count' | 'rule' | 'purpose' | null;
  /** 데모 백엔드만: 짧은 시간에 미리 확인을 너무 많이 써서 판정 없이 돌려줌 (ADR-0032). 보내면 서버가 판정한다 */
  limited?: boolean;
}

// ── 의료진 ↔ 개인정보 보호 담당자 메시지 ────────────────────────────────────────

export type ClinicMessageSender = 'clinician' | 'security';
/** access_request: 의료진의 세부 정보 요청 · check_request: 보호 담당자의 확인 요청 · reply: 답장 */
export type ClinicMessageKind = 'access_request' | 'check_request' | 'reply' | 'release';

export interface ClinicMessage {
  messageId: string;
  createdAt: IsoDateTime;
  sender: ClinicMessageSender;
  kind: ClinicMessageKind;
  kindLabel: string;
  caseId: CaseId | null;
  caseLabel: string | null;
  text: string;
  /** 공개 승인 메시지: 요청한 값 가운데 일부만 공개함 (나머지는 까닭 · 대안과 함께 본문에) */
  partial?: boolean;
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
  /* 판정 근거는 보안 담당자 API에서만 온다 (의료진 화면 API는 403) */
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
  scope?: QuestionScope;
}

export interface SendQuestionResponse {
  userMessage: ChatMessage;
  assistantMessage: ChatMessage;
  riskState: CaseRiskState;
  newDisclosures: DisclosureHistoryEntry[];
  /** 이 답변이 다른 사례도 언급해 그 사례의 State가 바뀐 경우, 그 사례들의 최신 상태 (각 사례 State는 따로 쌓인다). */
  relatedRiskStates?: CaseRiskState[];
}

// ── 로그인 (python -m medicloak) ─────────────────────────────────────────────

export type UserRole = 'clinician' | 'security';

export interface AuthUser {
  userId: number;
  username: string;
  displayName: string;
  role: UserRole;
  roleLabel: string;
  department: string | null;
}

// ── 가상 EMR 외래 목록 (python -m medicloak) ─────────────────────────────────

export interface WorklistPurpose {
  trialId: string;
  /** PRESCRIPTION · TREATMENT_PROCEDURE · COURSE_CARE */
  purpose: string;
  purposeLabel: string;
  /** 이 진료 목적의 진료일 (합성 데이터의 기준일) */
  visitDate: string;
  mainDx?: string;
  item?: string;
  /** 그 진료일에 이어지던 동반질환 (AI에 보내는 요약에 들어간다) */
  comorbidity?: string | null;
}

/** 오늘 볼 진단으로 고를 수 있는 것 (그 진단의 진료일 기준 환자 요약). isDefault: 지금 기본 기준 진료 */
export interface VisitChoice {
  eventId: string;
  label: string;
  date: string;
  item?: string | null;
  comorbidity?: string | null;
  isDefault: boolean;
}

/** EMR 외래 목록 한 줄. 생년 · 거주 지역은 넣지 않는다 (환자를 고르는 데 필요 없다). */
export interface WorklistPatient {
  /** FHIR Patient.id */
  fhirId: string;
  /** 화면 표시용 앞 8자리 */
  identifier: string;
  /** 등록번호 ('26-4821', ADR-0036). 로그인 없는 서버는 없음 */
  regno?: string | null;
  sex: 'male' | 'female' | 'unknown';
  /** 가장 최근 진료일 기준 연령대 ('20대') */
  ageBand: string | null;
  /** 연령대를 센 해 (= 마지막 내원 해). 장기 미내원이면 화면이 '1998년 기준'처럼 같이 보인다 */
  ageYear?: number | null;
  conditions: string[];
  events: number;
  purposes: WorklistPurpose[];
  featured: boolean;
  /** ACTIVE 진료 중: 진행 중인 진단 · 처방 · 관리 계획이 있고 최근 3년 안에 내원 · RESOLVED 완치: 진행 중인 것이 없음 ·
   *  DORMANT 장기 미내원: 진행 중인 것이 있지만 마지막 내원이 3년보다 오래됨 */
  status: 'ACTIVE' | 'RESOLVED' | 'DORMANT';
  statusLabel: string;
  /** 진행 중인 진단 · 처방 · 관리 계획 수 (차트의 '진행 중'과 같다) */
  openItems: number;
  /** 마지막 내원일 (차트의 최근 내원과 같은 날) */
  lastRecord: string | null;
  /** 이 의료진에게 열린 까닭: 담당 환자 · 협진 의뢰 · 담당 외 예외 열람 (ADR-0034 · ADR-0036). 로그인 없는 서버는 없음 */
  access?: EmrAccessVia;
  /** 협진 의뢰 · 예외 열람이면 사유 · 끝나는 시각 */
  grant?: EmrGrant | null;
}

export type EmrAccessVia = 'assigned' | 'consult' | 'break_glass';

/** 담당 외 환자 예외 열람 (의료진에게 보이는 것) */
export interface EmrGrant {
  id: number;
  reason: string;
  reasonLabel: string;
  note: string | null;
  createdAt: number;
  /** 이 시각(초)까지 열 수 있다 */
  expiresAt: number;
  /** 협진 의뢰로 연 열람이면 그 의뢰 번호 */
  consultId?: number | null;
}

/** 협진 의뢰 (ADR-0036): 담당 의료진이 보내고, 받은 의료진은 번호 없이 연다 */
export interface EmrConsult {
  id: number;
  fhirId: string;
  regno: string | null;
  sex?: WorklistPatient['sex'];
  ageBand?: string | null;
  note: string;
  createdAt: number;
  expiresAt: number;
  status: 'pending' | 'opened' | 'declined' | 'canceled' | 'expired';
  statusLabel: string;
  /** 열거나 다시 열 수 있는지 (열기 전 · 열람함, 기한 안) */
  open: boolean;
  openedAt: number | null;
  closedAt: number | null;
  closeNote: string | null;
  sender: { username: string; displayName: string; department: string | null };
  receiver: { username: string; displayName: string; department: string | null };
}

/** 협진 의뢰를 받을 수 있는 의료진 */
export interface Clinician {
  username: string;
  displayName: string;
  department: string | null;
}

/** GET /api/emr/me: 담당 환자 수와 예외 열람 설정 */
export interface EmrMe {
  assigned: number | null;
  active?: number;
  breakGlass: { on: boolean; hours?: number; noteMin?: number; reasons?: { id: string; label: string }[] };
  /** 협진 의뢰: 받고 아직 열지 않은 수 (waiting) · 의뢰가 유효한 날 수 */
  consult?: { on: boolean; noteMin: number; days: number; hours: number; waiting: number };
}

/** 차트 요약의 한 줄: 같은 이름은 묶어 횟수 · 처음 · 마지막 날 */
export interface ChartItem {
  label: string;
  times: number;
  first: string | null;
  last: string | null;
  /** 진행 중인 진단 · 처방 · 관리 계획 */
  active: boolean;
  /** 종료일은 없지만 오래되어 진행 중으로 세지 않음 (마지막 처방이 마지막 내원보다 1년 넘게 앞섬 · 오래된 급성 질환) */
  noEnd?: boolean;
  ended: string | null;
}

export interface ChartGroup {
  items: ChartItem[];
  total: number;
  active: number;
  /** 종료일 없음(오래됨) 수 */
  noEnd?: number;
}

/** GET /api/emr/chart: 차트 요약 (생년 · 거주 지역 없음) */
export interface EmrChart {
  patient: Omit<WorklistPatient, 'purposes' | 'featured' | 'access' | 'grant'>;
  problems: ChartGroup;
  medications: ChartGroup;
  procedures: ChartGroup;
  carePlans: ChartGroup;
  /** 최근 내원: 진료마다 그날 기록된 것 (최근 것부터) */
  visits: { date: string; items: { kind: 'problems' | 'medications' | 'procedures' | 'carePlans'; label: string }[] }[];
  /** 해마다 내원한 날 수 (마지막 내원 해까지 최근 10년) */
  yearly: { year: number; visits: number }[];
  visitDays: number;
  firstRecord: string | null;
  /** 내원한 날 전체 (오래된 것부터) */
  visitDates?: string[];
  /** 가상 EMR 기준일 (합성 데이터의 마지막 기록일). 진료 상태(장기 미내원 3년)는 이 날 기준 */
  refDate?: string | null;
  /** 진료 지원 AI 목적 (목록 줄과 같음). 의료진 차트만 */
  purposes?: WorklistPurpose[];
  access?: { via: EmrAccessVia; grant: EmrGrant | null };
  /** 협진 의뢰: 보낼 수 있는지(담당 의료진만) · 이 환자로 보낸 열린 의뢰 · 이 열람을 연 받은 의뢰 */
  consult?: { canSend: boolean; sent: EmrConsult[]; received: EmrConsult | null };
}

/** 진료 지원 AI를 여는 동안의 진행 (GET /api/emr/launch/progress) */
export interface LaunchProgress {
  active: boolean;
  label?: string;
  /** 지금 단계: target(답 쓰기 · 사례 정리) · extractor(확인) · rewriter(고쳐 쓰기) · recheck(다시 확인) */
  step?: 'target' | 'extractor' | 'rewriter' | 'recheck';
  /** 멈추기를 눌러 멈추는 중 */
  stopping?: boolean;
  /** 지금까지 보낸 실제 LLM 호출 수 */
  calls?: number;
  elapsed?: number;
}

/** 이 의료진의 대화 목록 (지금 대화 · 지난 대화) */
export interface ClinicHistoryItem {
  id: string;
  trialId: string;
  startedAt: number;
  lastActive: number;
  questions: number;
  patient: string;
  purpose: string;
  /** 진료한 환자 번호 (EMR 환자 번호 앞 8자리) */
  patientId?: string | null;
  /** 진료한 환자의 등록번호 (ADR-0036) */
  regno?: string | null;
  current: boolean;
  archived: boolean;
}
