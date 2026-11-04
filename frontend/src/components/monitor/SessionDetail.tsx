import { ChevronDown, ChevronUp, Loader2, MailQuestion, MessageSquareText, Network, Send, ShieldCheck, Stethoscope } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ClueFact } from '../../lib/clueGraph';
import { josa } from '../../lib/korean';
import { caseLabel, clockTime, relativeTime } from '../../lib/time';
import { useTermDetect } from '../../state/TermContext';
import type { MonitorDetail, ReviewAction, ThreadMessage, TurnView } from '../../types/monitor';
import { StatusChip } from '../common/StatusChip';
import { ClueGraph } from '../graph/ClueGraph';
import { AnswerTerms } from '../terminology/AnswerTerms';
import { TermText } from '../terminology/TermText';
import { ApprovalsList, ApprovePanel, CountsSection, RulesSection } from './ReviewTools';

const TONE = { danger: 'danger', caution: 'caution', safe: 'safe' } as const;
const ATTR_KO: Record<string, string> = { AGE: '나이', SEX: '성별', REGION: '거주지', PERIOD: '시점', DX: '진단', PROC: '시술', MED: '약', PLAN: '관리 계획' };
/** 판정 항목(decisions.items.attribute)은 한글 이름으로 온다 → 단서 코드 */
const ATTR_CODE: Record<string, string> = Object.fromEntries(Object.entries(ATTR_KO).map(([k, v]) => [v, k]));

/** 실제 LLM 답은 '사례N · 항목: 값' 줄 모양이 아니므로, 단서는 Defender 판정 항목에서 읽는다. */
function decisionFacts(t: TurnView): ClueFact[] {
  return (t.decisions ?? []).flatMap((p) =>
    p.items.map((it) => ({
      caseRef: p.case,
      caseLabel: caseLabel(p.case),
      attribute: ATTR_CODE[it.attribute] ?? it.attribute,
      attributeLabel: it.attribute,
      value: it.action === 'suppress' ? null : it.action === 'generalize' ? it.to_label : it.raw_value,
      action: it.action,
      turn: t.turn,
    })),
  );
}

/** 메시지 보낸 사람: 운영 모드는 계정 이름, 데모는 역할 */
function senderName(m: ThreadMessage): string {
  if (m.actor && !m.actor.includes('(데모)')) return m.actor.split(' (')[0];
  return m.sender === 'clinician' ? '의료진' : '보안 담당자';
}
const CHANGE = { suppress: { tone: 'danger', label: '가림' }, generalize: { tone: 'caution', label: '일반화' } } as const;

type Group = { kind: 'turn'; turn: TurnView } | { kind: 'fold'; turns: TurnView[] };

function summarize(d: MonitorDetail): string {
  const base = summarizeTurns(d);
  const aps = d.approvals ?? [];
  if (!aps.length) return base;
  const n = aps.reduce((s, ap) => s + ap.items.length, 0);
  return `${base} 그 뒤 보안 담당자가 세부 정보 요청을 승인해 값 ${n}개를 공개했고, 지금 ${caseLabel(d.row.focus_case)} 후보는 ${d.row.k_now ?? '–'}명입니다.`;
}

function summarizeTurns(d: MonitorDetail): string {
  const r = d.row;
  const focus = caseLabel(r.focus_case);
  const turns = d.arms[d.live_arm].turns;
  // 방어 규칙이 지킨 후보 수: 첫 승인 공개 전 마지막 턴 기록 (승인 공개 뒤의 턴은 공개된 값이 더해진 수다)
  const firstAp = Math.min(...(d.approvals ?? []).flatMap((ap) => ap.items.map((x) => x.after_turn ?? Infinity)));
  const upto = turns.filter((t) => t.turn <= firstAp);
  const kTurns = (r.focus_case ? upto[upto.length - 1]?.cases?.[r.focus_case]?.k : null) ?? r.k_now;
  const hits = turns.filter((t) =>
    t.change_notes.some((n) => n.case === r.focus_case && n.changes.some((c) => (r.status === 'danger' ? c.change === 'suppress' : true))),
  ).length;
  const droppedAt = r.focus_case ? turns.find((t) => t.dropped?.includes(r.focus_case!)) : undefined;
  if (droppedAt)
    return `${droppedAt.turn === 0 ? '첫 답(사례 검색)' : `${droppedAt.turn}턴 답`}에서 ${focus} 내용을 그대로 냈다면 후보가 ${r.k_if_raw}명으로 줄 수 있었고, 고친 답도 다시 확인을 통과하지 못해 그 사례만 답에서 뺐습니다. 지금 ${focus} 후보는 ${r.k_now ?? '–'}명입니다.`;
  if (r.status === 'danger')
    return `${focus} 환자를 좁히는 질문에 값을 가린 답이 ${hits}번 있었습니다. 그대로 답했다면 후보가 ${r.k_if_raw}명으로 줄어 환자가 특정될 수 있었습니다. 방어 규칙이 값을 가려 후보 ${kTurns}명을 지켰습니다.`;
  if (r.status === 'caution')
    return `${focus} 답에서 넓은 범주로 바꾼 값이 ${hits}번 있었습니다. 그대로였다면 후보가 ${r.k_if_raw}명이었고, 답한 뒤에는 ${kTurns}명입니다.`;
  return `모든 답을 그대로 보냈습니다. 후보가 기준 ${d.k_req}명보다 많게 유지되었습니다.`;
}

/** 확인 요청 기본 문구 (보안 담당자가 고쳐 보낼 수 있다) */
export const CHECK_DEFAULT = '이 대화에서 같은 사례의 세부 정보를 여러 번 물으셨습니다. 진료에 필요한 내용이었는지 알려 주세요.';

type Composer = { kind: 'reply' | 'check_request'; text: string };

/** 의료진과 주고받은 메시지 (의료진 화면의 '보호 담당자 메시지'와 같은 대화) */
function Thread({ messages }: { messages: ThreadMessage[] }) {
  return (
    <ol className="space-y-2.5">
      {messages.map((m) => {
        const clin = m.sender === 'clinician';
        return (
          <li key={m.id} className={clin ? 'mr-8' : 'ml-8'}>
            <p className={`flex flex-wrap items-center gap-x-1.5 text-[11px] text-ink-3 ${clin ? '' : 'justify-end'}`}>
              {clin && <Stethoscope className="h-3 w-3" aria-hidden />}
              <span className="font-semibold text-ink-2">{senderName(m)}</span>
              <span>{m.kind_label}</span>
              {m.case && <span>{caseLabel(m.case)}</span>}
              <span className="num">{clockTime(m.at)}</span>
            </p>
            <p
              className={`mt-1 whitespace-pre-wrap break-words rounded-control px-3 py-2 text-[13px] leading-5 text-ink ${
                clin ? (m.kind === 'access_request' ? 'border border-iris bg-surface' : 'bg-surface-2') : m.kind === 'release' ? 'border border-caution bg-caution-tint' : 'bg-iris-tint'
              }`}
            >
              {m.text}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

interface Props {
  detail: MonitorDetail;
  onReveal(): void;
  onReview(action: ReviewAction): void;
  /** 의료진에게 답장(reply) 또는 확인 요청(check_request) */
  onMessage(kind: 'reply' | 'check_request', text: string, caseRef: string | null): Promise<boolean>;
  /** 규칙 · 공개 승인 뒤 서버가 돌려준 상세로 바꾼다 */
  onDetail(d: MonitorDetail): void;
  busy: boolean;
}

export function SessionDetail({ detail: d, onReveal, onReview, onMessage, onDetail, busy }: Props) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [rulesOpen, setRulesOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [answers, setAnswers] = useState<Set<number>>(new Set());
  const [composer, setComposer] = useState<Composer | null>(null);
  const [graphOpen, setGraphOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const r = d.row;
  const c1 = d.arms[d.live_arm];
  const messages = d.messages ?? [];
  const pending = r.pending_request ? messages[messages.length - 1] : null;

  // 대화를 바꾸면 쓰던 답장은 닫는다
  useEffect(() => {
    setComposer(null);
    setGraphOpen(false);
    setRulesOpen(false);
    setApproveOpen(false);
  }, [d.id]);
  useEffect(() => {
    if (composer) composerRef.current?.focus();
  }, [composer?.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const facts = useMemo<ClueFact[]>(
    () =>
      c1.turns.flatMap((t) => {
        const fromLines: ClueFact[] = t.lines
          .filter((l) => l.case && l.attribute)
          .map((l) => ({
            caseRef: l.case!,
            caseLabel: caseLabel(l.case),
            attribute: l.attribute!,
            attributeLabel: ATTR_KO[l.attribute!] ?? l.attribute!,
            value: l.change === 'suppress' || l.value == null || l.value === '(비공개)' ? null : l.value,
            action: l.change ?? 'allow',
            turn: t.turn,
          }));
        return fromLines.length ? fromLines : decisionFacts(t);
      }),
    [c1.turns],
  );
  const archived = !!d.archived || !!r.archived;

  async function sendComposer() {
    if (!composer || composer.text.trim().length < 2) return;
    setSending(true);
    const ok = await onMessage(composer.kind, composer.text.trim(), pending?.case ?? r.focus_case ?? null);
    setSending(false);
    if (ok) setComposer(null);
  }
  // 내보낸 답(가드레일을 거친 답) 속 의료 용어: 밑줄과 칩으로 자동 표시
  const { mentions } = useTermDetect(c1.turns.map((t) => t.released ?? ''));
  const focus = r.focus_case;

  const groups = useMemo<Group[]>(() => {
    const out: Group[] = [];
    for (const t of c1.turns) {
      const quiet = t.turn > 0 && t.change_notes.length === 0;
      const prev = out[out.length - 1];
      if (quiet && prev?.kind === 'fold') prev.turns.push(t);
      else if (quiet) out.push({ kind: 'fold', turns: [t] });
      else out.push({ kind: 'turn', turn: t });
    }
    return out.map((g) => (g.kind === 'fold' && g.turns.length === 1 ? { kind: 'turn', turn: g.turns[0] } : g));
  }, [c1.turns]);


  function turnBlock(t: TurnView) {
    const hit = t.change_notes.some((n) => n.changes.some((c) => c.change === 'suppress'));
    const lineAttrs = t.lines.filter((l) => l.case).map((l) => ATTR_KO[l.attribute ?? ''] ?? l.attribute);
    const attrs = [...new Set(lineAttrs.length ? lineAttrs : (t.decisions ?? []).flatMap((p) => p.items.map((it) => it.attribute)))].filter(Boolean);
    const rawFromLines = d.revealed
      ? t.lines.flatMap((l, i) => {
          const raw = t.raw_lines?.[i];
          return l.change && raw?.case ? [`${caseLabel(raw.case)} ${raw.field}: ${raw.value ?? ''}`] : [];
        })
      : [];
    // 실제 LLM 답: 열람 뒤에는 가리거나 넓힌 항목의 원래 값을 판정 항목에서 보여 준다
    const rawChanged =
      rawFromLines.length || !d.revealed
        ? rawFromLines
        : (t.decisions ?? []).flatMap((p) =>
            p.items.filter((it) => it.action !== 'allow' && it.raw_value).map((it) => `${caseLabel(p.case)} ${it.attribute}: ${it.raw_value}`),
          );
    const m = mentions[c1.turns.indexOf(t)];
    const shown = answers.has(t.turn);
    return (
      <div key={t.turn} className="relative grid grid-cols-[28px_1fr] gap-2.5 pb-3.5">
        <span className={`relative z-[1] grid h-[26px] w-[26px] place-items-center rounded-full border bg-surface text-[11px] font-bold ${hit ? 'border-danger text-danger-text' : 'border-line-input text-ink-2'}`}>
          {t.turn}
        </span>
        <div className="min-w-0">
          <p className="text-[13px] text-ink">{t.turn === 0 ? `사례 검색: ${t.question}` : t.question}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
            {t.change_notes.length === 0 ? (
              <>
                <StatusChip tone="safe">허용</StatusChip>
                <span>{attrs.length ? `${attrs.join(', ')} 그대로` : '새 단서 없음'}</span>
              </>
            ) : (
              t.change_notes.flatMap((n) =>
                n.changes.map((c, i) => {
                  const meta = CHANGE[c.change as keyof typeof CHANGE] ?? CHANGE.generalize;
                  return (
                    <span key={`${n.case}-${i}`} className="inline-flex items-center gap-1.5">
                      <StatusChip tone={meta.tone}>{meta.label}</StatusChip>
                      <span>
                        {caseLabel(n.case)} {c.attribute}
                        {n.k_if_raw != null && <span className="text-ink-3"> (그대로면 {n.k_if_raw}명)</span>}
                      </span>
                    </span>
                  );
                }),
              )
            )}
          </div>
          {t.dropped && t.dropped.length > 0 && (
            <p className="mt-1 text-xs text-danger-text">
              {josa(t.dropped.map(caseLabel).join(', '), '은', '는')} 고친 답도 다시 확인을 통과하지 못해 답에서 뺐습니다.
            </p>
          )}
          {t.released && (
            <div className="mt-1.5">
              <button
                type="button"
                className="btn-ghost btn-sm h-6 px-1.5"
                aria-expanded={shown}
                onClick={() => setAnswers((s) => (s.has(t.turn) ? new Set([...s].filter((x) => x !== t.turn)) : new Set(s).add(t.turn)))}
              >
                <MessageSquareText className="h-3.5 w-3.5" aria-hidden />
                {shown ? '답 접기' : '내보낸 답 보기'}
              </button>
              {shown && (
                <p className="mt-1 whitespace-pre-wrap rounded-cell border border-line bg-surface px-3 py-2 text-[13px] leading-relaxed text-ink">
                  <TermText text={t.released} mentions={m} />
                </p>
              )}
              <AnswerTerms mentions={[m]} max={5} label="답에 나온 의료 용어" />
            </div>
          )}
          {rawChanged.length > 0 && (
            <div className="mt-1.5 rounded-cell bg-surface-2 px-2.5 py-1.5 text-xs leading-5 text-ink-2">
              {rawChanged.map((ln) => (
                <div key={ln}>
                  <span className="mr-1.5 font-semibold text-ink">원래 답</span>
                  {ln}
                </div>
              ))}
            </div>
          )}
        </div>
        <span className="absolute bottom-0 left-[13px] top-[26px] w-px bg-line" aria-hidden />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-line px-5 pb-4 pt-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="font-mono text-[15px] font-medium">{d.trial_id}</span>
          <StatusChip tone={TONE[r.status]}>{r.status_label}</StatusChip>
          <span className="text-xs text-ink-3">
            {d.source_label}
            {r.owner ? ` · ${r.owner}` : ''} {r.turns}턴 {relativeTime(r.last_active)}
          </span>
          {r.llm_mode === 'live' && <StatusChip tone="plain">실제 LLM 대화</StatusChip>}
          {r.review && <StatusChip tone="plain">{r.review.label}</StatusChip>}
        </div>
        {archived && (
          <p className="mt-2 rounded-control bg-surface-2 px-3 py-2 text-xs leading-5 text-ink-2">
            서버를 다시 켜기 전 대화입니다. 기록과 판정은 DB에 남은 그대로 볼 수 있고, 원문 열람 · 검토 표시는 되지만 메시지는 보낼 수 없습니다.
          </p>
        )}
        <p className="mt-3 max-w-[40em] text-[15px] leading-relaxed">{summarize(d)}</p>
        {pending && !archived && (
          <div className="mt-3 flex flex-wrap items-start gap-x-3 gap-y-2 rounded-control border border-iris bg-iris-tint px-3 py-2.5 text-[13px]">
            <MailQuestion className="mt-0.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
            <span className="min-w-0 flex-1">
              <strong className="font-semibold">{pending.kind === 'access_request' ? '의료진이 세부 정보를 요청했습니다' : '의료진이 답장했습니다'}</strong>
              {pending.case && <span className="ml-1 text-ink-2">({caseLabel(pending.case)})</span>}
              <span className="mt-0.5 block text-xs text-ink-2">아래 메시지를 읽고 답장해 주세요. 답장은 의료진 화면의 보호 담당자 메시지에 바로 뜹니다.</span>
            </span>
            {pending.kind === 'access_request' && (
              <button type="button" className="btn-secondary btn-sm" aria-expanded={approveOpen} onClick={() => setApproveOpen((v) => !v)}>
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                값 공개 승인
              </button>
            )}
            <button type="button" className="btn-primary btn-sm" onClick={() => setComposer({ kind: 'reply', text: '' })}>
              답장하기
            </button>
          </div>
        )}
        {approveOpen && pending && !archived && <ApprovePanel d={d} caseRef={pending.case} onCancel={() => setApproveOpen(false)} onDetail={onDetail} />}
        {r.awaiting_clinician && !pending && <p className="mt-2 text-xs text-ink-3">의료진에게 확인 요청을 보냈고 답을 기다리는 중입니다.</p>}
      </header>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {(messages.length > 0 || composer) && (
          <section aria-label="의료진과 주고받은 메시지" className="border-b border-line px-5 py-4">
            <h3 className="mb-2.5 flex items-center gap-1.5 text-[13px] font-bold text-ink-2">
              의료진과 주고받은 메시지 <span className="num text-xs font-medium text-ink-3">{messages.length}</span>
            </h3>
            <Thread messages={messages} />
            {composer ? (
              <form
                className="mt-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void sendComposer();
                }}
              >
                <label htmlFor="sec-msg" className="mb-1 block text-xs font-semibold text-ink-2">
                  {composer.kind === 'check_request' ? '의료진에게 보낼 확인 요청 (의료진 화면 대화 위에 뜹니다)' : '의료진에게 보낼 답장'}
                </label>
                <textarea
                  id="sec-msg"
                  ref={composerRef}
                  value={composer.text}
                  onChange={(e) => setComposer({ ...composer, text: e.target.value })}
                  rows={3}
                  maxLength={500}
                  placeholder="원래 값은 쓰지 말고 처리 결과와 대안을 적어 주세요"
                  className="w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-[13px] leading-5 text-ink outline-none placeholder:text-ink-3 focus:border-focus"
                />
                <div className="mt-1.5 flex justify-end gap-1.5">
                  <button type="button" className="btn-ghost btn-sm" onClick={() => setComposer(null)}>
                    취소
                  </button>
                  <button type="submit" className="btn-primary btn-sm" disabled={sending || busy || composer.text.trim().length < 2}>
                    {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
                    {composer.kind === 'check_request' ? '확인 요청 보내기' : '답장 보내기'}
                  </button>
                </div>
              </form>
            ) : archived ? null : (
              <button type="button" className="btn-ghost btn-sm mt-2" onClick={() => setComposer({ kind: 'reply', text: '' })}>
                <Send className="h-3.5 w-3.5" aria-hidden /> 답장 쓰기
              </button>
            )}
          </section>
        )}

        <CountsSection d={d} onReveal={onReveal} />
        <RulesSection d={d} open={rulesOpen} onOpen={setRulesOpen} onDetail={onDetail} />
        <ApprovalsList d={d} />

        <section aria-label="단서 그래프" className="border-b border-line">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-5 py-3 text-left text-[13px] font-bold text-ink-2 hover:bg-surface-2"
            aria-expanded={graphOpen}
            onClick={() => setGraphOpen((o) => !o)}
          >
            <Network className="h-4 w-4 text-ink-3" aria-hidden />
            단서 그래프
            <span className="font-normal text-ink-3">사례와 답에 나간 값이 어떻게 이어지는지</span>
            {graphOpen ? <ChevronUp className="ml-auto h-4 w-4" aria-hidden /> : <ChevronDown className="ml-auto h-4 w-4" aria-hidden />}
          </button>
          {graphOpen && <ClueGraph facts={facts} focusCase={focus} />}
        </section>

        <div className="px-5 pt-4">
          <h3 className="mb-2.5 text-[13px] font-bold text-ink-2">질문 흐름</h3>
          {groups.map((g, gi) =>
            g.kind === 'turn' ? (
              turnBlock(g.turn)
            ) : open.has(gi) ? (
              <div key={`f${gi}`}>
                {g.turns.map(turnBlock)}
                <button type="button" className="btn-ghost btn-sm mb-3 ml-9 h-6 px-1.5" onClick={() => setOpen((s) => new Set([...s].filter((x) => x !== gi)))}>
                  <ChevronUp className="h-3.5 w-3.5" aria-hidden /> 접기
                </button>
              </div>
            ) : (
              <div key={`f${gi}`} className="relative grid grid-cols-[28px_1fr] gap-2.5 pb-3.5">
                <span className="relative z-[1] grid h-[26px] w-[26px] place-items-center rounded-full border border-dashed border-line-input bg-surface text-[10px] font-bold text-ink-2">
                  {g.turns[0].turn}–{g.turns[g.turns.length - 1].turn}
                </span>
                <p className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
                  {g.turns.length}턴 모두 그대로 답했습니다.
                  <button type="button" className="btn-ghost btn-sm h-6 px-1.5" onClick={() => setOpen((s) => new Set(s).add(gi))}>
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden /> 펼치기
                  </button>
                </p>
                <span className="absolute bottom-0 left-[13px] top-[26px] w-px bg-line" aria-hidden />
              </div>
            ),
          )}
        </div>
      </div>

      <footer className="flex flex-wrap gap-2 border-t border-line px-5 py-3.5">
        <button type="button" className="btn-primary" disabled={busy} onClick={() => onReview('reviewed')}>
          검토 완료
        </button>
        {!archived && (
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            aria-expanded={composer?.kind === 'check_request'}
            onClick={() => setComposer({ kind: 'check_request', text: CHECK_DEFAULT })}
          >
            의료진에게 확인 요청
          </button>
        )}
        <span className="flex-1" />
        {!archived && (
          <button type="button" className="btn-ghost" disabled={busy} aria-expanded={rulesOpen} onClick={() => setRulesOpen((v) => !v)}>
            <ShieldCheck className="h-4 w-4" aria-hidden />
            이 대화에 규칙 걸기
          </button>
        )}
      </footer>
    </div>
  );
}
