import { useEffect, useState } from 'react';
import type { CaseId, PreflightRiskAssessment } from '../types/domain';
import { useWorkspace } from './WorkspaceContext';

export interface PreflightState {
  status: 'idle' | 'checking' | 'done' | 'error';
  assessment: PreflightRiskAssessment | null;
}

const DEBOUNCE_MS = 450;
const MIN_LENGTH = 4;

/**
 * 입력 중인 질문을 백엔드 사전 평가 API에 보내 경고 여부를 받는다.
 * 프론트엔드는 위험을 계산하지 않고 결과만 표시한다. 전송 시 백엔드가 다시 검증한다.
 */
export function usePreflight(caseId: CaseId | null, sessionId: string | undefined, draft: string): PreflightState {
  const { api } = useWorkspace();
  const [state, setState] = useState<PreflightState>({ status: 'idle', assessment: null });
  const question = draft.trim();

  useEffect(() => {
    if (!caseId || !sessionId || question.length < MIN_LENGTH) {
      setState({ status: 'idle', assessment: null });
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState((prev) => ({ status: 'checking', assessment: prev.assessment }));
      api.assessPreflight(caseId, sessionId, question, controller.signal).then(
        (assessment) => setState({ status: 'done', assessment }),
        (error) => {
          if (error instanceof DOMException && error.name === 'AbortError') return;
          setState({ status: 'error', assessment: null });
        },
      );
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [api, caseId, sessionId, question]);

  return state;
}
