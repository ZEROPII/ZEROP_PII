import { CornerDownLeft, Info, Layers, Loader2, Lock, MessageSquareReply, Ruler, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { emrApi } from '../../api/emrApi';
import { overviewOf, splitItem } from '../../lib/caseOverview';
import { preflightNotice, preflightStatusLine, restrictedNotice } from '../../lib/clinicianCopy';
import { josa, josaRo } from '../../lib/korean';
import { caseNoOf, scopeHint } from '../../lib/scopeHint';
import { useClinicMessages } from '../../state/ClinicMessages';
import { usePreflight } from '../../state/usePreflight';
import { useSuggestions } from '../../state/useSuggestions';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, CaseSummary, LaunchProgress, QuestionScope, SuggestedQuestion } from '../../types/domain';
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

function SuggestionChips({ items, onPick, compact = false }: { items: SuggestedQuestion[]; onPick(s: SuggestedQuestion): void; compact?: boolean }) {
  return (
    <div className={compact ? 'flex gap-1.5 overflow-x-auto pb-0.5' : 'flex flex-wrap justify-center gap-1.5'}>
      {items.map((s) => (
        <button
          key={s.question}
          type="button"
          onClick={() => onPick(s)}
          title={s.scope === 'all' ? `찾은 사례 전체에 묻기: ${s.question}` : s.question}
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border bg-surface text-ink-2 hover:border-iris hover:text-ink ${
            s.scope === 'all' ? 'border-dashed border-iris' : 'border-line'
          } ${compact ? 'h-7 px-2.5 text-xs' : 'h-8 max-w-full px-3 text-[13px]'}`}
        >
          <span className="font-semibold text-ink">{s.label}</span>
          {s.scope === 'all' && <span className="text-[10.5px] font-semibold text-iris-text">전체</span>}
          {!compact && <span className="truncate">{s.question === s.label ? '' : s.question}</span>}
        </button>
      ))}
    </div>
  );
}

/** 찾은 사례 한눈에: 사례 목록에 보이는 진단 · 대표 항목을 센다 (새 값을 드러내지 않는다). */
function FoundCases({ cases }: { cases: CaseSummary[] }) {
  const o = useMemo(() => overviewOf(cases), [cases]);
  if (o.total === 0) return null;
  const line = (xs: { value: string; n: number }[], short = false) =>
    xs
      .slice(0, 3)
      .map((x) => `${short ? splitItem(x.value)[1] : x.value} ${x.n}건`)
      .join(', ');
  const itemName = o.items[0] ? splitItem(o.items[0].value)[0] || '대표 항목' : '대표 항목';
  return (
    <div className="mx-auto mb-4 w-full max-w-[560px] rounded-control border border-line bg-surface px-4 py-3 text-left text-[13px] leading-6 text-ink-2">
      <p className="font-semibold text-ink">비슷한 사례 {o.total}건을 찾았습니다</p>
      {o.diagnoses.length > 0 && (
        <p>
          <span className="text-ink-3">진단</span> {line(o.diagnoses)}
        </p>
      )}
      {o.items.length > 0 && (
        <p>
          <span className="text-ink-3">{itemName}</span> {line(o.items, true)}
        </p>
      )}
      <p className="mt-1 text-xs text-ink-3">사례 하나는 과거 환자 한 명입니다. 공통점이나 차이는 '찾은 사례 전체'로 물어보세요.</p>
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
  const live = state.policy.data?.live === true;
  // 묻는 범위: 고른 사례(case) · 찾은 사례 전체(all, 실제 LLM 대화). 보내기 전 미리 세기는 고른 사례 질문에만 한다.
  const [scope, setScope] = useState<QuestionScope>('case');
  const preflight = usePreflight(caseId, data?.sessionId, scope === 'all' ? '' : draft);
  const [progress, setProgress] = useState<LaunchProgress | null>(null);
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

  // 답을 기다리는 동안 서버가 알려 주는 지금 단계 (실제 LLM 호출이 차례로 이어진다)
  useEffect(() => {
    if (!sending || !live) {
      setProgress(null);
      return;
    }
    let stop = false;
    let timer = 0;
    const tick = () => {
      emrApi.questionProgress().then(
        (p) => !stop && setProgress(p),
        () => undefined,
      );
      if (!stop) timer = window.setTimeout(tick, 700);
    };
    timer = window.setTimeout(tick, 200);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [sending, live]);

  function pick(s: SuggestedQuestion) {
    setDraft(s.question);
    if (live) setScope(s.scope ?? 'case');
  }

  // 질문 문장과 묻는 범위가 어긋나면 알린다. 사례 하나 범위에서 여러 사례 · 다른 사례를 물으면 Enter 한 번은 보내지 않고 안내를 강조한다.
  const hint = live && summary ? scopeHint(draft, scope, caseNoOf(summary.label), cases.length) : null;
  const [held, setHeld] = useState<string | null>(null);
  const holding = hint?.hold === true && held === draft.trim();
  const caseIdOf = (n: number) => cases.find((c) => caseNoOf(c.label) === n)?.caseId;

  /** 입력한 질문을 다른 사례의 대화로 옮긴다 (그 사례 하나에 묻기) */
  function moveDraft(n: number) {
    const target = caseIdOf(n);
    if (!caseId || !target) return;
    const text = draft;
    setDrafts((d) => ({ ...d, [caseId]: '', [target]: text }));
    setScope('case');
    actions.selectCase(target);
  }

  async function submit(text?: string, scopeOverride?: QuestionScope) {
    if (!caseId) return;
    if (!text && !scopeOverride && hint?.hold && held !== draft.trim()) {
      setHeld(draft.trim());
      return;
    }
    const question = text ?? draft;
    const sc = scopeOverride ?? scope;
    if (scopeOverride) setScope(scopeOverride);
    if (!text) setDraft('');
    setHeld(null);
    const ok = await actions.sendQuestion(caseId, question, live ? sc : 'case');
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
          <div className="flex flex-col items-center px-2 py-6 text-center">
            {live && <FoundCases cases={cases} />}
            <p className="max-w-[520px] text-[13px] leading-6 text-ink-2">
              {label}에 대해 아직 묻지 않았습니다. 처방, 시술, 관리 계획처럼 진료에 필요한 내용을 물어보세요. 개인을 알아볼 수 있는 세부 값은 범위로
              보이거나 비공개로 표시됩니다.
            </p>
            {suggestions.length > 0 && (
              <div className="mt-4 w-full">
                <p className="mb-2 inline-flex items-center gap-1 text-xs text-ink-3">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden /> {live ? '조회 목적에 맞는 질문 (눌러서 입력칸에 넣기)' : '예시 질문 (눌러서 입력칸에 넣기)'}
                </p>
                <SuggestionChips items={suggestions} onPick={pick} />
              </div>
            )}
          </div>
        ) : (
          data?.messages.map((m, i) => (
            <ClinicalMessage
              key={m.messageId}
              message={m}
              caseLabel={label}
              cases={cases}
              flash={flashId === m.messageId}
              onRetry={(msg) => actions.retryMessage(caseId, msg)}
              onDiscard={(msg) => actions.discardMessage(caseId, msg.messageId)}
              until={data.messages.slice(i + 1).find((x) => x.role === 'user')?.createdAt}
            />
          ))
        )}
        {sending && (
          <div className="flex items-center gap-2.5 text-[13px] text-ink-3" role="status">
            <LogoMark size={18} className="text-iris-text" />
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-control border border-line bg-surface px-3 py-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              {progress?.active ? progress.label : '사례 기록에서 답을 찾아 개인정보 보호 기준으로 확인하는 중'}
              {progress?.active && <span className="num text-[11px] text-ink-3">{Math.round(progress.elapsed ?? 0)}초</span>}
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
        {/* 범위부터 정해야 하는 질문이면 보내기 전 확인(고른 사례 기준)은 범위를 고른 뒤에 의미가 있으므로 잠시 숨긴다 */}
        {notice && !hint?.hold && (
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
        {hint && summary && (
          <div
            role="status"
            aria-live="polite"
            className={`mb-2 rounded-control px-3 py-2 text-[13px] text-ink-2 ${holding ? 'bg-iris-tint ring-1 ring-iris' : 'bg-surface-2'}`}
          >
            <p className="flex gap-2">
              <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-iris-text" aria-hidden />
              <span>
                {hint.kind === 'toAll'
                  ? `여러 사례를 묻는 질문 같습니다. 지금 묻는 범위는 ${josa(summary.label, '이라', '라')} ${summary.label}만 답합니다.`
                  : hint.kind === 'otherCase'
                    ? `질문에 ${josa(`사례 ${hint.caseNo}`, '이', '가')} 있지만 지금 묻는 범위는 ${summary.label}입니다.`
                    : `사례 ${hint.caseNo} 하나만 묻는 질문입니다. 사례 ${hint.caseNo} 대화에서 물으면 그 사례 기록에 함께 남습니다.`}
                {holding && <strong className="ml-1 font-semibold text-ink">범위를 골라 보내세요. Enter를 한 번 더 누르면 지금 범위로 보냅니다.</strong>}
              </span>
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-5">
              {hint.kind === 'toAll' && (
                <>
                  <button type="button" className="btn-primary btn-sm h-7" disabled={sending || !data} onClick={() => void submit(undefined, 'all')}>
                    찾은 사례 전체로 보내기
                  </button>
                  <button type="button" className="btn-ghost btn-sm h-7 text-ink-2" disabled={sending || !data} onClick={() => void submit(undefined, 'case')}>
                    {summary.label}만 묻기
                  </button>
                </>
              )}
              {hint.kind === 'otherCase' && (
                <>
                  <button type="button" className="btn-primary btn-sm h-7" disabled={!caseIdOf(hint.caseNo)} onClick={() => moveDraft(hint.caseNo)}>
                    {josaRo(`사례 ${hint.caseNo}`)} 옮겨 묻기
                  </button>
                  <button type="button" className="btn-ghost btn-sm h-7 text-ink-2" disabled={sending || !data} onClick={() => void submit(undefined, 'case')}>
                    {josaRo(summary.label)} 보내기
                  </button>
                </>
              )}
              {hint.kind === 'oneCase' && (
                <button type="button" className="btn-ghost btn-sm h-7 text-ink-2" disabled={!caseIdOf(hint.caseNo)} onClick={() => moveDraft(hint.caseNo)}>
                  사례 {hint.caseNo} 대화에서 묻기
                </button>
              )}
            </div>
          </div>
        )}
        {data && data.messages.length > 0 && suggestions.length > 0 && !draft && (
          <div className="mb-2">
            <SuggestionChips items={suggestions.slice(0, 5)} onPick={pick} compact />
          </div>
        )}
        {live && summary && (
          <div role="radiogroup" aria-label="묻는 범위" className="mb-2 flex items-center gap-2 text-xs">
            <span className="text-ink-3">묻는 범위</span>
            <span className="flex rounded-[9px] bg-surface-2 p-0.5">
              {(
                [
                  ['case', summary.label],
                  ['all', `찾은 사례 전체 (${cases.length}건)`],
                ] as [QuestionScope, string][]
              ).map(([k, l]) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={scope === k}
                  onClick={() => setScope(k)}
                  className={`h-6 rounded-[7px] px-2.5 font-semibold ${scope === k ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink'}`}
                >
                  {l}
                </button>
              ))}
            </span>
          </div>
        )}
        <ChatInput
          value={draft}
          onChange={setDraft}
          onSubmit={() => void submit()}
          disabled={!data}
          sending={sending}
          placeholder={
            !summary ? '사례를 고르세요' : scope === 'all' && live ? '찾은 사례 전체에 대해 질문하세요 (공통점 · 차이 비교)' : `${summary.label}에 대해 질문하세요`
          }
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
