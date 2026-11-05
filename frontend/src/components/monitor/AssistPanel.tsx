// 검토 보조: 의료진의 세부 정보 요청마다 서버가 만든 검토 초안 (webdemo/backend/assist.py, ADR-0027).
//   추천은 규칙으로 정하고(후보 수 · 조회 목적), 요약과 답장 문장은 실제 LLM이 쓴다 (없거나 실패하면 정해진 문장).
//   초안은 아무것도 보내지 않는다. '승인 창에 담기' · '답장에 넣기'로 담당자가 고쳐서 직접 보낸다.

import { Bot, Check, ChevronDown, ChevronUp, Loader2, MessageSquareReply, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { monitorApi } from '../../api/monitorApi';
import type { Tone } from '../../lib/riskStyles';
import { clockTime } from '../../lib/time';
import type { AssistDraft, AssistItem, AssistState, MonitorDetail } from '../../types/monitor';
import { StatusChip } from '../common/StatusChip';

const REC_TONE: Record<AssistItem['rec'], Tone> = { release: 'safe', consider: 'caution', keep: 'plain', decline: 'danger' };
const VERDICT_TONE: Record<AssistDraft['verdict'], Tone> = { release: 'safe', partial: 'brand', consider: 'caution', keep: 'plain', none: 'plain' };

interface Props {
  d: MonitorDetail;
  /** 지금 답을 기다리는 세부 정보 요청 */
  requestId: string;
  /** 추천대로 공개 승인 창을 연다 (고를 값 · 사유 초안) */
  onApprove(ids: string[], reason: string): void;
  /** 답장 칸에 초안을 넣는다 */
  onReply(text: string): void;
}

export function AssistPanel({ d, requestId, onApprove, onReply }: Props) {
  const [st, setSt] = useState<AssistState>(d.assist ?? { status: 'none' });
  const [steps, setSteps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  // 요청이 바뀌거나 초안을 만드는 중이면 상태를 다시 읽는다
  useEffect(() => {
    let alive = true;
    const ctl = new AbortController();
    const load = () =>
      monitorApi.assist(d.id, ctl.signal).then(
        (x) => {
          if (!alive) return;
          setSt(x);
          setError(null);
          if (x.status === 'running') timer.current = window.setTimeout(load, 900);
        },
        (e) => {
          if (alive && !(e instanceof DOMException)) setError(e instanceof Error ? e.message : '검토 초안을 불러오지 못했습니다.');
        },
      );
    void load();
    return () => {
      alive = false;
      ctl.abort();
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [d.id, requestId, busy]);

  async function rerun() {
    setBusy(true);
    try {
      setSt(await monitorApi.assistRun(d.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : '검토 초안을 다시 만들지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  const draft = st.status === 'ready' && st.requestId === requestId ? st.draft : undefined;
  const running = st.status === 'running' || busy;

  return (
    <section aria-label="검토 보조" className="mt-3 rounded-control border border-line bg-surface text-[13px]">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-3 py-2">
        <Bot className="h-4 w-4 text-iris-text" aria-hidden />
        <h4 className="font-bold text-ink">검토 보조</h4>
        {draft && (
          <span className="text-xs text-ink-3">
            {draft.writerLabel} · {clockTime(draft.createdAt)}
          </span>
        )}
        <span className="flex-1" />
        <button type="button" className="btn-ghost btn-sm h-7 px-2" disabled={running} onClick={() => void rerun()}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
          {running ? '초안 만드는 중' : st.status === 'none' ? '초안 만들기' : '다시 만들기'}
        </button>
      </header>

      {error ? (
        <p className="px-3 py-2.5 text-xs text-danger-text">{error}</p>
      ) : st.status === 'error' ? (
        <p className="px-3 py-2.5 text-xs text-danger-text">{st.error}</p>
      ) : !draft ? (
        <p className="px-3 py-2.5 text-xs leading-5 text-ink-3" aria-live="polite">
          {running
            ? '가린 값마다 공개했을 때의 후보 수와 조회 목적을 확인하고 있습니다.'
            : '이 요청의 검토 초안이 아직 없습니다. 초안 만들기를 누르면 가린 값을 하나씩 확인해 정리합니다.'}
        </p>
      ) : (
        <Draft draft={draft} steps={steps} onSteps={setSteps} onApprove={onApprove} onReply={onReply} />
      )}
    </section>
  );
}

function Draft({
  draft,
  steps,
  onSteps,
  onApprove,
  onReply,
}: {
  draft: AssistDraft;
  steps: boolean;
  onSteps(v: boolean): void;
  onApprove(ids: string[], reason: string): void;
  onReply(text: string): void;
}) {
  return (
    <div className="px-3 pb-3 pt-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={VERDICT_TONE[draft.verdict]}>{draft.verdictLabel}</StatusChip>
        <span className="text-xs text-ink-3">
          {draft.caseLabel} · {draft.purposeLabel} 참고
          {draft.kNow != null && (
            <>
              {' '}
              · 지금 후보 <span className="num text-ink-2">{draft.kNow}명</span> (기준 {draft.kReq}명)
            </>
          )}
        </span>
      </div>
      <p className="mt-2 max-w-[62ch] leading-6 text-ink">{draft.summary}</p>
      {draft.reasonFit && (
        <p className="mt-1 text-xs text-ink-2">
          요청 사유: <b className="font-semibold">{draft.reasonFit}</b>
          {draft.reasonNote ? ` · ${draft.reasonNote}` : ''}
        </p>
      )}

      {draft.items.length > 0 && (
        <ul className="mt-2.5 divide-y divide-line rounded-cell border border-line" aria-label="가린 값마다의 판정">
          {draft.items.map((it) => (
            <li key={it.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 px-3 py-2.5 text-xs">
              <p className="min-w-0 text-ink">
                <b className="text-[13px] font-semibold">{it.attributeLabel}</b>
                <span className="ml-1.5 text-ink-3">
                  {it.where} · {it.actionLabel}
                </span>
              </p>
              <StatusChip tone={REC_TONE[it.rec]}>{it.recLabel}</StatusChip>
              <p className="col-span-2 text-ink-2">
                조회 목적: {it.needLabel} · 하나만 열면 후보{' '}
                <span className={`num ${it.kIfRelease != null && it.kIfRelease < draft.kReq ? 'font-semibold text-danger-text' : 'text-ink'}`}>
                  {it.kIfRelease != null ? `${it.kIfRelease}명` : '–'}
                </span>
              </p>
              <p className="col-span-2 leading-5 text-ink-3">
                {it.why}
                {it.alternative && <span className="block text-ink-2">대안: {it.alternative}</span>}
              </p>
            </li>
          ))}
        </ul>
      )}
      {draft.combinedK != null && (
        <p className="mt-2 text-xs text-ink-2">
          공개 가능한 값 {draft.release.length}개를 함께 열면 후보 <span className="num font-semibold text-ink">{draft.combinedK}명</span>으로 기준 {draft.kReq}명
          이상입니다.
        </p>
      )}

      <button type="button" className="btn-ghost btn-sm mt-2 h-7 px-1.5" aria-expanded={steps} onClick={() => onSteps(!steps)}>
        {steps ? <ChevronUp className="h-3.5 w-3.5" aria-hidden /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
        확인한 순서 {draft.steps.length}단계
      </button>
      {steps && (
        <ol className="mt-1 space-y-1 border-l border-line pl-3 text-xs">
          {draft.steps.map((s, i) => (
            <li key={s.label} className="flex gap-2">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-safe-text" aria-hidden />
              <span>
                <b className="font-semibold text-ink">
                  {i + 1}. {s.label}
                </b>{' '}
                <span className="text-ink-2">{s.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      )}

      <div className="mt-2.5">
        <p className="text-xs font-semibold text-ink-2">의료진에게 보낼 답장 초안</p>
        <blockquote className="mt-1 whitespace-pre-wrap rounded-cell bg-surface-2 px-3 py-2 leading-6 text-ink">{draft.reply}</blockquote>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {draft.release.length > 0 && (
          <button type="button" className="btn-secondary btn-sm" onClick={() => onApprove(draft.release, draft.reason)}>
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            공개 가능 {draft.release.length}개를 승인 창에 담기
          </button>
        )}
        <button type="button" className="btn-secondary btn-sm" onClick={() => onReply(draft.reply)}>
          <MessageSquareReply className="h-3.5 w-3.5" aria-hidden />
          답장 칸에 넣기
        </button>
        <span className="text-[11px] leading-4 text-ink-3">
          초안은 보내지 않습니다. 고쳐서 직접 보내세요.{draft.writer === 'llm' ? ' LLM에는 가린 값의 원문을 보내지 않았습니다.' : ''}
        </span>
      </div>
    </div>
  );
}
