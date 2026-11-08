import { Loader2, MailQuestion, MessageSquareReply, Send, ShieldCheck, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { requestDraft } from '../../lib/clinicianCopy';
import { formatTime } from '../../lib/format';
import { REQUEST_STATE_KO, statusOf } from '../../lib/requests';
import { useClinicMessages } from '../../state/ClinicMessages';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId } from '../../types/domain';

/** 내 세부 정보 요청 아래 처리 상태 한 줄 */
function RequestLine({ status }: { status: ReturnType<typeof statusOf> }) {
  const tone = status.state === 'released' ? 'text-safe-text' : status.state === 'answered' || status.state === 'partial' ? 'text-iris-text' : 'text-ink-3';
  return (
    <p className={`mt-1 text-right text-[11px] font-semibold ${tone}`}>
      {REQUEST_STATE_KO[status.state]}
      {status.doneAt ? <span className="num font-normal text-ink-3"> · {formatTime(status.doneAt)}</span> : <span className="font-normal text-ink-3"> · 보호 담당자가 확인하면 여기에 답이 옵니다</span>}
    </p>
  );
}

/** 주고받은 메시지와 보내기 칸. 창이 열려 있는 동안 새 메시지를 읽음으로 표시한다. */
function DeskThread({ focusNonce }: { focusNonce: number }) {
  const msgs = useClinicMessages();
  const { state } = useWorkspace();
  const { caseId } = useSelectedCase();
  const cases = state.cases.data ?? [];
  /** 새 세부 정보 요청의 사례: 창을 연 곳이 가리킨 사례(알림 · 요청 상태), 없으면 고른 사례. 의료진이 바꿀 수 있다 */
  const [reqCase, setReqCase] = useState<CaseId | null>(msgs.openCase ?? caseId);
  const picked = useRef(false);
  const summary = cases.find((c) => c.caseId === reqCase) ?? null;
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
  }, [msgs.messages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (msgs.awaitingReply) setMode('reply');
  }, [msgs.awaitingReply]);

  useEffect(() => {
    inputRef.current?.focus();
    // 다시 열 때마다 연 곳이 가리킨 사례로 (없으면 고른 사례)
    picked.current = false;
    setReqCase(msgs.openCase ?? caseId);
  }, [focusNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  // 창을 열어 둔 채 다른 사례를 고르면 따라간다 (의료진이 요청 사례를 직접 고른 뒤에는 그대로)
  const lastSelected = useRef(caseId);
  useEffect(() => {
    if (lastSelected.current === caseId) return; // 처음 그릴 때는 연 곳이 가리킨 사례를 둔다
    lastSelected.current = caseId;
    if (!picked.current && caseId) setReqCase(caseId);
  }, [caseId]);

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
    const ok = await msgs.send({ kind: mode, text: body, caseId: mode === 'access_request' ? reqCase : (msgs.awaitingReply?.caseId ?? null) });
    if (ok) {
      autoDraft.current = '';
      setText('');
    }
  }

  return (
    <>
      <ol ref={listRef} className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto bg-page px-4 py-3">
        {msgs.messages.length === 0 && (
          <li className="space-y-2.5 rounded-control border border-line bg-surface px-3 py-3 text-[13px] leading-5 text-ink-2">
            <p className="font-semibold text-ink">이럴 때 씁니다</p>
            <p className="flex gap-2">
              <MailQuestion className="mt-0.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
              <span>답에서 비공개로 보인 값이 진료에 꼭 필요할 때, 사유를 적어 세부 정보를 요청합니다.</span>
            </p>
            <p className="flex gap-2">
              <MessageSquareReply className="mt-0.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
              <span>보호 담당자가 질문한 목적을 물으면(확인 요청) 이 창으로 오고, 여기서 답장합니다.</span>
            </p>
          </li>
        )}
        {msgs.messages.map((m) => {
          const mine = m.sender === 'clinician';
          return (
            <li key={m.messageId} className={mine ? 'ml-8' : 'mr-8'}>
              <p className={`flex flex-wrap items-center gap-x-1.5 text-[11px] text-ink-3 ${mine ? 'justify-end' : ''}`}>
                <span className="font-semibold text-ink-2">{mine ? '나' : '보호 담당자'}</span>
                <span>{m.kindLabel}</span>
                {m.caseLabel && <span>{m.caseLabel}</span>}
                <time dateTime={m.createdAt} className="num">
                  {formatTime(m.createdAt)}
                </time>
              </p>
              <p
                className={`mt-1 whitespace-pre-wrap break-words rounded-control px-3 py-2 text-[13px] leading-5 text-ink ${
                  mine ? 'bg-iris-tint' : m.kind === 'check_request' ? 'border border-iris bg-surface' : m.kind === 'release' ? 'border border-caution bg-caution-tint' : 'border border-line bg-surface'
                }`}
              >
                {m.text}
              </p>
              {mine && m.kind === 'access_request' && <RequestLine status={statusOf(msgs.messages, m)} />}
            </li>
          );
        })}
      </ol>
      <form
        className="shrink-0 border-t border-line bg-surface p-3"
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
        {mode === 'access_request' && cases.length > 0 && (
          <label className="mb-2 flex items-center gap-2 text-xs font-semibold text-ink-2">
            요청할 사례
            <select
              value={reqCase ?? ''}
              onChange={(e) => {
                picked.current = true;
                setReqCase(e.target.value || null);
              }}
              className="h-8 min-w-0 flex-1 rounded-cell border border-line-input bg-surface px-2 text-[13px] font-normal text-ink"
            >
              {!reqCase && <option value="">사례를 고르세요</option>}
              {cases.map((c) => (
                <option key={c.caseId} value={c.caseId}>
                  {c.label} · {c.diagnosis.length > 28 ? `${c.diagnosis.slice(0, 27)}…` : c.diagnosis}
                </option>
              ))}
            </select>
          </label>
        )}
        <label htmlFor="desk-msg" className="sr-only">
          {mode === 'reply' ? '답장' : '세부 정보 요청'}
        </label>
        <textarea
          id="desk-msg"
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void send();
            }
          }}
          rows={3}
          maxLength={500}
          placeholder={mode === 'reply' ? '확인 요청에 답장을 쓰세요' : '필요한 세부 정보와 사유를 쓰세요'}
          className="w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-[13px] leading-5 text-ink outline-none placeholder:text-ink-3 focus:border-focus"
        />
        {msgs.error && <p className="mt-1 text-xs text-danger-text">{msgs.error}</p>}
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="min-w-0 truncate text-[11px] text-ink-3">
            {mode === 'access_request' ? (summary ? `${summary.label}에 대한 요청으로 보냅니다` : '사례를 고르면 그 사례에 대한 요청이 됩니다') : '주고받은 내용은 조회 기록에 남습니다'}
          </span>
          <button type="submit" className="btn-primary btn-sm shrink-0" disabled={msgs.sending || text.trim().length < 2 || (mode === 'access_request' && !reqCase)}>
            {msgs.sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
            {mode === 'reply' ? '답장 보내기' : '요청 보내기'}
          </button>
        </div>
      </form>
    </>
  );
}

/**
 * 개인정보 보호 담당자 창: 고객센터 상담 창처럼 화면 오른쪽에 떠 있다.
 * - 진료 지원 AI 화면에서는 환자 줄의 '보호 담당자에게 묻기'(DeskLauncher)와 새 메시지 수가 늘 보인다.
 *   오른쪽 아래에 떠 있던 단추는 입력칸 아래 상태 줄 · 보내기 단추 · 사례 노트를 가려 환자 줄로 옮겼다 (ADR-0043).
 * - 머리줄 알림 · 대화 위 '답장하기' · 답 아래 안내는 requestOpen으로 이 창을 연다 (어느 화면에서든).
 * - 열린 환자가 없으면(메시지는 대화 하나에 묶인다) 창을 열지 않는다.
 */
export function ProtectionDesk() {
  const msgs = useClinicMessages();
  const { state } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [focusNonce, setFocusNonce] = useState(0);
  const { openPending, consumeOpen } = msgs;
  const available = msgs.supported === true && !state.noConversation;

  useEffect(() => {
    if (!openPending) return;
    consumeOpen();
    if (!available) return;
    setOpen(true);
    setFocusNonce((n) => n + 1);
  }, [openPending, consumeOpen, available]);

  useEffect(() => {
    if (!available) setOpen(false);
  }, [available]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false);
        focusLauncher();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  if (!available) return null;

  return (
    <>
      {open && (
        <section
          role="dialog"
          aria-modal="false"
          aria-labelledby="desk-title"
          className="fixed inset-x-2 bottom-2 top-[20vh] z-40 flex flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay sm:inset-x-auto sm:right-5 sm:top-auto sm:h-[min(560px,calc(100dvh-140px))] sm:w-[372px] lg:bottom-auto lg:right-4 lg:top-[116px] lg:w-[336px]"
        >
          <header className="flex shrink-0 items-start gap-3 border-b border-line px-4 py-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-iris text-iris-on">
              <ShieldCheck className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <h2 id="desk-title" className="text-[15px] font-bold text-ink">
                개인정보 보호 담당자
              </h2>
              <p className="text-xs leading-5 text-ink-3">세부 정보 요청과 확인 요청을 주고받는 창입니다. 지금 진료 중인 환자의 대화에 묶입니다.</p>
            </div>
            <button
              type="button"
              className="btn-ghost h-8 w-8 shrink-0 px-0"
              aria-label="창 닫기"
              onClick={() => {
                setOpen(false);
                focusLauncher();
              }}
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </header>
          <DeskThread focusNonce={focusNonce} />
        </section>
      )}
    </>
  );
}

export const DESK_LAUNCHER_ID = 'desk-launcher';

/** 창을 닫으면 여는 단추로 돌아간다 (단추가 없는 화면이면 그대로). */
function focusLauncher() {
  document.getElementById(DESK_LAUNCHER_ID)?.focus();
}

/**
 * 진료 지원 AI 화면 환자 줄의 '보호 담당자에게 묻기' (ADR-0043).
 * 새 메시지 수를 붙이고, 보호 담당자가 보낸 새 메시지는 단추 아래에 미리 보인다 (닫으면 다음 새 메시지까지 숨김).
 */
export function DeskLauncher() {
  const msgs = useClinicMessages();
  const { state } = useWorkspace();
  /** 미리 보기를 닫은 마지막 메시지 (새 메시지가 오면 다시 보인다) */
  const [peekClosed, setPeekClosed] = useState<string | null>(null);
  if (msgs.supported !== true || state.noConversation) return null;
  const last = msgs.messages[msgs.messages.length - 1];
  const peek = msgs.unread > 0 && last?.sender === 'security' && last.messageId !== peekClosed ? last : null;
  return (
    <span className="relative">
      <button
        id={DESK_LAUNCHER_ID}
        type="button"
        aria-haspopup="dialog"
        aria-label={msgs.unread ? `보호 담당자에게 묻기, 새 메시지 ${msgs.unread}건` : '보호 담당자에게 묻기'}
        title="개인정보 보호 담당자에게 세부 정보 · 확인을 요청합니다"
        onClick={() => msgs.requestOpen(null)}
        className="relative inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-full bg-iris px-2.5 text-xs font-semibold text-iris-on hover:brightness-110"
      >
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden sm:inline">보호 담당자에게 묻기</span>
        {msgs.unread > 0 && (
          <span className="num absolute -right-1.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold text-white ring-2 ring-page">
            {msgs.unread}
          </span>
        )}
      </button>
      {peek && (
        <div className="absolute right-0 top-full z-40 mt-2 w-[280px]">
          <button
            type="button"
            onClick={() => msgs.requestOpen(peek.caseId)}
            className="w-full rounded-control border border-line bg-surface py-2.5 pl-3 pr-8 text-left shadow-overlay hover:border-iris"
          >
            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-iris-text">
              <ShieldCheck className="h-3 w-3" aria-hidden />
              보호 담당자 · {peek.kindLabel}
            </span>
            {/* line-clamp는 display:-webkit-box라 block을 함께 쓰면 두 줄로 줄지 않는다 (승인 결과처럼 긴 메시지가 버튼을 덮음) */}
            <span className="mt-0.5 line-clamp-2 text-[13px] leading-5 text-ink">{peek.text}</span>
          </button>
          <button
            type="button"
            aria-label="미리 보기 닫기"
            onClick={() => setPeekClosed(peek.messageId)}
            className="absolute right-1.5 top-1.5 grid h-6 w-6 place-items-center rounded-full text-ink-3 hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}
    </span>
  );
}
