import { CornerDownLeft, Info, Loader2, Lock, MessageSquareReply, Ruler, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { preflightNotice, preflightStatusLine, restrictedNotice } from '../../lib/clinicianCopy';
import { useClinicMessages } from '../../state/ClinicMessages';
import { usePreflight } from '../../state/usePreflight';
import { useSuggestions } from '../../state/useSuggestions';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, SuggestedQuestion } from '../../types/domain';
import { LogoMark } from '../brand/Logo';
import { ChatInput } from '../chat/ChatInput';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { ClinicalMessage } from './ClinicalMessage';
import { LockedText } from './ClinicValue';

export interface JumpTarget {
  caseId: CaseId;
  messageId: string;
  nonce: number;
}

/** 진료에 바로 쓰는 질문(시술 · 관리 계획 · 처방 · 진단)을 앞에 둔다. 나머지 예시는 그 뒤에. */
const LABEL_ORDER = ['시술', '관리 계획', '처방 약', '약', '진단', '시점', '나이', '성별'];
function clinicalFirst(items: SuggestedQuestion[]): SuggestedQuestion[] {
  const rank = (l: string) => {
    const i = LABEL_ORDER.indexOf(l);
    return i < 0 ? LABEL_ORDER.length : i;
  };
  return [...items].sort((a, b) => rank(a.label) - rank(b.label));
}

const NOTICE_ICON = { lock: Lock, range: Ruler, info: Info } as const;

function SuggestionChips({ items, onPick, compact = false }: { items: SuggestedQuestion[]; onPick(q: string): void; compact?: boolean }) {
  return (
    <div className={compact ? 'flex gap-1.5 overflow-x-auto pb-0.5' : 'flex flex-wrap gap-1.5'}>
      {items.map((s) => (
        <button
          key={s.question}
          type="button"
          onClick={() => onPick(s.question)}
          title={s.question}
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface text-ink-2 hover:border-iris hover:text-ink ${
            compact ? 'h-7 px-2.5 text-xs' : 'h-8 max-w-full px-3 text-[13px]'
          }`}
        >
          <span className="font-semibold text-ink">{s.label}</span>
          {!compact && <span className="truncate">{s.question === s.label ? '' : s.question}</span>}
        </button>
      ))}
    </div>
  );
}

/** 의료진 화면 가운데: 고른 사례에 대해 묻고 답을 받는다. 보호 처리는 숫자 없이 '범위' · '비공개'로만 알린다. */
export function ClinicalChat({ jump, onJumpDone, onOpenMessages }: { jump: JumpTarget | null; onJumpDone(): void; onOpenMessages(): void }) {
  const { actions, state } = useWorkspace();
  const { caseId, summary, session, risk } = useSelectedCase();
  const msgs = useClinicMessages();
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
  const rawSuggestions = useSuggestions(caseId, messageCount);
  const suggestions = useMemo(() => clinicalFirst(rawSuggestions), [rawSuggestions]);
  const [flashId, setFlashId] = useState<string | null>(null);
  const label = summary?.label ?? '이 사례';
  const cases = state.cases.data ?? [];

  // 새 답이 오면 맨 아래로. 백링크로 특정 질문에 가는 중이면 그쪽이 먼저다.
  useEffect(() => {
    if (jump && jump.caseId === caseId) return;
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [caseId, messageCount, sending]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jump || jump.caseId !== caseId) return;
    const el = document.getElementById(`m-${jump.messageId}`);
    if (!el) return; // 대화를 아직 못 받았으면 받은 뒤 다시 시도한다 (messageCount가 바뀜)
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setFlashId(jump.messageId);
    onJumpDone();
  }, [jump, caseId, messageCount, onJumpDone]);

  useEffect(() => {
    if (!flashId) return;
    const t = window.setTimeout(() => setFlashId(null), 1700);
    return () => window.clearTimeout(t);
  }, [flashId]);

  async function submit(text?: string) {
    if (!caseId) return;
    const question = text ?? draft;
    if (!text) setDraft('');
    const ok = await actions.sendQuestion(caseId, question);
    if (!ok) setDrafts((d) => (d[caseId] ? d : { ...d, [caseId]: question }));
  }

  const assessment = preflight.assessment;
  const current = assessment && assessment.caseId === caseId && assessment.question === draft.trim() ? assessment : null;
  const notice = current ? preflightNotice(current, current.targetCaseLabel ?? label) : null;
  const NoticeIcon = notice ? NOTICE_ICON[notice.tone] : Info;
  const restricted = risk ? !risk.disclosureAllowed : false;
  const status = preflightStatusLine(preflight.status, current);

  return (
    <section aria-label="진료 지원 AI 대화" className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3 md:px-5">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-baseline gap-x-2.5 text-[17px] font-bold tracking-[-0.015em] text-ink">
            {summary ? summary.label : '사례를 고르세요'}
            {summary && <span className="truncate text-sm font-semibold text-ink-2">{summary.diagnosis}</span>}
          </h2>
          {summary && (
            <p className="truncate text-xs text-ink-3">
              <LockedText text={summary.description} />
            </p>
          )}
        </div>
        {data && <span className="num shrink-0 pt-1 text-xs text-ink-3">질문 {data.questionCount}회</span>}
      </header>

      {msgs.awaitingReply && (
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-iris-tint px-4 py-2 text-[13px] text-ink md:px-5">
          <MessageSquareReply className="h-4 w-4 shrink-0 text-iris-text" aria-hidden />
          <span className="min-w-0 flex-1">
            <strong className="font-semibold">개인정보 보호 담당자가 확인을 요청했습니다.</strong>{' '}
            <span className="text-ink-2">{msgs.awaitingReply.text}</span>
          </span>
          <button type="button" className="btn-primary btn-sm" onClick={onOpenMessages}>
            답장하기
          </button>
        </div>
      )}
      {restricted && summary && (
        <p className="flex items-start gap-2 border-b border-line bg-emr-lock-tint px-4 py-2 text-xs leading-5 text-emr-lock md:px-5">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {restrictedNotice(summary.label)}
        </p>
      )}

      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-4 overflow-y-auto bg-page px-4 py-4 md:px-5" aria-live="polite" aria-busy={sending}>
        {!caseId ? (
          <EmptyState message="왼쪽 목록에서 사례를 고르세요." />
        ) : !session || session.status === 'loading' || session.status === 'idle' ? (
          <LoadingState label="대화 기록을 불러오는 중" />
        ) : session.status === 'error' ? (
          <ErrorState message={session.error ?? '대화를 불러오지 못했습니다.'} onRetry={() => actions.loadSession(caseId, true)} />
        ) : data && data.messages.length === 0 ? (
          <EmptyState message={`${label}에 대해 아직 묻지 않았습니다. 처방, 시술, 관리 계획처럼 진료에 필요한 내용을 물어보세요. 개인을 알아볼 수 있는 세부 값은 범위로 보이거나 비공개로 표시됩니다.`}>
            {suggestions.length > 0 && (
              <div className="mt-3 w-full">
                <p className="mb-2 inline-flex items-center gap-1 text-xs text-ink-3">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden /> 예시 질문 (눌러서 입력칸에 넣기)
                </p>
                <div className="flex justify-center">
                  <SuggestionChips items={suggestions} onPick={setDraft} />
                </div>
              </div>
            )}
          </EmptyState>
        ) : (
          data?.messages.map((m) => (
            <ClinicalMessage
              key={m.messageId}
              message={m}
              caseLabel={label}
              cases={cases}
              flash={flashId === m.messageId}
              onRetry={(msg) => actions.retryMessage(caseId, msg)}
              onDiscard={(msg) => actions.discardMessage(caseId, msg.messageId)}
            />
          ))
        )}
        {sending && (
          <div className="flex items-center gap-2.5 text-[13px] text-ink-3" role="status">
            <LogoMark size={18} className="text-iris-text" />
            <span className="inline-flex items-center gap-2 rounded-control border border-line bg-surface px-3 py-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              사례 기록에서 답을 찾아 개인정보 보호 기준으로 확인하는 중
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line bg-surface px-4 pb-3 pt-3 md:px-5">
        {session?.sendError && (
          <p role="alert" className="mb-2 text-xs text-danger-text">
            {session.sendError}
          </p>
        )}
        {notice && (
          <div role="status" aria-live="polite" className="mb-2 rounded-control bg-emr-lock-tint px-3 py-2 text-[13px] text-ink-2">
            <p className="flex gap-2">
              <NoticeIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emr-lock" aria-hidden />
              <span>{notice.text}</span>
            </p>
            {current && current.suggestions.length > 0 && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-5">
                <span className="text-xs text-ink-3">대신 물어볼 수 있는 질문</span>
                {current.suggestions.map((s) => (
                  <button
                    key={s.question}
                    type="button"
                    onClick={() => setDraft(s.question)}
                    title={s.question}
                    className="inline-flex h-7 items-center gap-1 rounded-full border border-line bg-surface px-2.5 text-xs font-semibold text-ink-2 hover:border-iris hover:text-ink"
                  >
                    <CornerDownLeft className="h-3 w-3" aria-hidden />
                    {s.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {data && data.messages.length > 0 && suggestions.length > 0 && !draft && (
          <div className="mb-2">
            <SuggestionChips items={suggestions.slice(0, 5)} onPick={setDraft} compact />
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
          <span aria-live="polite">{draft.trim().length >= 4 ? status : '질문과 답은 개인정보 보호 담당자가 확인할 수 있습니다'}</span>
        </p>
      </div>
    </section>
  );
}
