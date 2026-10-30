import { Loader2, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { usePreflight } from '../../state/usePreflight';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, SuggestedQuestion } from '../../types/domain';
import { LogoMark } from '../brand/Logo';
import { Card, CardHeader } from '../common/Card';
import { StatusIcon } from '../common/StatusChip';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { ChatInput } from './ChatInput';
import { ChatMessage } from './ChatMessage';
import { PreflightWarning } from './PreflightWarning';

/** 이 사례에 지금 물어볼 수 있는 예시 질문 (백엔드가 지원할 때만). 질문할 때마다 다시 받는다. */
function useSuggestions(caseId: CaseId | null, version: number): SuggestedQuestion[] {
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

export function ChatPanel() {
  const { actions } = useWorkspace();
  const { caseId, summary, session, risk } = useSelectedCase();
  // 사례별 입력 초안. 사례를 바꿔도 다른 사례의 초안과 섞이지 않는다.
  const [drafts, setDrafts] = useState<Record<CaseId, string>>({});
  const draft = caseId ? (drafts[caseId] ?? '') : '';
  const setDraft = (value: string) => {
    if (caseId) setDrafts((d) => ({ ...d, [caseId]: value }));
  };

  const data = session?.data;
  const sending = session?.sending ?? false;
  const preflight = usePreflight(caseId, data?.sessionId, draft);
  const scrollRef = useRef<HTMLDivElement>(null);
  const messageCount = data?.messages.length ?? 0;
  const suggestions = useSuggestions(caseId, messageCount);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [caseId, messageCount, sending]);

  async function submit(text?: string) {
    if (!caseId) return;
    const question = text ?? draft;
    if (!text) setDraft('');
    const ok = await actions.sendQuestion(caseId, question);
    // 실패하면 다시 쓰지 않아도 되게 입력을 되돌린다 (그 사이 새로 쓴 초안이 있으면 유지).
    if (!ok) setDrafts((d) => (d[caseId] ? d : { ...d, [caseId]: question }));
  }

  const assessment = preflight.assessment;
  const warning = assessment?.requiresWarning && assessment.caseId === caseId && assessment.question === draft.trim() ? assessment : null;

  const chips = suggestions.length > 0 && (
    <div className="flex flex-wrap justify-center gap-1.5">
      {suggestions.map((s) => (
        <button
          key={s.question}
          type="button"
          onClick={() => setDraft(s.question)}
          title={s.question}
          className="inline-flex h-8 max-w-full items-center gap-1.5 truncate rounded-full border border-line bg-surface px-3 text-[13px] text-ink-2 hover:border-line-input hover:text-ink"
        >
          <span className="font-semibold text-ink">{s.label}</span>
          <span className="truncate">{s.question === s.label ? '' : s.question}</span>
        </button>
      ))}
    </div>
  );

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader
        title={summary ? `${summary.label}에 대해 묻기` : '대화'}
        aside={data ? `질문 ${data.questionCount}회` : undefined}
      />

      {risk && !risk.disclosureAllowed && (
        <p className="flex items-center gap-2 border-b border-line bg-caution-tint px-4 py-2 text-xs text-caution-text">
          <StatusIcon tone="caution" className="h-3 w-3 shrink-0" />
          {summary?.label} 후보가 {risk.k}명이라 새 단서는 넓히거나 가려서 답합니다.
        </p>
      )}

      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto bg-page px-4 py-5 md:px-6" aria-live="polite" aria-busy={sending}>
        {!caseId ? (
          <EmptyState message="왼쪽 목록에서 사례를 고르세요." />
        ) : !session || session.status === 'loading' || session.status === 'idle' ? (
          <LoadingState label="대화 기록을 불러오는 중" />
        ) : session.status === 'error' ? (
          <ErrorState message={session.error ?? '대화를 불러오지 못했습니다.'} onRetry={() => actions.loadSession(caseId, true)} />
        ) : data && data.messages.length === 0 ? (
          <EmptyState message={`${summary?.label ?? '이 사례'}에 대해 아직 묻지 않았습니다. 처방, 경과, 시술처럼 진료에 필요한 내용을 물어보세요. 답에서 환자를 좁힐 수 있는 값은 자동으로 넓히거나 가립니다.`}>
            {chips && (
              <div className="mt-3 w-full">
                <p className="mb-2 inline-flex items-center gap-1 text-xs text-ink-3">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden /> 예시 질문 (눌러서 입력칸에 넣기)
                </p>
                {chips}
              </div>
            )}
          </EmptyState>
        ) : (
          data?.messages.map((m) => (
            <ChatMessage
              key={m.messageId}
              message={m}
              onRetry={(msg) => actions.retryMessage(caseId, msg)}
              onDiscard={(msg) => actions.discardMessage(caseId, msg.messageId)}
            />
          ))
        )}
        {sending && (
          <div className="flex items-center gap-3 text-[13px] text-ink-3" role="status">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-iris-tint" aria-hidden>
              <LogoMark size={20} />
            </span>
            <span className="inline-flex items-center gap-2 rounded-[18px] border border-line bg-surface px-3.5 py-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              답에 나온 단서로 후보 수를 세는 중
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line bg-surface px-4 pb-3 pt-3 md:px-6">
        {session?.sendError && (
          <p role="alert" className="mb-2 text-xs text-danger-text">
            {session.sendError}
          </p>
        )}
        {warning && <PreflightWarning assessment={warning} onSuggestion={setDraft} />}
        {data && data.messages.length > 0 && suggestions.length > 0 && !draft && (
          <div className="mb-2 flex gap-1.5 overflow-x-auto pb-0.5">
            {suggestions.slice(0, 4).map((s) => (
              <button
                key={s.question}
                type="button"
                onClick={() => setDraft(s.question)}
                title={s.question}
                className="h-7 shrink-0 rounded-full border border-line px-2.5 text-xs text-ink-2 hover:border-line-input hover:text-ink"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
        <ChatInput
          value={draft}
          onChange={setDraft}
          onSubmit={() => void submit()}
          disabled={!data}
          sending={sending}
          placeholder={summary ? `${summary.label}에 대해 질문하세요` : '사례를 고르세요'}
        />
        <p className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 text-[11px] text-ink-3">
          <span>
            <span className="kbd">Enter</span> 보내기 <span className="kbd ml-1">Shift</span>+<span className="kbd">Enter</span> 줄바꿈
          </span>
          <span aria-live="polite">
            {preflight.status === 'checking'
              ? '보내기 전 후보 수를 미리 세는 중'
              : preflight.status === 'error'
                ? '미리 세지 못했습니다. 보내면 서버가 판정합니다'
                : assessment?.supported === false
                  ? '이 서버는 미리 세기를 지원하지 않습니다. 보내면 판정합니다'
                  : assessment?.understood === false
                    ? '묻는 항목을 찾지 못했습니다. 나이, 진단, 약, 시기처럼 물어보세요'
                    : assessment && !assessment.requiresWarning && assessment.projectedK != null
                      ? `그대로 답하면 후보 ${assessment.projectedK.toLocaleString()}명입니다 (기준 통과)`
                      : '보내면 서버가 공개 정책으로 다시 판정합니다'}
          </span>
        </p>
      </div>
    </Card>
  );
}
