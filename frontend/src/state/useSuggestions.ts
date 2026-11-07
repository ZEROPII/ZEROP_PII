import { useEffect, useState } from 'react';
import type { CaseId, SuggestedQuestion } from '../types/domain';
import { useWorkspace } from './WorkspaceContext';

/** 이 사례에 지금 물어볼 수 있는 예시 질문 (백엔드가 지원할 때만). version이 바뀔 때마다(질문할 때마다) 다시 받는다. */
export function useSuggestions(caseId: CaseId | null, version: number): SuggestedQuestion[] {
  const { api } = useWorkspace();
  const [items, setItems] = useState<SuggestedQuestion[]>([]);
  useEffect(() => {
    if (!caseId || !api.listSuggestions) {
      setItems([]);
      return;
    }
    const ctl = new AbortController();
    api.listSuggestions(caseId, ctl.signal).then(setItems, () => setItems([]));
    return () => ctl.abort();
  }, [api, caseId, version]);
  return items;
}
