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
  /** 서버를 켠 뒤 의료진 대화 LLM 호출 (역할별 호출 수 · 토큰). LLM이 없으면 null */
  llmUsage?: { label: string; calls: number; by_role: Record<string, { calls: number; input_tokens: number; output_tokens: number }> } | null;
}

export interface ThreadMessage {
  id: string;
  at: number;
  sender: 'clinician' | 'security';
  kind: 'access_request' | 'check_request' | 'reply';
  kind_label: string;
  case: string | null;
  text: string;
  actor: string;
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
  /** 의료진 질문(clinic_question): 대화 턴 · 공개 방식 · 보호한 값 수 */
  turn?: number | null;
  release?: string | null;
  protected?: number;
  /** EMR 열기(emr_launch): 진료 목적 */
  purpose?: string;
  /** 로그인 기록: 접속 주소 */
  client?: string;
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
  utility: number;
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
  profile_label: string;
  fuzzer: string;
  fuzzer_label: string;
  per_type: number | null;
  total: number;
  done: number;
  status: 'queued' | 'running' | 'done' | 'error';
  error: string | null;
  elapsed: number | null;
  result: PocResult | null;
}
