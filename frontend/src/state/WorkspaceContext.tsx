import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { api as defaultApi, type ClinicalCaseApi } from '../api';
import { isNoConversation } from '../api/types';
import type { CaseId, ChatMessage, QuestionScope } from '../types/domain';
import { initialWorkspaceState, workspaceReducer, type WorkspaceState } from './workspaceReducer';

export interface WorkspaceActions {
  reloadAll(): void;
  selectCase(caseId: CaseId): void;
  loadSession(caseId: CaseId, force?: boolean): void;
  loadDisclosures(caseId: CaseId, force?: boolean): void;
  sendQuestion(caseId: CaseId, question: string, scope?: QuestionScope): Promise<boolean>;
  retryMessage(caseId: CaseId, message: ChatMessage): void;
  discardMessage(caseId: CaseId, messageId: string): void;
  /** 새 대화로 다시 시작 (trialId를 주면 그 질의 환자로). 백엔드가 지원할 때만. */
  restart(trialId?: string): Promise<void>;
  /** 서버 쪽에서 대화가 바뀐 뒤(EMR에서 다른 환자를 엶) 화면 상태를 비우고 처음부터 다시 받는다. */
  resetAndReload(): void;
  /**
   * 열어 둔 대화·공개 이력·후보 수를 로딩 표시 없이 새로 받는다 (보안 담당자 '의료진 대화' 화면이 주기적으로 부른다).
   * 그 사이 의료진이 새 대화를 시작했으면 처음부터 다시 불러온다.
   */
  refreshLive(): Promise<void>;
  /** 사례 목록(카드의 진단 · 대표 항목 · 승인 표시)만 로딩 표시 없이 새로 받는다. 답을 받은 뒤 · 공개 승인이 온 뒤 */
  refreshCases(): Promise<void>;
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
      (error) => dispatch(isNoConversation(error) ? { type: 'workspace/none' } : { type: 'resource/error', key: 'environment', error: errorMessage(error) }),
    );

    dispatch({ type: 'resource/loading', key: 'policy' });
    api.getProtectionPolicy().then(
      (data) => dispatch({ type: 'resource/success', key: 'policy', data }),
      (error) => dispatch(isNoConversation(error) ? { type: 'workspace/none' } : { type: 'resource/error', key: 'policy', error: errorMessage(error) }),
    );

    dispatch({ type: 'resource/loading', key: 'riskStates' });
    api.listRiskStates().then(
      (list) => dispatch({ type: 'resource/success', key: 'riskStates', data: Object.fromEntries(list.map((r) => [r.caseId, r])) }),
      (error) => dispatch(isNoConversation(error) ? { type: 'workspace/none' } : { type: 'resource/error', key: 'riskStates', error: errorMessage(error) }),
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
        if (isNoConversation(error)) {
          dispatch({ type: 'workspace/none' });
          return;
        }
        dispatch({ type: 'resource/error', key: 'patient', error: errorMessage(error) });
        dispatch({ type: 'resource/error', key: 'cases', error: '환자 맥락을 불러오지 못해 사례를 검색할 수 없습니다.' });
      },
    );
  }, [api]);

  const refreshCases = useCallback(async () => {
    const ctx = stateRef.current.patient.data?.contextId;
    if (!ctx) return;
    try {
      const cases = [...(await api.listSimilarCases(ctx))].sort((a, b) => a.similarityRank - b.similarityRank);
      const now = stateRef.current;
      if (now.patient.data?.contextId !== ctx) return; // 그 사이 다른 환자를 열었다
      if (JSON.stringify(now.cases.data) !== JSON.stringify(cases)) dispatch({ type: 'resource/success', key: 'cases', data: cases });
    } catch {
      /* 다음에 다시 받는다 */
    }
  }, [api]);

  const sendQuestion = useCallback(
    async (caseId: CaseId, question: string, scope: QuestionScope = 'case'): Promise<boolean> => {
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
        scope,
      };
      dispatch({ type: 'send/start', caseId, pending });
      try {
        const response = await api.sendQuestion({ caseId, sessionId: slot.data.sessionId, question: text, clientMessageId, scope });
        // 응답은 요청한 사례에만 반영한다 (그 사이 다른 사례를 골랐어도 섞이지 않음).
        dispatch({ type: 'send/success', caseId, clientMessageId, response });
        void refreshCases(); // 첫 답에 없던 진단 · 항목이 이 답에 나왔으면 카드에 채운다
        return true;
      } catch (error) {
        if (!isAbort(error)) dispatch({ type: 'send/failure', caseId, clientMessageId, error: errorMessage(error) });
        return false;
      }
    },
    [api, refreshCases],
  );

  const discardMessage = useCallback((caseId: CaseId, messageId: string) => {
    dispatch({ type: 'message/discard', caseId, messageId });
  }, []);

  const retryMessage = useCallback(
    (caseId: CaseId, message: ChatMessage) => {
      const text = message.segments.map((s) => s.text).join('');
      dispatch({ type: 'message/discard', caseId, messageId: message.messageId });
      void sendQuestion(caseId, text, message.scope ?? 'case');
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

  const resetAndReload = useCallback(() => {
    dispatch({ type: 'workspace/reset' });
    reloadAll();
  }, [reloadAll]);

  const refreshLive = useCallback(async () => {
    const before = stateRef.current;
    try {
      const patient = await api.getPatientContext();
      if (before.patient.data && patient.contextId !== before.patient.data.contextId) {
        dispatch({ type: 'workspace/reset' });
        reloadAll();
        return;
      }
      const risks = await api.listRiskStates();
      for (const risk of risks) dispatch({ type: 'risk/apply', risk });
      const now = stateRef.current;
      await Promise.all([
        ...Object.entries(now.sessions)
          .filter(([, slot]) => slot.status === 'success' && !slot.sending)
          .map(([caseId]) => api.getConversation(caseId).then((session) => dispatch({ type: 'session/refresh', caseId, session }))),
        ...Object.entries(now.disclosures)
          .filter(([, slot]) => slot.status === 'success')
          .map(([caseId]) =>
            api.getDisclosureHistory(caseId).then((h) => {
              const known = stateRef.current.disclosures[caseId]?.data;
              if (!known || known.length !== h.entries.length) dispatch({ type: 'disclosures/success', caseId, entries: h.entries });
            }),
          ),
      ]);
    } catch {
      /* 다음 주기에 다시 받는다 */
    }
  }, [api, reloadAll]);

  useEffect(() => {
    reloadAll();
  }, [reloadAll]);

  useEffect(() => {
    if (!state.selectedCaseId) return;
    loadSession(state.selectedCaseId);
    loadDisclosures(state.selectedCaseId);
  }, [state.selectedCaseId, loadSession, loadDisclosures]);

  const actions = useMemo<WorkspaceActions>(
    () => ({ reloadAll, selectCase, loadSession, loadDisclosures, sendQuestion, retryMessage, discardMessage, restart, resetAndReload, refreshLive, refreshCases }),
    [reloadAll, selectCase, loadSession, loadDisclosures, sendQuestion, retryMessage, discardMessage, restart, resetAndReload, refreshLive, refreshCases],
  );

  const value = useMemo(() => ({ state, actions, api }), [state, actions, api]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace는 WorkspaceProvider 안에서만 쓸 수 있습니다.');
  return ctx;
}

/** 제공자 밖에서도 부를 수 있는 판 (명령 찾기처럼 두 역할 화면 모두에 뜨는 부품). 밖이면 null. */
export function useOptionalWorkspace(): WorkspaceContextValue | null {
  return useContext(WorkspaceContext);
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
