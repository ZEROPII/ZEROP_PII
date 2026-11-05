// 보안 담당자 관제 화면 타입 (데모 백엔드 /api/monitor, /api/poc, /api/redteam)
//
// 이름은 백엔드(webdemo/backend/monitor.py · engine.py)의 JSON 키를 그대로 쓴다.
// 원 응답·가린 원래 값·환자 번호는 열람 사유를 남긴 뒤(revealed=true)에만 채워져 온다.

import type { ProtectionPolicy } from './domain';

export type ArmKey = 'C0' | 'C1' | 'C1S';
export type MonitorStatus = 'danger' | 'caution' | 'safe';
export type ReviewAction = 'reviewed' | 'ask_clinician' | 'add_rule';

export interface ReviewMark {
  action: ReviewAction;
  label: string;
  at: number;
  actor: string;
  note: string | null;
}

export interface MonitorRow {
  id: string;
  trial_id: string;
  source: 'clinic' | 'simulation' | 'manual';
  source_label: string;
  qtype_label: string;
  turns: number;
  suppressed: number;
  generalized: number;
  status: MonitorStatus;
  status_label: string;
  focus_case: string | null;
  k_if_raw: number | null;
  k_now: number | null;
  repeated: string[];
  flag: string | null;
  violated: string[];
  last_question: string | null;
  last_active: number;
  created: number;
  review: ReviewMark | null;
  needs_review: boolean;
  /** 의료진과 주고받은 메시지 수 */
  messages: number;
  /** 마지막 메시지를 의료진이 보냈다 (보안 담당자가 답할 차례) */
  pending_request: boolean;
  /** 보안 담당자가 확인 요청을 보내고 의료진 답을 기다리는 중 */
  awaiting_clinician: boolean;
  /** 답할 차례인 요청이 가리키는 사례 ('사례1') */
  request_case: string | null;
  /** 의료진 대화: 계정 이름 (운영 모드) */
  owner?: string | null;
  /** 서버를 다시 켜기 전 대화 (DB 스냅숏, 읽기 · 검토 표시만) */
  archived?: boolean;
  /** oracle: 결정적 응답기 · live: 서버를 켤 때 정한 LLM */
  llm_mode?: 'oracle' | 'live';
}

/** 의료진 대화 목록 한 줄 (/api/watch) */
export interface WatchItem {
  id: string;
  trialId: string;
  owner: string | null;
  qtypeLabel: string;
  turns: number;
  lastActive: number;
  created: number;
  status: MonitorStatus;
  statusLabel: string;
  archived: boolean;
  /** 그 의료진이 지금 보고 있는 대화 */
  current: boolean;
  pendingRequest: boolean;
  llmMode: 'oracle' | 'live' | null;
}

/** /api/monitor/policy: 보호 정책과 서버 설정 */
export interface MonitorPolicy extends ProtectionPolicy {
  kReq: number;
  llmLive: boolean;
  compare: boolean;
  auth: boolean;
  persist: boolean;
  /** 실제 LLM 대화에 나이 · 날짜 규칙 추출을 켰는지 */
  ruleExtract?: boolean;
  /** 실제 LLM 대상 AI에 짧은 답 형식을 붙였는지 (의료진 대화 · 레드팀 같은 설정) */
  answerStyle?: boolean;
  /** 서버를 켠 뒤 의료진 대화 LLM 호출 (역할별 호출 수 · 토큰). LLM이 없으면 null */
  llmUsage?: { label: string; calls: number; by_role: Record<string, { calls: number; input_tokens: number; output_tokens: number }> } | null;
}

export interface ThreadMessage {
  id: string;
  at: number;
  sender: 'clinician' | 'security';
  /** release: 보안 담당자가 세부 정보 요청을 승인해 값을 공개함 (본문에 공개한 값이 있다) */
  kind: 'access_request' | 'check_request' | 'reply' | 'release';
  kind_label: string;
  case: string | null;
  text: string;
  actor: string;
  /** 공개 승인 메시지의 값을 지운 경우 (원문 열람 전 상세 · 메시지 목록) */
  masked?: boolean;
}

export interface ThreadResult {
  messages: ThreadMessage[];
  row: MonitorRow;
}

export interface MonitorOverview {
  kpi: {
    sessions: number;
    suppressed: number;
    generalized: number;
    identified: number;
    needs_review: number;
    blocked_sessions: number;
    /** 보안 담당자가 답할 차례인 의료진 요청 수 */
    requests: number;
  };
  sessions: MonitorRow[];
  simulations: string;
  live_arm: ArmKey;
  live_arm_label: string;
  k_req: number;
  suppress_threshold: number;
  generalize_threshold: number;
  /** 기준 집단 크기 (과거 기록 환자 전체) */
  p_ref?: number;
}

export interface AnswerLine {
  case?: string;
  field?: string;
  attribute?: string;
  value?: string | null;
  change?: 'suppress' | 'generalize' | null;
  text?: string;
}

export interface DecisionItem {
  attribute: string;
  raw_value: string | null;
  action: 'allow' | 'generalize' | 'suppress';
  to_label: string | null;
  k_raw: number | null;
  steps: number;
  utility: number;
}

export interface TurnView {
  turn: number;
  question: string;
  mode: string;
  refused: boolean;
  /** 다시 확인을 통과하지 못해 이 답에서 뺀 사례 (공개 방식 CASE_DROPPED) */
  dropped?: string[];
  lines: AnswerLine[];
  change_notes: { case: string; changes: { attribute: string; change: string }[]; k_if_raw: number | null; k_now: number | null }[];
  target_qi: string | null;
  picked_by: string | null;
  raw?: string | null;
  released?: string | null;
  raw_lines?: AnswerLine[];
  seed_id?: string | null;
  cases?: Record<string, { k: number | null; k_if_raw: number | null }>;
  decisions?: { case: string; k_before: number; k_projected: number; risky: boolean; k_final: number; items: DecisionItem[] }[];
}

export interface ArmView {
  label: string;
  case_A: string | null;
  k_series: Record<string, [number, number][]>;
  first_violation_A: number | null;
  violated_cases: string[];
  utility: number | null;
  decisions: Record<string, number>;
  turns: TurnView[];
}

/** 보안 담당자 규칙: 이 대화에서 사례 · 단서 종류는 늘 가림 (의료진 화면 갈래 C1에만) */
export interface ReviewRule {
  id: string;
  case: string;
  attribute: string;
  attribute_label: string;
  by: string;
  at: number;
  note: string | null;
  /** 이 턴부터 적용 */
  from_turn: number;
}

/** 세부 정보 요청 승인으로 공개한 값 (value는 열람 전에는 null) */
export interface ApprovalItem {
  turn: number;
  case: string;
  index: number;
  attribute: string;
  attribute_label: string;
  value: string | null;
  /** 몇 번째 턴 뒤에 공개했는지 */
  after_turn?: number;
}

export interface Approval {
  id: string;
  at: number;
  by: string;
  reason: string;
  items: ApprovalItem[];
  /** 공개한 뒤 사례별 후보 수 */
  k_after: Record<string, number>;
}

/** 가리거나 넓힌 값 (값 자체는 없다). 승인 공개를 고를 때 쓴다. */
export interface HiddenItem {
  id: string;
  turn: number;
  case: string;
  index: number;
  attribute: string;
  action: 'suppress' | 'generalize';
  kIfRaw: number | null;
  released: boolean;
  /** 다시 확인을 통과하지 못해 사례째로 답에서 뺀 값 */
  dropped?: boolean;
}

/** 사례 하나에서 후보가 줄어든 과정 (/api/watch/{대화}/cases/{사례}/narrowing) */
export interface NarrowingStep {
  attribute: string;
  attributeLabel: string;
  value: string;
  /** 이 값이 나간 턴 (0 = 사례 검색). 승인 공개는 null */
  turn: number | null;
  approved: boolean;
  /** 승인 공개: 몇 번째 턴 뒤에 공개했는지 */
  afterTurn?: number | null;
  kBefore: number;
  kAfter: number;
}

export interface NarrowingHidden {
  turn: number;
  attribute: string;
  attributeLabel: string;
  action: 'suppress' | 'generalize';
  kIfRaw: number | null;
  released: boolean;
  /** 다시 확인을 통과하지 못해 사례째로 답에서 뺀 값 */
  dropped?: boolean;
}

export interface Narrowing {
  case: string;
  caseId: string;
  label: string;
  population: number;
  generalizeK: number;
  suppressK: number;
  k: number;
  steps: NarrowingStep[];
  hidden: NarrowingHidden[];
  rules: { attribute: string; attributeLabel: string }[];
}

export interface MonitorDetail {
  id: string;
  trial_id: string;
  patient: string | null;
  qtype_label: string;
  profile_label: string;
  turn: number;
  budget: number;
  k_req: number;
  p_ref: number;
  source: string;
  source_label: string;
  arms: Record<ArmKey, ArmView>;
  retrieval: { ref: string; patient: string | null; score: number }[];
  row: MonitorRow;
  revealed: boolean;
  live_arm: ArmKey;
  messages: ThreadMessage[];
  /** 서버를 다시 켜기 전 대화 (메시지는 보낼 수 없다) */
  archived?: boolean;
  rules?: ReviewRule[];
  approvals?: Approval[];
  /** 검토 보조 초안 상태 (세부 정보 요청이 오면 서버가 뒤에서 만든다) */
  assist?: AssistState;
}

/** 검토 보조: 가린 값 하나의 판정 (값 원문은 없다) */
export interface AssistItem {
  id: string;
  turn: number;
  where: string;
  case: string;
  attribute: string;
  attributeLabel: string;
  action: 'generalize' | 'suppress' | 'dropped';
  actionLabel: string;
  /** 조회 목적에 쓰이는 정도: 직접 · 범위로 충분 · 관련 적음 */
  need: 'need' | 'coarse' | 'low';
  needLabel: string;
  kNow: number | null;
  /** 이 값 하나만 지금 공개했을 때 후보 수 */
  kIfRelease: number | null;
  rec: 'release' | 'consider' | 'keep' | 'decline';
  recLabel: string;
  why: string;
  alternative: string | null;
}

export interface AssistDraft {
  case: string | null;
  caseLabel: string;
  purpose: string;
  purposeLabel: string;
  requestId: string;
  requestText: string;
  kReq: number;
  kNow: number | null;
  items: AssistItem[];
  /** 함께 열어도 기준 이상인 값 (승인 창에 미리 고를 것) */
  release: string[];
  combinedK: number | null;
  counts: Record<'release' | 'consider' | 'keep' | 'decline', number>;
  verdict: 'release' | 'partial' | 'consider' | 'keep' | 'none';
  verdictLabel: string;
  /** 검토 보조가 확인한 것 (순서대로) */
  steps: { label: string; detail: string }[];
  summary: string;
  /** 의료진 답장 초안 (숫자 없음) */
  reply: string;
  /** 공개 승인 사유 초안 (공개 가능 값이 있을 때) */
  reason: string;
  reasonFit?: '구체적' | '불분명' | '목적과 다름';
  reasonNote?: string;
  writer: 'llm' | 'template';
  writerLabel: string;
  createdAt: number;
}

export interface AssistState {
  status: 'none' | 'running' | 'ready' | 'error';
  requestId?: string;
  startedAt?: number;
  finishedAt?: number;
  draft?: AssistDraft;
  error?: string;
}

export interface AuditEntry {
  id: string;
  at: number;
  actor: string;
  action: string;
  session: string | null;
  trial: string | null;
  reason?: string;
  note?: string | null;
  job?: string;
  /** 메시지 기록만: 가리킨 사례 ('사례1') */
  case?: string | null;
  /** 운영 모드: 계정 번호 */
  user_id?: number;
  /** 검토 보조 초안(assist_draft): 추천 · 추천별 수 · 쓴 방식 */
  verdict?: string;
  counts?: Partial<Record<'release' | 'consider' | 'keep' | 'decline', number>>;
  writer?: 'llm' | 'template';
  /** 의료진 질문(clinic_question): 대화 턴 · 공개 방식 · 보호한 값 수 */
  turn?: number | null;
  release?: string | null;
  protected?: number;
  /** EMR 열기(emr_launch): 진료 목적 */
  purpose?: string;
  /** 로그인 기록: 접속 주소 */
  client?: string;
  /** 규칙 기록: 단서 종류 */
  attribute?: string;
  /** 공개 승인: 공개한 항목 (값 없음) */
  items?: { turn: number; case: string; attribute: string }[];
  /** 레드팀 시작: live · oracle, 유형마다 질의 환자 수 */
  llm?: string;
  per_type?: number | null;
}

export interface Proportion {
  k: number;
  n: number;
  p: number;
  ci: [number, number];
}

export interface PocArm {
  label: string;
  n: number;
  viol8: Proportion;
  viol10: Proportion;
  viol_any: Proportion;
  turn0: Proportion;
  first_median: number | null;
  cumulative: number[];
  kA_median: number[];
  kA_q1: number[];
  kA_q3: number[];
  /** 답변 유용도. 판정한 단서가 하나도 없으면 null */
  utility: number | null;
  decisive: Record<string, number>;
  overblock: Proportion;
}

export interface PocResult {
  arms: Partial<Record<ArmKey, PocArm>>;
  paired: Record<string, { only_first: number; only_second: number; p_value: number | null }>;
  config: Record<string, unknown>;
}

export interface RedTeamJob {
  id: string;
  /** 서버의 실제 LLM으로 돌렸는지 (false = 결정적 응답기) */
  live?: boolean;
  model?: string | null;
  /** 실제 LLM 실행의 대상 AI 답 형식. 이 설정이 생기기 전 실행은 없음(= 지시 없음) */
  answer_style?: 'on' | 'off' | null;
  profile_label: string;
  fuzzer: string;
  fuzzer_label: string;
  per_type: number | null;
  /** 질의 환자(trial) 수 */
  trials?: number;
  /** 갈래별 대화 수 (trial × 3) */
  total: number;
  /** 끝낸 갈래별 대화 수 (LLM 오류로 뺀 것 포함) */
  done: number;
  /** 집계에 넣은 갈래별 대화 수 (세 갈래를 다 끝낸 질의 환자만) */
  kept?: number;
  /** LLM 호출이 실패해 집계에서 뺀 질의 환자 수 */
  llm_error_trials?: number;
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled' | 'interrupted';
  error: string | null;
  elapsed: number | null;
  /** 남은 시간 추정 (초) */
  eta?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
  usage?: { calls: number; input_tokens: number; output_tokens: number };
  last?: string;
  result: PocResult | null;
}
