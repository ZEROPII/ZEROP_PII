import { Bot, Loader2, MessageSquare, ShieldAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { usePreflight } from '../../state/usePreflight';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId } from '../../types/domain';
import { Card, CardHeader } from '../common/Card';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { ChatInput } from './ChatInput';
import { ChatMessage } from './ChatMessage';
import { PreflightWarning } from './PreflightWarning';

export function ChatPanel() {
  const { actions } = useWorkspace();
  const { caseId, summary, session, risk } = useSelectedCase();
  // 사례별 입력 초안. 사례를 바꿔도 다른 사례의 초안과 섞이지 않는다.
  const [drafts, setDrafts] = useState<Record<CaseId, string>>({});
  const draft = caseId ? drafts[caseId] ?? '' : '';
  const setDraft = (value: string) => {
    if (caseId) setDrafts((d) => ({ ...d, [caseId]: value }));
  };

  const data = session?.data;
  const sending = session?.sending ?? false;
  const preflight = usePreflight(caseId, data?.sessionId, draft);
  const scrollRef = useRef<HTMLDivElement>(null);
  const messageCount = data?.messages.length ?? 0;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [caseId, messageCount, sending]);

  async function submit() {
    if (!caseId) return;
    const question = draft;
    setDraft('');
    const ok = await actions.sendQuestion(caseId, question);
    // 실패하면 사용자가 입력을 다시 쓰지 않아도 되게 되돌린다 (그 사이 새로 쓴 초안이 있으면 유지).
    if (!ok) setDrafts((d) => (d[caseId] ? d : { ...d, [caseId]: question }));
  }

  const assessment = preflight.assessment;
  const warning =
    assessment?.requiresWarning && assessment.caseId === caseId && assessment.question === draft.trim() ? assessment : null;

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <MessageSquare className="h-4 w-4 text-blue-600" aria-hidden />
            대화
          </span>
        }
        aside={summary && data ? `${summary.label} 중심 · 질문 ${data.questionCount}회` : undefined}
      />

      {risk && !risk.disclosureAllowed && (
        <p className="flex items-center gap-1.5 border-b border-red-100 bg-red-50 px-4 py-1.5 text-[11px] text-red-700">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {summary?.label}: {risk.statusLabel} (k {risk.k}). 새 준식별자는 답변에서 일반화되거나 제외됩니다.
        </p>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50/60 px-4 py-4" aria-live="polite" aria-busy={sending}>
        {!caseId ? (
          <EmptyState message="왼쪽 목록에서 사례를 선택하세요." />
        ) : !session || session.status === 'loading' || session.status === 'idle' ? (
          <LoadingState label="대화 기록을 불러오는 중…" />
        ) : session.status === 'error' ? (
          <ErrorState message={session.error ?? '대화를 불러오지 못했습니다.'} onRetry={() => actions.loadSession(caseId, true)} />
        ) : data && data.messages.length === 0 ? (
          <EmptyState message={`${summary?.label ?? '이 사례'}에 대해 아직 질문하지 않았습니다. 처방·경과 등 필요한 내용을 물어보세요.`} />
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
          <div className="flex items-center gap-2.5 text-xs text-slate-500" role="status">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-navy-900 text-white" aria-hidden>
              <Bot className="h-4 w-4" />
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-2xl border border-slate-200 bg-white px-3 py-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              보호 정책을 검증하며 답변을 만드는 중…
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-100 bg-white px-4 pb-3 pt-2.5">
        {session?.sendError && (
          <p role="alert" className="mb-2 text-[11px] text-red-600">
            {session.sendError}
          </p>
        )}
        {warning && <PreflightWarning assessment={warning} onSuggestion={setDraft} />}
        <ChatInput
          value={draft}
          onChange={setDraft}
          onSubmit={submit}
          disabled={!data}
          sending={sending}
          placeholder={summary ? `${summary.label}에 대해 질문하세요` : '사례를 선택하세요'}
        />
        <p className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 text-[10px] text-slate-400">
          <span>Enter 보내기 · Shift+Enter 줄바꿈</span>
          <span aria-live="polite">
            {preflight.status === 'checking'
              ? '재식별 위험 사전 평가 중…'
              : preflight.status === 'error'
                ? '사전 평가를 받지 못했습니다 (전송 시 서버가 검증합니다)'
                : '전송 시 서버가 공개 정책을 다시 검증합니다'}
          </span>
        </p>
      </div>
    </Card>
  );
}
