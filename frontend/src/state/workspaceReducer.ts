// 화면 상태 (순수 reducer)
//
// - 현재 환자(patient)와 사례 데이터(cases·sessions·riskStates·disclosures)는 서로 다른 슬롯이다.
// - 대화·공개 이력·위험 상태는 모두 caseId를 키로 따로 보관해 사례끼리 섞이지 않는다.
// - 위험 상태는 백엔드가 준 version이 더 클 때만 덮어쓴다 (늦게 도착한 오래된 응답 무시).

import type {
  CaseId,
  CaseRiskState,
  CaseSummary,
  ChatMessage,
  ConversationSession,
  DisclosureHistoryEntry,
  PatientContext,
  ProtectionPolicy,
  SendQuestionResponse,
  WorkspaceEnvironment,
} from '../types/domain';

export type AsyncStatus = 'idle' | 'loading' | 'success' | 'error';

export interface Async<T> {
  status: AsyncStatus;
  data?: T;
  error?: string;
}

export interface SessionSlot extends Async<ConversationSession> {
  sending: boolean;
  /** 마지막 질문 전송 실패 사유 (대화 불러오기 오류와 구분) */
  sendError?: string;
}

export interface WorkspaceState {
  environment: Async<WorkspaceEnvironment>;
  policy: Async<ProtectionPolicy>;
  patient: Async<PatientContext>;
  cases: Async<CaseSummary[]>;
  riskStates: Async<Record<CaseId, CaseRiskState>>;
  selectedCaseId: CaseId | null;
  sessions: Record<CaseId, SessionSlot>;
  disclosures: Record<CaseId, Async<DisclosureHistoryEntry[]>>;
}

export const initialWorkspaceState: WorkspaceState = {
  environment: { status: 'idle' },
  policy: { status: 'idle' },
  patient: { status: 'idle' },
  cases: { status: 'idle' },
  riskStates: { status: 'idle' },
  selectedCaseId: null,
  sessions: {},
  disclosures: {},
};

type ResourceKey = 'environment' | 'policy' | 'patient' | 'cases' | 'riskStates';
type ResourceData = { [K in ResourceKey]: NonNullable<WorkspaceState[K]['data']> };

export type WorkspaceAction =
  | { type: 'resource/loading'; key: ResourceKey }
  | { [K in ResourceKey]: { type: 'resource/success'; key: K; data: ResourceData[K] } }[ResourceKey]
  | { type: 'resource/error'; key: ResourceKey; error: string }
  | { type: 'case/select'; caseId: CaseId }
  | { type: 'session/loading'; caseId: CaseId }
  | { type: 'session/success'; caseId: CaseId; session: ConversationSession }
  | { type: 'session/error'; caseId: CaseId; error: string }
  | { type: 'disclosures/loading'; caseId: CaseId }
  | { type: 'disclosures/success'; caseId: CaseId; entries: DisclosureHistoryEntry[] }
  | { type: 'disclosures/error'; caseId: CaseId; error: string }
  | { type: 'send/start'; caseId: CaseId; pending: ChatMessage }
  | { type: 'send/success'; caseId: CaseId; clientMessageId: string; response: SendQuestionResponse }
  | { type: 'send/failure'; caseId: CaseId; clientMessageId: string; error: string }
  | { type: 'message/discard'; caseId: CaseId; messageId: string }
  /** 다른 화면(다른 탭)에서 바뀐 대화를 조용히 받아 온다. 보내는 중인 사례는 건드리지 않는다. */
  | { type: 'session/refresh'; caseId: CaseId; session: ConversationSession }
  | { type: 'risk/apply'; risk: CaseRiskState }
  | { type: 'workspace/reset' };

function updateSession(state: WorkspaceState, caseId: CaseId, fn: (slot: SessionSlot) => SessionSlot): WorkspaceState {
  const slot = state.sessions[caseId] ?? { status: 'idle', sending: false };
  return { ...state, sessions: { ...state.sessions, [caseId]: fn(slot) } };
}

function mapMessages(slot: SessionSlot, fn: (messages: ChatMessage[]) => ChatMessage[]): SessionSlot {
  if (!slot.data) return slot;
  return { ...slot, data: { ...slot.data, messages: fn(slot.data.messages) } };
}

export function applyRiskState(state: WorkspaceState, risk: CaseRiskState): WorkspaceState {
  const current = state.riskStates.data ?? {};
  const existing = current[risk.caseId];
  if (existing && existing.version >= risk.version) return state;
  return { ...state, riskStates: { ...state.riskStates, data: { ...current, [risk.caseId]: risk } } };
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case 'resource/loading':
      return { ...state, [action.key]: { ...state[action.key], status: 'loading', error: undefined } };
    case 'resource/success':
      return { ...state, [action.key]: { status: 'success', data: action.data } };
    case 'resource/error':
      return { ...state, [action.key]: { ...state[action.key], status: 'error', error: action.error } };

    case 'case/select':
      return state.selectedCaseId === action.caseId ? state : { ...state, selectedCaseId: action.caseId };

    case 'session/loading':
      return updateSession(state, action.caseId, (s) => ({ ...s, status: 'loading', error: undefined }));
    case 'session/success':
      return updateSession(state, action.caseId, (s) => ({ ...s, status: 'success', data: action.session }));
    case 'session/error':
      return updateSession(state, action.caseId, (s) => ({ ...s, status: 'error', error: action.error }));

    case 'disclosures/loading':
      return {
        ...state,
        disclosures: { ...state.disclosures, [action.caseId]: { ...state.disclosures[action.caseId], status: 'loading', error: undefined } },
      };
    case 'disclosures/success':
      return { ...state, disclosures: { ...state.disclosures, [action.caseId]: { status: 'success', data: action.entries } } };
    case 'disclosures/error':
      return {
        ...state,
        disclosures: { ...state.disclosures, [action.caseId]: { ...state.disclosures[action.caseId], status: 'error', error: action.error } },
      };

    case 'send/start':
      return updateSession(state, action.caseId, (s) => ({
        ...mapMessages(s, (messages) => [...messages, action.pending]),
        sending: true,
        sendError: undefined,
      }));

    case 'send/success': {
      const { userMessage, assistantMessage, riskState, newDisclosures } = action.response;
      let next = updateSession(state, action.caseId, (s) => {
        const updated = mapMessages(s, (messages) => [
          ...messages.map((m) => (m.messageId === action.clientMessageId ? userMessage : m)),
          assistantMessage,
        ]);
        if (!updated.data) return { ...updated, sending: false };
        return { ...updated, sending: false, data: { ...updated.data, questionCount: Math.max(updated.data.questionCount, userMessage.turn) } };
      });
      const history = next.disclosures[action.caseId];
      if (history?.status === 'success' && history.data) {
        const known = new Set(history.data.map((e) => e.entryId));
        next = {
          ...next,
          disclosures: {
            ...next.disclosures,
            [action.caseId]: { ...history, data: [...history.data, ...newDisclosures.filter((e) => !known.has(e.entryId))] },
          },
        };
      }
      next = applyRiskState(next, riskState);
      // 다른 사례가 함께 언급돼 그 사례의 State가 바뀌었으면 위험 상태를 갱신하고, 공개 이력은 다음 선택 때 다시 불러온다.
      for (const related of action.response.relatedRiskStates ?? []) {
        if (related.caseId === action.caseId) continue;
        next = applyRiskState(next, related);
        if (next.disclosures[related.caseId]) {
          next = { ...next, disclosures: { ...next.disclosures, [related.caseId]: { status: 'idle' } } };
        }
      }
      return next;
    }

    case 'send/failure':
      return updateSession(state, action.caseId, (s) => ({
        ...mapMessages(s, (messages) => messages.map((m) => (m.messageId === action.clientMessageId ? { ...m, status: 'failed' } : m))),
        sending: false,
        sendError: action.error,
      }));

    case 'session/refresh': {
      const slot = state.sessions[action.caseId];
      if (!slot || slot.sending || slot.status !== 'success') return state;
      const known = slot.data;
      if (known && known.sessionId === action.session.sessionId && known.messages.length === action.session.messages.length) return state;
      return updateSession(state, action.caseId, (s) => ({ ...s, data: action.session }));
    }

    case 'risk/apply':
      return applyRiskState(state, action.risk);

    case 'workspace/reset':
      return initialWorkspaceState;

    case 'message/discard':
      return updateSession(state, action.caseId, (s) => ({
        ...mapMessages(s, (messages) => messages.filter((m) => m.messageId !== action.messageId)),
        sendError: undefined,
      }));
  }
}
