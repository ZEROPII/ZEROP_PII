import { AlertCircle, Check, CircleHelp, Copy, Loader2, Lock, MailQuestion, RotateCw, Trash2 } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { parseAnswer, type AnswerBlock, type Inline } from '../../lib/answerLines';
import { answerPlainText, attrName, chartCopyText, protectionNote, refLabel, requestDraft, whyText } from '../../lib/clinicianCopy';
import { latestRequest, REQUEST_STATE_KO } from '../../lib/requests';
import { formatTime } from '../../lib/format';
import { useClinicMessages } from '../../state/ClinicMessages';
import { useTermDetect } from '../../state/TermContext';
import type { CaseSummary, ChatMessage, MessageSegment, PrivacyTransformation, ProtectionResult } from '../../types/domain';
import type { TermMention } from '../../types/terminology';
import { LogoMark } from '../brand/Logo';
import { useToast } from '../layout/Toast';
import { AnswerTerms } from '../terminology/AnswerTerms';
import { TermText } from '../terminology/TermText';
import { ClinicValue, GatedMark } from './ClinicValue';

interface Props {
  message: ChatMessage;
  /** 지금 고른 사례 이름 ('사례 1') */
  caseLabel: string;
  cases: CaseSummary[];
  /** 백링크로 이 자리에 왔을 때 잠깐 강조 */
  flash?: boolean;
  onRetry?: (message: ChatMessage) => void;
  onDiscard?: (message: ChatMessage) => void;
  /** 이 답 다음 질문을 보낸 때. 그 전에 보낸 세부 정보 요청만 이 답의 요청으로 본다 */
  until?: string;
}

function caseIdOfRef(ref: string | undefined, cases: CaseSummary[]): string | null {
  if (!ref) return null;
  return cases.find((c) => c.label.replace(/\s+/g, '') === ref.replace(/\s+/g, ''))?.caseId ?? null;
}

const GATED = '(비공개)';

/** 글 속 '(비공개)'(AI에 보내지 않은 값)를 표시로 바꾸고, 나머지 글은 의료 용어 밑줄 (용어 위치는 조각마다 옮긴다) */
function GatedText({ text, mentions }: { text: string; mentions: TermMention[] | undefined }) {
  if (!text.includes(GATED)) return <TermText text={text} mentions={mentions} />;
  const out: JSX.Element[] = [];
  let pos = 0;
  for (let k = 0; ; k += 2) {
    const at = text.indexOf(GATED, pos);
    const end = at < 0 ? text.length : at;
    if (end > pos) {
      const ms = mentions?.filter((m) => m.start >= pos && m.end <= end).map((m) => ({ ...m, start: m.start - pos, end: m.end - pos }));
      out.push(<TermText key={k} text={text.slice(pos, end)} mentions={ms} />);
    }
    if (at < 0) break;
    out.push(<GatedMark key={k + 1} />);
    pos = at + GATED.length;
  }
  return <>{out}</>;
}

/** 조각 하나: 글이면 의료 용어 밑줄, 보호 조치가 걸린 값이면 범위 · 비공개 표시 */
function Piece({ seg, tf, mentions, named }: { seg: MessageSegment; tf: Map<string, PrivacyTransformation>; mentions: TermMention[] | undefined; named: boolean }) {
  const terms = <GatedText text={seg.text} mentions={mentions} />;
  if (seg.kind === 'text') return terms;
  if (seg.placeholder)
    return <ClinicValue text={seg.text} transformation={tf.get(seg.transformationId)} placeholderLabel={seg.label ?? '값'} partial={seg.partial} />;
  return (
    <ClinicValue text={seg.text} transformation={tf.get(seg.transformationId)} named={named}>
      {terms}
    </ClinicValue>
  );
}

/** named: 글 안의 '비공개' 표시에 단서 이름을 붙인다 ('처방 약 비공개'). 항목 이름이 따로 보이는 줄(fact)에서는 붙이지 않는다. */
function Pieces({ run, tf, mentions, named = true }: { run: Inline[]; tf: Map<string, PrivacyTransformation>; mentions: (TermMention[] | undefined)[]; named?: boolean }) {
  return (
    <>
      {run.map((p) =>
        p.bold ? (
          <strong key={p.k} className="font-semibold">
            <Piece seg={p.seg} tf={tf} mentions={mentions[p.k]} named={named} />
          </strong>
        ) : (
          <Piece key={p.k} seg={p.seg} tf={tf} mentions={mentions[p.k]} named={named} />
        ),
      )}
    </>
  );
}

function Block({ b, tf, mentions, showCase }: { b: AnswerBlock; tf: Map<string, PrivacyTransformation>; mentions: (TermMention[] | undefined)[]; showCase: boolean }) {
  const run = (r: Inline[], named = true) => <Pieces run={r} tf={tf} mentions={mentions} named={named} />;
  switch (b.kind) {
    case 'fact':
      return (
        <div className="grid grid-cols-1 gap-x-4 gap-y-0.5 border-b border-line py-2 last:border-b-0 sm:grid-cols-[minmax(150px,38%)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[13px] text-ink-2">
            {showCase && <span className="rounded-[5px] bg-surface-2 px-1.5 text-xs font-semibold text-ink">{refLabel(b.caseRef)}</span>}
            <span>{b.field}</span>
            {b.source && (
              <span className="text-[11px] text-ink-3" title="사례 기록 안에서 이 값이 나온 곳">
                {b.source.replace(/^기록\s*(\d+)$/, '기록 $1')}
              </span>
            )}
          </div>
          <div className="min-w-0 break-words font-medium">{run(b.value, false)}</div>
        </div>
      );
    case 'heading':
      return b.level <= 2 ? (
        <h4 className="mb-1 mt-3 text-[15px] font-bold text-ink first:mt-0">{run(b.content)}</h4>
      ) : (
        <h5 className="mb-0.5 mt-2.5 text-sm font-semibold text-ink first:mt-0">{run(b.content)}</h5>
      );
    case 'para':
      return (
        <p className="break-words py-1">
          {b.lines.map((l, i) => (
            <span key={i}>
              {i > 0 && <br />}
              {run(l)}
            </span>
          ))}
        </p>
      );
    case 'list':
      return (
        <ul className="my-1 space-y-0.5">
          {b.items.map((it, i) => (
            <li key={i} className="flex gap-2" style={{ paddingLeft: it.depth * 16 }}>
              <span aria-hidden className={`shrink-0 text-ink-3 ${it.marker ? 'num min-w-[1.25rem] text-right' : 'w-3 text-center'}`}>
                {it.marker ?? '•'}
              </span>
              <span className="min-w-0 break-words">{run(it.content)}</span>
            </li>
          ))}
        </ul>
      );
    case 'table':
      return (
        <div className="my-2 overflow-x-auto rounded-cell border border-line">
          <table className="w-full border-collapse text-[13px]">
            {b.head && (
              <thead className="bg-surface-2 text-left text-ink-2">
                <tr>
                  {b.head.map((c, i) => (
                    <th key={i} scope="col" className="border-b border-line px-2.5 py-1.5 font-semibold">
                      {run(c)}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri} className="align-top">
                  {r.map((c, ci) => (
                    <td key={ci} className="border-b border-line px-2.5 py-1.5 [tr:last-child_&]:border-b-0">
                      {run(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'rule':
      return <hr className="my-2 border-line" />;
  }
}

function AnswerBody({ message, caseLabel }: { message: ChatMessage; caseLabel: string }) {
  const parsed = useMemo(() => parseAnswer(message.segments), [message.segments]);
  const tf = useMemo(() => new Map((message.protection?.transformations ?? []).map((t) => [t.id, t])), [message.protection]);
  // 읽는 순서로 편 조각에서 의료 용어를 한 번에 찾는다 (조각 번호 k = mentions 번호)
  const { mentions } = useTermDetect(parsed.pieces.map((p) => p.seg.text));
  const ownRef = caseLabel.replace(/\s+/g, '');
  const refs = new Set(parsed.blocks.flatMap((b) => (b.kind === 'fact' ? [b.caseRef] : [])));
  const showCase = refs.size > 1 || (refs.size === 1 && !refs.has(ownRef));
  const gated = message.segments.some((x) => x.kind === 'text' && x.text.includes(GATED));

  return (
    <>
      <div className="px-4 py-3 text-sm leading-relaxed text-ink">
        <span className="sr-only">AI 답변: </span>
        {parsed.blocks.map((b, i) => (
          <Block key={i} b={b} tf={tf} mentions={mentions} showCase={showCase} />
        ))}
      </div>
      {gated && (
        <p className="px-4 pb-1.5 text-[11.5px] leading-5 text-ink-3">
          <span className="font-semibold text-emr-lock">AI에 보내지 않음</span>은 MediCloak이 과거 사례 기록을 진료 지원 AI에 넘기기 전에 가린 값입니다.
          누르면 설명이 보입니다.
        </p>
      )}
      <div className="px-4 pb-1 empty:hidden">
        <AnswerTerms mentions={mentions} label="이 답의 의료 용어" />
      </div>
    </>
  );
}

/** 이 답에서 MediCloak이 바꾼 곳을 사례마다: 비공개 · 범위로 보인 항목 이름 (몇 개인지는 보이지 않는다) */
export function changesByCase(p: ProtectionResult): { ref: string | null; hidden: string[]; ranged: string[]; dropped: boolean }[] {
  const rows = new Map<string, { ref: string | null; hidden: string[]; ranged: string[]; dropped: boolean }>();
  for (const t of p.transformations) {
    if (t.action === 'allow') continue;
    const key = t.caseRef ?? '';
    const row = rows.get(key) ?? { ref: t.caseRef ?? null, hidden: [], ranged: [], dropped: false };
    const name = attrName(t);
    if (t.dropped) row.dropped = true;
    else if (t.action === 'suppress' && !row.hidden.includes(name)) row.hidden.push(name);
    else if (t.action === 'generalize' && !row.ranged.includes(name)) row.ranged.push(name);
    rows.set(key, row);
  }
  return [...rows.values()]
    .filter((r) => r.dropped || r.hidden.length || r.ranged.length)
    .sort((a, b) => (a.ref ?? '').localeCompare(b.ref ?? '', 'ko', { numeric: true }));
}

/** 답 아래: 사례마다 무엇을 가리고 넓혔는지 + 표시 읽는 법 */
function ChangeMap({ p }: { p: ProtectionResult }) {
  const rows = changesByCase(p);
  if (!rows.length) return null;
  return (
    <div className="mt-2 rounded-control bg-surface px-3 py-2">
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.ref ?? '-'} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-[12.5px]">
            <span className="min-w-[3.25rem] font-semibold text-ink">{r.ref ? refLabel(r.ref) : '이 답'}</span>
            {r.dropped && <span className="text-ink-2">이 답에서 사례 내용을 뺐습니다</span>}
            {r.hidden.length > 0 && (
              <span className="inline-flex items-baseline gap-1 text-ink-2">
                <Lock className="h-3 w-3 shrink-0 translate-y-[1px] text-emr-lock" strokeWidth={2.4} aria-hidden />
                {r.hidden.join(' · ')} 비공개
              </span>
            )}
            {r.ranged.length > 0 && (
              <span className="text-ink-2">
                <span className="range-value">{r.ranged.join(' · ')}</span> 범위로
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11.5px] leading-5 text-ink-3">
        글 속 <span className="font-semibold text-emr-lock">비공개</span> · <span className="font-semibold text-iris-text">범위</span> 표시를 누르면 그 자리에서
        무엇을 왜 바꿨는지 보입니다. 표시는 진료 지원 AI가 아니라 MediCloak이 붙였고, 과거 사례 기록은 그대로입니다.
      </p>
    </div>
  );
}

function ProtectionFooter({ message, caseLabel, cases, until }: { message: ChatMessage; caseLabel: string; cases: CaseSummary[]; until?: string }) {
  const p = message.protection!;
  const note = protectionNote(p);
  const msgs = useClinicMessages();
  const toast = useToast();
  const [why, setWhy] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  /** 요청할 사례: 이 답에서 값이 바뀐 사례가 여럿이면 의료진이 고른다 (기본은 첫 사례) */
  const [pickRef, setPickRef] = useState<string | null>(null);
  /** 화면이 채운 마지막 초안. 고치지 않았으면 사례를 바꿀 때 그 사례 초안으로 바꾼다 */
  const autoDraft = useRef('');
  if (!note) return null;

  // 조회 목적에 필요 없어 뺀 값(거주 지역)은 세부 정보 요청 대상이 아니다
  const changed = p.transformations.filter((t) => t.action !== 'allow' && !t.purpose);
  const refs = [...new Set(changed.map((t) => t.caseRef).filter((r): r is string => !!r))];
  const who = refs.length === 1 ? refLabel(refs[0]) : refs.length > 1 ? '해당 사례' : caseLabel;
  const ref = pickRef && refs.includes(pickRef) ? pickRef : refs[0];
  const requestCase = caseIdOfRef(ref, cases) ?? message.caseId;
  const requestLabel = ref ? refLabel(ref) : caseLabel;
  const namesFor = (r: string | undefined) => changed.filter((t) => !r || t.caseRef === r).map(attrName);
  const canRequest = msgs.supported === true && changed.length > 0;
  // 이 답 뒤에 이 답의 사례(들)로 보낸 요청이 있으면 그 처리 상태 (사례를 바꿨다 돌아와 다시 그려도 유지)
  const refCases = refs.map((r) => caseIdOfRef(r, cases)).filter((c): c is string => !!c);
  const status = latestRequest(msgs.messages, refCases.length ? refCases : requestCase, message.createdAt, until);
  const requested = sent || status !== null;

  function openDraft() {
    if (draft !== null) {
      setDraft(null);
      return;
    }
    const d = requestDraft(requestLabel, namesFor(ref));
    autoDraft.current = d;
    setDraft(d);
  }

  function pick(r: string) {
    setPickRef(r);
    const next = requestDraft(refLabel(r), namesFor(r));
    setDraft((cur) => {
      if (cur !== null && cur !== autoDraft.current) return cur; // 의료진이 고친 초안은 그대로 둔다
      autoDraft.current = next;
      return next;
    });
  }

  async function send() {
    if (!draft?.trim()) return;
    const ok = await msgs.send({ kind: 'access_request', text: draft.trim(), caseId: requestCase });
    if (ok) {
      setDraft(null);
      setSent(true);
      toast('세부 정보 요청을 보냈습니다.');
    }
  }

  return (
    <div className="border-t border-line bg-page px-4 py-2.5 text-[13px] text-ink-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="inline-flex min-w-0 items-start gap-1.5">
          <Lock className="mt-[3px] h-3.5 w-3.5 shrink-0 text-emr-lock" aria-hidden />
          <span>{note.text}</span>
        </span>
        <span className="ml-auto flex items-center gap-1">
          <button type="button" className="btn-ghost btn-sm h-7" aria-expanded={why} onClick={() => setWhy((w) => !w)}>
            <CircleHelp className="h-3.5 w-3.5" aria-hidden />
            왜 그런가요?
          </button>
          {canRequest && !requested && (
            <button
              type="button"
              className="btn-ghost btn-sm h-7 text-iris-text"
              aria-expanded={draft !== null}
              onClick={openDraft}
            >
              <MailQuestion className="h-3.5 w-3.5" aria-hidden />
              세부 정보 요청
            </button>
          )}
          {canRequest && requested && (
            <button
              type="button"
              onClick={() => msgs.requestOpen(requestCase)}
              className={`btn-ghost btn-sm h-7 gap-1 text-xs font-semibold ${status?.state === 'released' ? 'text-safe-text' : 'text-iris-text'}`}
              title={`${requestLabel}에 대한 세부 정보 요청${status?.doneAt ? ` · ${formatTime(status.doneAt)} 처리` : ''}. 눌러서 보호 담당자 창 열기`}
            >
              <Check className="h-3.5 w-3.5" aria-hidden />
              요청함 · {REQUEST_STATE_KO[status?.state ?? 'pending']}
            </button>
          )}
        </span>
      </div>
      <ChangeMap p={p} />
      {why && (
        <div className="mt-2 space-y-1.5 rounded-control bg-surface px-3 py-2.5 leading-6 text-ink-2">
          {whyText(p, who).map((t) => (
            <p key={t}>{t}</p>
          ))}
          {canRequest && <p>진료에 꼭 필요하면 세부 정보 요청을 보내 주세요. 개인정보 보호 담당자가 확인하고 답합니다.</p>}
        </div>
      )}
      {draft !== null && (
        <form
          className="mt-2 rounded-control border border-line-input bg-surface p-2 focus-within:border-focus"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          {refs.length > 1 && (
            <div role="radiogroup" aria-label="요청할 사례" className="mb-1.5 flex flex-wrap items-center gap-1.5 px-1">
              <span className="text-xs font-semibold text-ink-2">요청할 사례</span>
              {refs.map((r) => (
                <button
                  key={r}
                  type="button"
                  role="radio"
                  aria-checked={r === ref}
                  onClick={() => pick(r)}
                  className={`h-6 rounded-full border px-2 text-xs ${r === ref ? 'border-iris bg-iris-tint font-semibold text-iris-text' : 'border-line-input text-ink-2 hover:text-ink'}`}
                >
                  {refLabel(r)}
                </button>
              ))}
            </div>
          )}
          <label htmlFor={`req-${message.messageId}`} className="mb-1 block px-1 text-xs font-semibold text-ink-2">
            {requestLabel}에 대해 개인정보 보호 담당자에게 보낼 요청 (사유를 적어 주세요)
          </label>
          <textarea
            id={`req-${message.messageId}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            autoFocus
            maxLength={500}
            className="w-full resize-none bg-transparent px-1 text-[13px] leading-5 text-ink outline-none"
          />
          {msgs.error && <p className="px-1 text-xs text-danger-text">{msgs.error}</p>}
          <div className="mt-1 flex justify-end gap-1.5">
            <button type="button" className="btn-ghost btn-sm" onClick={() => setDraft(null)}>
              취소
            </button>
            <button type="submit" className="btn-primary btn-sm" disabled={msgs.sending || draft.trim().length < 2}>
              {msgs.sending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
              요청 보내기
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export function ClinicalMessage({ message, caseLabel, cases, flash = false, onRetry, onDiscard, until }: Props) {
  const toast = useToast();
  if (message.role === 'user') {
    return (
      <div id={`m-${message.messageId}`} className={`rounded-control ${flash ? 'jump-flash' : ''}`}>
        <div className="flex items-baseline gap-2.5">
          <span className="num shrink-0 text-xs font-semibold text-iris-text">질문 {message.turn}</span>
          {message.scope === 'all' && (
            <span className="shrink-0 rounded-[5px] bg-iris-tint px-1.5 py-px text-[11px] font-semibold text-iris-text" title="찾은 사례 전체에 물은 질문">
              사례 전체
            </span>
          )}
          <p className={`min-w-0 flex-1 whitespace-pre-wrap break-words text-[15px] font-semibold leading-snug text-ink ${message.status !== 'sent' ? 'opacity-70' : ''}`}>
            {message.segments.map((s) => s.text).join('')}
          </p>
          {message.status === 'sent' && (
            <time dateTime={message.createdAt} className="num shrink-0 text-[11px] text-ink-3">
              {formatTime(message.createdAt)}
            </time>
          )}
        </div>
        {message.status === 'pending' && (
          <p className="ml-[52px] mt-1 inline-flex items-center gap-1 text-[11px] text-ink-3">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> 보내는 중
          </p>
        )}
        {message.status === 'failed' && (
          <p className="ml-[52px] mt-1 inline-flex flex-wrap items-center gap-2 text-xs text-danger-text">
            <AlertCircle className="h-3.5 w-3.5" aria-hidden /> 보내지 못했습니다
            {onRetry && (
              <button type="button" onClick={() => onRetry(message)} className="inline-flex items-center gap-0.5 font-semibold hover:underline">
                <RotateCw className="h-3 w-3" aria-hidden /> 다시 보내기
              </button>
            )}
            {onDiscard && (
              <button type="button" onClick={() => onDiscard(message)} className="inline-flex items-center gap-0.5 font-semibold hover:underline">
                <Trash2 className="h-3 w-3" aria-hidden /> 지우기
              </button>
            )}
          </p>
        )}
      </div>
    );
  }

  async function copy() {
    try {
      const tf = message.protection?.transformations ?? [];
      const body = answerPlainText(message.segments, tf);
      await navigator.clipboard.writeText(chartCopyText(body, caseLabel, { protectedCount: tf.filter((t) => t.action !== 'allow').length }));
      toast('진료 기록에 붙일 수 있게 출처와 함께 복사했습니다. 가린 값은 (비공개)로 들어갑니다.');
    } catch {
      toast('복사하지 못했습니다. 글을 직접 선택해 복사하세요.');
    }
  }

  return (
    <article id={`m-${message.messageId}`} className={`overflow-hidden rounded-panel border border-line bg-surface ${flash ? 'jump-flash' : ''}`}>
      <header className="flex items-center gap-2 px-4 pt-2.5 text-xs text-ink-3">
        <LogoMark size={16} className="text-iris-text" />
        <span className="font-semibold text-ink-2">진료 지원 AI</span>
        <time dateTime={message.createdAt} className="num ml-auto">
          {formatTime(message.createdAt)}
        </time>
        <button type="button" onClick={() => void copy()} className="btn-ghost h-7 w-7 px-0" aria-label="답 복사 (진료 기록에 붙이기)" title="답 복사">
          <Copy className="h-3.5 w-3.5" aria-hidden />
        </button>
      </header>
      <AnswerBody message={message} caseLabel={caseLabel} />
      {message.protection && <ProtectionFooter message={message} caseLabel={caseLabel} cases={cases} until={until} />}
    </article>
  );
}
