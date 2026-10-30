import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { api as defaultApi, type ClinicalCaseApi } from '../api';
import type { CaseId, ChatMessage } from '../types/domain';
import { initialWorkspaceState, workspaceReducer, type WorkspaceState } from './workspaceReducer';

export interface WorkspaceActions {
  reloadAll(): void;
  selectCase(caseId: CaseId): void;
  loadSession(caseId: CaseId, force?: boolean): void;
  loadDisclosures(caseId: CaseId, force?: boolean): void;
  sendQuestion(caseId: CaseId, question: string): Promise<boolean>;
  retryMessage(caseId: CaseId, message: ChatMessage): void;
  discardMessage(caseId: CaseId, messageId: string): void;
  /** 새 대화로 다시 시작 (trialId를 주면 그 질의 환자로). 백엔드가 지원할 때만. */
  restart(trialId?: string): Promise<void>;
}

interface WorkspaceContextValue {
  state: WorkspaceState;
  actions: WorkspaceActions;
  api: ClinicalCaseApi;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다.';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

let clientSeq = 0;

export function WorkspaceProvider({ children, api = defaultApi }: { children: ReactNode; api?: ClinicalCaseApi }) {
  const [state, dispatch] = useReducer(workspaceReducer, initialWorkspaceState);
  const stateRef = useRef(state);
  stateRef.current = state;

  const loadSession = useCallback(
    (caseId: CaseId, force = false) => {
      const slot = stateRef.current.sessions[caseId];
      if (!force && (slot?.status === 'loading' || slot?.status === 'success')) return;
      dispatch({ type: 'session/loading', caseId });
      api.getConversation(caseId).then(
        (session) => dispatch({ type: 'session/success', caseId, session }),
        (error) => dispatch({ type: 'session/error', caseId, error: errorMessage(error) }),
      );
    },
    [api],
  );

  const loadDisclosures = useCallback(
    (caseId: CaseId, force = false) => {
      const slot = stateRef.current.disclosures[caseId];
      if (!force && (slot?.status === 'loading' || slot?.status === 'success')) return;
      dispatch({ type: 'disclosures/loading', caseId });
      api.getDisclosureHistory(caseId).then(
        (history) => dispatch({ type: 'disclosures/success', caseId, entries: history.entries }),
        (error) => dispatch({ type: 'disclosures/error', caseId, error: errorMessage(error) }),
      );
    },
    [api],
  );

  const reloadAll = useCallback(() => {
    dispatch({ type: 'resource/loading', key: 'environment' });
    api.getWorkspaceEnvironment().then(
      (data) => dispatch({ type: 'resource/success', key: 'environment', data }),
      (error) => dispatch({ type: 'resource/error', key: 'environment', error: errorMessage(error) }),
    );

    dispatch({ type: 'resource/loading', key: 'policy' });
    api.getProtectionPolicy().then(
      (data) => dispatch({ type: 'resource/success', key: 'policy', data }),
      (error) => dispatch({ type: 'resource/error', key: 'policy', error: errorMessage(error) }),
    );

    dispatch({ type: 'resource/loading', key: 'riskStates' });
    api.listRiskStates().then(
      (list) => dispatch({ type: 'resource/success', key: 'riskStates', data: Object.fromEntries(list.map((r) => [r.caseId, r])) }),
      (error) => dispatch({ type: 'resource/error', key: 'riskStates', error: errorMessage(error) }),
    );

    dispatch({ type: 'resource/loading', key: 'patient' });
    dispatch({ type: 'resource/loading', key: 'cases' });
    api.getPatientContext().then(
      (patient) => {
        dispatch({ type: 'resource/success', key: 'patient', data: patient });
        // 사례 검색에는 환자 맥락의 id만 넘긴다.
        return api.listSimilarCases(patient.contextId).then(
          (cases) => {
            const sorted = [...cases].sort((a, b) => a.similarityRank - b.similarityRank);
            dispatch({ type: 'resource/success', key: 'cases', data: sorted });
            const selected = stateRef.current.selectedCaseId;
            if (sorted.length && (!selected || !sorted.some((c) => c.caseId === selected))) {
              dispatch({ type: 'case/select', caseId: sorted[0].caseId });
            }
          },
          (error) => dispatch({ type: 'resource/error', key: 'cases', error: errorMessage(error) }),
        );
      },
      (error) => {
        dispatch({ type: 'resource/error', key: 'patient', error: errorMessage(error) });
        dispatch({ type: 'resource/error', key: 'cases', error: '환자 맥락을 불러오지 못해 사례를 검색할 수 없습니다.' });
      },
    );
  }, [api]);

  const sendQuestion = useCallback(
    async (caseId: CaseId, question: string): Promise<boolean> => {
      const text = question.trim();
      const slot = stateRef.current.sessions[caseId];
      if (!text || !slot?.data || slot.sending) return false;

      const clientMessageId = `client-${Date.now()}-${++clientSeq}`;
      const pending: ChatMessage = {
        messageId: clientMessageId,
        caseId,
        role: 'user',
        turn: slot.data.questionCount + 1,
        createdAt: new Date().toISOString(),
        segments: [{ kind: 'text', text }],
        status: 'pending',
      };
      dispatch({ type: 'send/start', caseId, pending });
      try {
        const response = await api.sendQuestion({ caseId, sessionId: slot.data.sessionId, question: text, clientMessageId });
        // 응답은 요청한 사례에만 반영한다 (그 사이 다른 사례를 골랐어도 섞이지 않음).
        dispatch({ type: 'send/success', caseId, clientMessageId, response });
        return true;
      } catch (error) {
        if (!isAbort(error)) dispatch({ type: 'send/failure', caseId, clientMessageId, error: errorMessage(error) });
        return false;
      }
    },
    [api],
  );

  const discardMessage = useCallback((caseId: CaseId, messageId: string) => {
    dispatch({ type: 'message/discard', caseId, messageId });
  }, []);

  const retryMessage = useCallback(
    (caseId: CaseId, message: ChatMessage) => {
      const text = message.segments.map((s) => s.text).join('');
      dispatch({ type: 'message/discard', caseId, messageId: message.messageId });
      void sendQuestion(caseId, text);
    },
    [sendQuestion],
  );

  const selectCase = useCallback((caseId: CaseId) => dispatch({ type: 'case/select', caseId }), []);

  const restart = useCallback(
    async (trialId?: string) => {
      if (!api.resetSession) return;
      await api.resetSession(trialId);
      dispatch({ type: 'workspace/reset' });
      reloadAll();
    },
    [api, reloadAll],
  );

  useEffect(() => {
    reloadAll();
  }, [reloadAll]);

  useEffect(() => {
    if (!state.selectedCaseId) return;
    loadSession(state.selectedCaseId);
    loadDisclosures(state.selectedCaseId);
  }, [state.selectedCaseId, loadSession, loadDisclosures]);

  const actions = useMemo<WorkspaceActions>(
    () => ({ reloadAll, selectCase, loadSession, loadDisclosures, sendQuestion, retryMessage, discardMessage, restart }),
    [reloadAll, selectCase, loadSession, loadDisclosures, sendQuestion, retryMessage, discardMessage, restart],
  );

  const value = useMemo(() => ({ state, actions, api }), [state, actions, api]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace는 WorkspaceProvider 안에서만 쓸 수 있습니다.');
  return ctx;
}

/** 선택된 사례에 묶인 데이터만 모아 준다. */
export function useSelectedCase() {
  const { state } = useWorkspace();
  const caseId = state.selectedCaseId;
  return {
    caseId,
    summary: state.cases.data?.find((c) => c.caseId === caseId) ?? null,
    session: caseId ? state.sessions[caseId] : undefined,
    risk: caseId ? state.riskStates.data?.[caseId] : undefined,
    disclosures: caseId ? state.disclosures[caseId] : undefined,
  };
}
