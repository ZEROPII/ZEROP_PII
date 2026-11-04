import {
  CalendarDays,
  CircleDot,
  ClipboardList,
  CornerDownRight,
  Hourglass,
  Loader2,
  Lock,
  MapPin,
  Pill,
  Send,
  ShieldCheck,
  Stethoscope,
  Syringe,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { buildCaseNote, type NoteValue } from '../../lib/caseNote';
import { requestDraft } from '../../lib/clinicianCopy';
import { formatTime } from '../../lib/format';
import { useClinicMessages } from '../../state/ClinicMessages';
import { useTermDetect, useTerms } from '../../state/TermContext';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, ConversationSession, DisclosureHistoryEntry } from '../../types/domain';
import { EmptyState, LoadingState } from '../common/StatusViews';

export type NoteTab = 'note' | 'messages';

const ATTR_ICON: Record<string, LucideIcon> = {
  DX: Stethoscope,
  COMORBID: Stethoscope,
  PROC: Syringe,
  MED: Pill,
  PLAN: ClipboardList,
  PERIOD: CalendarDays,
  DATE: CalendarDays,
  AGE: Hourglass,
  SEX: UserRound,
  REGION: MapPin,
  LOC: MapPin,
  STATE: MapPin,
};
/** 의료 용어 사전에서 찾아볼 수 있는 항목 (값이 [[링크]]가 된다) */
const TERM_ATTRS = new Set(['DX', 'MED', 'PROC', 'PLAN', 'COMORBID']);

function SectionTitle({ children, count }: { children: string; count?: number }) {
  return (
    <h3 className="mb-1.5 mt-5 flex items-baseline gap-1.5 text-[13px] font-bold text-ink first:mt-0">
      {children}
      {count != null && <span className="num text-xs font-medium text-ink-3">{count}</span>}
    </h3>
  );
}

function ValueText({ v, nodeId }: { v: NoteValue; nodeId: string | undefined }) {
  const { openTerm } = useTerms();
  if (v.action === 'suppress')
    return (
      <span className="lock-token" title="개인을 알아볼 수 있는 값이라 비공개로 처리했습니다">
        <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
        비공개
      </span>
    );
  const text = v.text ?? '';
  const body = nodeId ? (
    <button type="button" className="wikilink" onClick={() => openTerm(nodeId)} title="의료 용어 설명 보기">
      {text}
    </button>
  ) : (
    <span>{text}</span>
  );
  if (v.action === 'generalize')
    return (
      <span>
        <span className="range-value">{body}</span>
        <span className="range-tag">범위</span>
      </span>
    );
  return body;
}

/** 사례 노트: 속성 · 연결된 질문(백링크) · 같은 값이 나온 사례(링크된 언급) */
function NoteView({ onJump }: { onJump(caseId: CaseId, messageId: string): void }) {
  const { state, actions } = useWorkspace();
  const { caseId, summary, disclosures, session } = useSelectedCase();
  const cases = useMemo(() => state.cases.data ?? [], [state.cases.data]);

  // 같은 값 찾기에 다른 사례의 공개 이력도 쓴다 (아직 안 받았거나 다시 받아야 하면 받는다)
  useEffect(() => {
    for (const c of cases) {
      const slot = state.disclosures[c.caseId];
      if (!slot || slot.status === 'idle') actions.loadDisclosures(c.caseId);
    }
  }, [cases, state.disclosures, actions]);

  const allEntries = useMemo(
    () => Object.fromEntries(Object.entries(state.disclosures).map(([k, v]) => [k, v.data])) as Record<CaseId, DisclosureHistoryEntry[] | undefined>,
    [state.disclosures],
  );
  const sessions = useMemo(
    () => Object.fromEntries(Object.entries(state.sessions).map(([k, v]) => [k, v.data])) as Record<CaseId, ConversationSession | undefined>,
    [state.sessions],
  );
  const note = useMemo(
    () => (caseId && disclosures?.data ? buildCaseNote({ caseId, entries: disclosures.data, allEntries, sessions, cases }) : null),
    [caseId, disclosures?.data, allEntries, sessions, cases],
  );

  // 진단 · 약 · 시술 값은 용어 사전에서 찾아 [[링크]]로 만든다
  const termValues = useMemo(
    () => (note ? note.properties.flatMap((p) => (TERM_ATTRS.has(p.attribute) ? p.values.map((v) => v.text ?? '') : [])) : []),
    [note],
  );
  const { mentions } = useTermDetect(termValues);

  if (!caseId || !summary) return <EmptyState message="사례를 고르면 지금까지 나온 내용이 노트로 정리됩니다." />;
  if (disclosures?.status === 'error') return <EmptyState message="노트를 만들 내용을 불러오지 못했습니다." />;
  if (!note) return <LoadingState compact label="노트를 정리하는 중" />;

  let ti = 0;
  const asked = session?.data?.questionCount ?? 0;
  return (
    <div className="px-4 pb-5 pt-4">
      <h2 className="text-xl font-bold tracking-[-0.02em] text-ink">{summary.label}</h2>
      <p className="mt-0.5 text-xs text-ink-3">
        비슷한 사례 {summary.similarityRank}위로 찾은 과거 기록{asked ? `, 이 사례에 질문 ${asked}회` : ''}
      </p>

      <SectionTitle>속성</SectionTitle>
      {note.properties.length === 0 ? (
        <p className="text-[13px] text-ink-3">아직 답에 나온 내용이 없습니다.</p>
      ) : (
        <dl className="rounded-control border border-line bg-surface">
          {note.properties.map((p) => {
            const Icon = ATTR_ICON[p.attribute] ?? CircleDot;
            const linkable = TERM_ATTRS.has(p.attribute);
            return (
              <div key={p.attribute} className="grid grid-cols-[18px_72px_minmax(0,1fr)] items-start gap-x-2 border-b border-line px-3 py-2 last:border-b-0">
                <Icon className="mt-[3px] h-3.5 w-3.5 text-ink-3" aria-hidden />
                <dt className="text-[13px] text-ink-3">{p.label}</dt>
                <dd className="min-w-0 space-y-1 break-words text-[13px] font-medium text-ink">
                  {p.values.map((v) => {
                    const m = linkable ? mentions[ti++] : undefined;
                    return (
                      <div key={`${v.action}:${v.text}`}>
                        <ValueText v={v} nodeId={m?.[0]?.node_id} />
                      </div>
                    );
                  })}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      <SectionTitle count={note.backlinks.length}>연결된 질문</SectionTitle>
      <ul className="space-y-0.5">
        {note.backlinks.map((b) => {
          const elsewhere = b.askedIn && b.askedIn !== caseId;
          const content = (
            <>
              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-iris-text">
                <CornerDownRight className="h-3 w-3" aria-hidden />
                {b.turn === 0 ? '사례 검색' : b.questionNo != null ? `질문 ${b.questionNo}` : '질문'}
                {elsewhere && <span className="font-normal text-ink-3">{b.askedInLabel} 대화에서</span>}
              </span>
              <span className="mt-0.5 line-clamp-2 block text-[13px] leading-5 text-ink">{b.question}</span>
              <span className="mt-1 flex flex-wrap gap-1">
                {b.facts.map((f, i) => (
                  <span key={i} className="inline-flex max-w-full items-center gap-1 truncate rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] text-ink-2">
                    {f.label}
                    {f.action === 'suppress' ? <Lock className="h-2.5 w-2.5 text-emr-lock" aria-label="비공개" /> : <span className="truncate text-ink">{f.text}</span>}
                    {f.action === 'generalize' && <span className="text-iris-text">범위</span>}
                  </span>
                ))}
              </span>
            </>
          );
          return (
            <li key={b.turn}>
              {b.messageId && b.askedIn ? (
                <button
                  type="button"
                  onClick={() => onJump(b.askedIn!, b.messageId!)}
                  className="block w-full rounded-control px-2 py-1.5 text-left hover:bg-surface-2"
                  title="대화에서 이 질문으로 가기"
                >
                  {content}
                </button>
              ) : (
                <div className="px-2 py-1.5">{content}</div>
              )}
            </li>
          );
        })}
      </ul>

      {note.linked.length > 0 && (
        <>
          <SectionTitle>같은 값이 나온 사례</SectionTitle>
          <ul className="space-y-1.5 text-[13px]">
            {note.linked.map((l) => (
              <li key={`${l.label}:${l.value}`} className="leading-6">
                <span className="text-ink-3">{l.label}</span> <span className="font-medium text-ink">{l.value}</span>
                <span className="ml-1 inline-flex flex-wrap gap-x-1.5">
                  {l.cases.map((c) => (
                    <button key={c.caseId} type="button" className="wikilink text-[13px]" onClick={() => actions.selectCase(c.caseId)}>
                      {c.label}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] leading-4 text-ink-3">여러 사례에 같이 나온 값은 비슷한 환자 무리에 공통인 특징입니다.</p>
        </>
      )}
    </div>
  );
}

/** 개인정보 보호 담당자와 주고받은 메시지 (세부 정보 요청 · 확인 요청 · 답장) */
function MessagesView({ focusNonce }: { focusNonce: number }) {
  const msgs = useClinicMessages();
  const { caseId, summary } = useSelectedCase();
  const hasSecurity = msgs.messages.some((m) => m.sender === 'security');
  const [mode, setMode] = useState<'reply' | 'access_request'>(msgs.awaitingReply ? 'reply' : 'access_request');
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  /** 화면이 자동으로 채운 마지막 초안. 의료진이 고치지 않았으면 사례를 바꿀 때 새 사례 초안으로 바꾼다. */
  const autoDraft = useRef('');
  const { markRead } = msgs;

  useEffect(() => {
    markRead();
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
    // 새 메시지가 올 때마다 읽음으로 표시한다 (이 탭이 열려 있는 동안)
  }, [msgs.messages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (msgs.awaitingReply) setMode('reply');
  }, [msgs.awaitingReply]);

  useEffect(() => {
    if (focusNonce) inputRef.current?.focus();
  }, [focusNonce]);

  useEffect(() => {
    if (mode !== 'access_request' || !summary) return;
    const next = requestDraft(summary.label, []);
    setText((t) => {
      if (t !== '' && t !== autoDraft.current) return t; // 의료진이 고친 초안은 그대로 둔다
      autoDraft.current = next;
      return next;
    });
  }, [mode, summary?.label]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send() {
    const body = text.trim();
    if (body.length < 2) return;
    const ok = await msgs.send({ kind: mode, text: body, caseId: mode === 'access_request' ? caseId : (msgs.awaitingReply?.caseId ?? null) });
    if (ok) {
      autoDraft.current = '';
      setText('');
    }
  }

  if (msgs.supported === false) return <EmptyState message="이 서버는 개인정보 보호 담당자 메시지를 지원하지 않습니다." />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="px-4 pb-2 pt-3 text-xs leading-5 text-ink-3">
        세부 정보 요청과 개인정보 보호 담당자의 답장이 여기에 모입니다. 주고받은 내용은 감사 기록에 남습니다.
      </p>
      <ol ref={listRef} className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-3">
        {msgs.messages.length === 0 && <li className="py-6 text-center text-[13px] text-ink-3">아직 주고받은 메시지가 없습니다.</li>}
        {msgs.messages.map((m) => {
          const mine = m.sender === 'clinician';
          return (
            <li key={m.messageId} className={mine ? 'ml-6' : 'mr-6'}>
              <p className={`flex flex-wrap items-center gap-x-1.5 text-[11px] text-ink-3 ${mine ? 'justify-end' : ''}`}>
                {!mine && <ShieldCheck className="h-3 w-3 text-iris-text" aria-hidden />}
                <span className="font-semibold text-ink-2">{mine ? '나' : '개인정보 보호 담당자'}</span>
                <span>{m.kindLabel}</span>
                {m.caseLabel && <span>{m.caseLabel}</span>}
                <time dateTime={m.createdAt} className="num">
                  {formatTime(m.createdAt)}
                </time>
              </p>
              <p
                className={`mt-1 whitespace-pre-wrap break-words rounded-control px-3 py-2 text-[13px] leading-5 text-ink ${
                  mine ? 'bg-iris-tint' : m.kind === 'check_request' ? 'border border-iris bg-surface' : 'bg-surface-2'
                }`}
              >
                {m.text}
              </p>
            </li>
          );
        })}
      </ol>
      <form
        className="shrink-0 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {hasSecurity && (
          <div role="group" aria-label="보낼 메시지 종류" className="mb-2 flex gap-1 rounded-control bg-surface-2 p-0.5 text-xs font-semibold">
            {(
              [
                ['reply', '답장'],
                ['access_request', '새 세부 정보 요청'],
              ] as const
            ).map(([k, l]) => (
              <button
                key={k}
                type="button"
                aria-pressed={mode === k}
                onClick={() => {
                  setMode(k);
                  const next = k === 'access_request' && summary ? requestDraft(summary.label, []) : '';
                  autoDraft.current = next;
                  setText(next);
                }}
                className={`h-7 flex-1 rounded-[8px] ${mode === k ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink'}`}
              >
                {l}
              </button>
            ))}
          </div>
        )}
        <label htmlFor="clinic-msg" className="sr-only">
          {mode === 'reply' ? '답장' : '세부 정보 요청'}
        </label>
        <textarea
          id="clinic-msg"
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={500}
          placeholder={mode === 'reply' ? '확인 요청에 답장을 쓰세요' : '필요한 세부 정보와 사유를 쓰세요'}
          className="w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-[13px] leading-5 text-ink outline-none placeholder:text-ink-3 focus:border-focus"
        />
        {msgs.error && <p className="mt-1 text-xs text-danger-text">{msgs.error}</p>}
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[11px] text-ink-3">{mode === 'access_request' && summary ? `${summary.label}에 대한 요청으로 보냅니다` : ''}</span>
          <button type="submit" className="btn-primary btn-sm" disabled={msgs.sending || text.trim().length < 2}>
            {msgs.sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
            {mode === 'reply' ? '답장 보내기' : '요청 보내기'}
          </button>
        </div>
      </form>
    </div>
  );
}

/** 의료진 화면 오른쪽: 사례 노트와 보호 담당자 메시지 */
export function CaseNotePanel({
  tab,
  onTab,
  onJump,
  focusNonce,
}: {
  tab: NoteTab;
  onTab(t: NoteTab): void;
  onJump(caseId: CaseId, messageId: string): void;
  focusNonce: number;
}) {
  const msgs = useClinicMessages();
  const tabs: { id: NoteTab; label: string; badge?: number }[] = [
    { id: 'note', label: '사례 노트' },
    ...(msgs.supported ? [{ id: 'messages' as const, label: '보호 담당자 메시지', badge: msgs.unread }] : []),
  ];
  return (
    <section aria-label="사례 노트와 메시지" className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <div role="tablist" aria-label="오른쪽 영역" className="flex shrink-0 gap-1 border-b border-line px-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => onTab(t.id)}
            className={`relative -mb-px inline-flex h-11 items-center gap-1.5 border-b-2 px-2.5 text-[13px] font-semibold ${
              tab === t.id ? 'border-iris text-ink' : 'border-transparent text-ink-3 hover:text-ink'
            }`}
          >
            {t.label}
            {!!t.badge && <span className="num grid h-[18px] min-w-[18px] place-items-center rounded-full bg-iris px-1 text-[10px] font-bold text-iris-on">{t.badge}</span>}
          </button>
        ))}
      </div>
      <div className={`min-h-0 flex-1 ${tab === 'note' ? 'scroll-thin overflow-y-auto' : 'flex flex-col'}`}>
        {tab === 'note' ? <NoteView onJump={onJump} /> : <MessagesView focusNonce={focusNonce} />}
      </div>
    </section>
  );
}
