import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '../api';
import { MONITOR_UNAVAILABLE, monitorApi } from '../api/monitorApi';
import { ErrorState, EmptyState, LoadingState } from '../components/common/StatusViews';
import { useToast } from '../components/layout/Toast';
import { QueueTable } from '../components/monitor/QueueTable';
import { RevealDialog } from '../components/monitor/RevealDialog';
import { SessionDetail } from '../components/monitor/SessionDetail';
import type { MonitorDetail, MonitorOverview, MonitorRow, ReviewAction, ThreadMessage } from '../types/monitor';

type TabId = 'all' | 'review' | 'danger' | 'caution' | 'safe';
const TABS: { id: TabId; label: string; match(r: MonitorRow): boolean }[] = [
  { id: 'all', label: '전체', match: () => true },
  { id: 'review', label: '확인 필요', match: (r) => r.needs_review },
  { id: 'danger', label: '막음', match: (r) => r.status === 'danger' },
  { id: 'caution', label: '넓혀서 답함', match: (r) => r.status === 'caution' },
  { id: 'safe', label: '이상 없음', match: (r) => r.status === 'safe' },
];
const REVIEW_TOAST: Record<ReviewAction, string> = {
  reviewed: '검토 완료로 표시했습니다.',
  ask_clinician: '의료진에게 확인 요청을 보냈습니다. 의료진 화면 대화 위에 뜹니다.',
  add_rule: '질문 패턴을 규칙 후보에 추가했습니다.',
};
const POLL_MS = 3000;

/** 메시지 목록 응답은 공개 승인 메시지의 값을 늘 지운다. 원문을 열람한 상세에서는 이미 받은 값을 그대로 둔다. */
function keepRevealed(d: MonitorDetail, next: ThreadMessage[]): ThreadMessage[] {
  if (!d.revealed) return next;
  const shown = new Map(d.messages.filter((m) => m.kind === 'release' && !m.masked).map((m) => [m.id, m]));
  return next.map((m) => (m.masked && shown.has(m.id) ? shown.get(m.id)! : m));
}

function Brief({ o }: { o: MonitorOverview }) {
  const k = o.kpi;
  let text;
  if (k.identified > 0) text = <>기준 아래로 내려간 사례가 <em className="not-italic text-danger-text">{k.identified}건</em> 있습니다. 바로 확인하세요.</>;
  else if (k.requests > 0)
    text = (
      <>
        의료진이 보낸 요청 <em className="not-italic text-iris-text">{k.requests}건</em>이 답을 기다립니다. 목록 맨 위 대화에서 답장해 주세요.
      </>
    );
  else if (k.needs_review > 0)
    text = (
      <>
        같은 환자를 계속 좁혀 묻는 대화가 <em className="not-italic text-danger-text">{k.needs_review}건</em> 있습니다. 방어 규칙이 답을 가려 특정된 환자는 없지만, 질문한 의도를 확인해 보세요.
      </>
    );
  else if (k.blocked_sessions > 0) text = <>지금 확인할 대화는 없습니다. 특정 시도 {k.blocked_sessions}건은 방어 규칙이 자동으로 막았습니다.</>;
  else text = <>모든 대화가 기준을 지키고 있습니다. 의료진 화면에서 질문하면 이 목록에 바로 나타납니다.</>;
  return (
    <section className="grid gap-5 px-4 pb-4 pt-5 md:px-6 xl:grid-cols-[1fr_auto] xl:items-end">
      <p className="max-w-[30em] text-[21px] font-bold leading-[1.42] tracking-[-0.025em] md:text-2xl">{text}</p>
      <dl className="grid grid-cols-[auto_auto] gap-x-5 gap-y-1 text-[13px] sm:grid-cols-[auto_auto_auto_auto]" aria-label="지금까지 집계">
        {(
          [
            ['살핀 대화', `${k.sessions.toLocaleString()}건`, '관제 목록에 있는 대화 수 (지난 대화 포함)'],
            ['가린 값', `${k.suppressed.toLocaleString()}개`, '의료진 화면 답의 공개 계획에서 비공개로 정한 단서 수'],
            ['넓힌 값', `${k.generalized.toLocaleString()}개`, '넓은 범주로 바꿔 보낸 단서 수'],
            [`기준 ${o.k_req}명 아래 사례`, `${k.identified.toLocaleString()}건`, `지금 후보가 ${o.k_req}명 아래인 사례 수 (승인 공개로 내려간 사례 포함)`],
          ] as const
        ).map(([l, v, help]) => (
          <div key={l} className="contents" title={help}>
            <dt className="text-ink-3">{l}</dt>
            <dd className={`num text-right font-semibold ${l.startsWith('기준') && k.identified > 0 ? 'text-danger-text' : 'text-ink'}`}>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function MonitorPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [overview, setOverview] = useState<MonitorOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>('all');
  const [detail, setDetail] = useState<MonitorDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [revealOpen, setRevealOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const selected = params.get('s');
  const stamp = useRef('');

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    try {
      const o = await monitorApi.overview(signal);
      setOverview(o);
      setError(null);
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(e instanceof ApiError || e instanceof Error ? e.message : MONITOR_UNAVAILABLE);
    }
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    void loadOverview(ctl.signal);
    const t = setInterval(() => void loadOverview(), POLL_MS);
    return () => {
      ctl.abort();
      clearInterval(t);
    };
  }, [loadOverview]);

  const rows = useMemo(() => (overview ? overview.sessions.filter(TABS.find((t) => t.id === tab)!.match) : []), [overview, tab]);
  const select = useCallback((id: string) => setParams({ s: id }, { replace: true }), [setParams]);

  // 고른 대화가 없으면 첫 행을 고른다.
  useEffect(() => {
    if (!overview || !overview.sessions.length) return;
    if (!selected || !overview.sessions.some((r) => r.id === selected)) select(overview.sessions[0].id);
  }, [overview, selected, select]);

  // 고른 대화의 상세. 그 대화가 바뀌면(턴 추가·검토) 다시 받는다. 원문 열람 상태는 대화를 바꾸면 풀린다.
  const row = overview?.sessions.find((r) => r.id === selected);
  const rowStamp = row ? `${row.id}:${row.turns}:${row.last_active}:${row.review?.at ?? ''}` : '';
  useEffect(() => {
    if (!selected || !rowStamp) return;
    const sameSession = stamp.current.split(':')[0] === selected;
    if (stamp.current === rowStamp) return;
    stamp.current = rowStamp;
    if (sameSession && detail?.revealed) {
      // 열람한 상세는 새로 받지 않는다 (다시 가려지지 않게). 목록 행 정보(검토 표시 등)와 메시지만 바꾼다.
      setDetail((d) => (d && row ? { ...d, row } : d));
      monitorApi.thread(selected).then(
        (t) => setDetail((d) => (d && d.id === selected ? { ...d, row: t.row, messages: keepRevealed(d, t.messages) } : d)),
        () => undefined,
      );
      return;
    }
    const ctl = new AbortController();
    monitorApi.detail(selected, ctl.signal).then(
      (d) => {
        setDetail(d);
        setDetailError(null);
      },
      (e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setDetailError(e instanceof Error ? e.message : '상세를 불러오지 못했습니다.');
      },
    );
    return () => ctl.abort();
    // 상세는 rowStamp가 바뀔 때만 다시 받는다 (row·detail은 그 시점 값을 쓴다).
  }, [selected, rowStamp]); // eslint-disable-line react-hooks/exhaustive-deps

  // J/K로 목록 이동
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.metaKey || e.ctrlKey || revealOpen) return;
      if (e.key !== 'j' && e.key !== 'k') return;
      const i = rows.findIndex((r) => r.id === selected);
      const next = rows[Math.min(Math.max(i + (e.key === 'j' ? 1 : -1), 0), rows.length - 1)];
      if (next) select(next.id);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, selected, select, revealOpen]);

  async function review(action: ReviewAction, note?: string) {
    if (!selected) return false;
    setBusy(true);
    try {
      await monitorApi.review(selected, action, note);
      toast(REVIEW_TOAST[action]);
      await loadOverview();
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : '기록하지 못했습니다.');
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** 의료진에게 답장 또는 확인 요청. 확인 요청은 검토 표시(ask_clinician)와 함께 남는다. */
  async function message(kind: 'reply' | 'check_request', text: string, caseRef: string | null) {
    if (!selected) return false;
    const sid = selected;
    if (kind === 'check_request') {
      const ok = await review('ask_clinician', text);
      if (ok) monitorApi.thread(sid).then((t) => setDetail((d) => (d && d.id === sid ? { ...d, row: t.row, messages: keepRevealed(d, t.messages) } : d)), () => undefined);
      return ok;
    }
    try {
      const t = await monitorApi.message(sid, 'reply', text, caseRef);
      setDetail((d) => (d && d.id === sid ? { ...d, row: t.row, messages: keepRevealed(d, t.messages) } : d));
      toast('의료진에게 답장을 보냈습니다.');
      await loadOverview();
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : '답장을 보내지 못했습니다.');
      return false;
    }
  }

  if (error && !overview)
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState message={error} onRetry={() => void loadOverview()} />
        {error === MONITOR_UNAVAILABLE && (
          <p className="mt-2 text-center text-[13px] text-ink-3">저장소 루트에서 python -m webdemo 를 실행한 뒤 http://127.0.0.1:8000 으로 여세요.</p>
        )}
      </div>
    );
  if (!overview) return <LoadingState label="관제 목록을 불러오는 중" />;

  return (
    <div className="scroll-thin flex h-full min-h-0 flex-col overflow-y-auto lg:overflow-hidden">
      <Brief o={overview} />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 pb-4 md:px-6 md:pb-6 lg:grid-cols-[minmax(0,1fr)_minmax(420px,520px)]">
        <section className="panel flex min-h-[320px] flex-col overflow-hidden" aria-label="대화 목록">
          <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-2.5">
            {TABS.map((t) => {
              const n = overview.sessions.filter(t.match).length;
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={`inline-flex h-[30px] items-center gap-2 rounded-[8px] px-3 text-[13px] font-semibold ${tab === t.id ? 'bg-surface-2 text-ink' : 'text-ink-2 hover:text-ink'}`}
                >
                  {t.label}
                  <span className="num text-xs font-medium text-ink-3">{n}</span>
                </button>
              );
            })}
            <span className="ml-auto hidden items-center gap-1.5 text-xs text-ink-3 md:inline-flex">
              위험 높은 순 <span className="kbd">J</span>
              <span className="kbd">K</span> 이동
            </span>
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            {rows.length ? (
              <QueueTable rows={rows} selected={selected} onSelect={select} kReq={overview.k_req} pRef={overview.p_ref} />
            ) : (
              <EmptyState message={tab === 'review' ? '지금 확인할 대화가 없습니다.' : '이 조건에 맞는 대화가 없습니다.'} />
            )}
            {overview.simulations === 'running' && <p className="px-4 py-3 text-xs text-ink-3">레드팀 시뮬레이션 대화를 만드는 중입니다.</p>}
          </div>
        </section>

        <aside className="panel flex min-h-[480px] flex-col overflow-hidden" aria-label="대화 상세">
          {detailError ? (
            <ErrorState message={detailError} />
          ) : detail && detail.id === selected ? (
            <SessionDetail
              detail={detail}
              busy={busy}
              onReveal={() => setRevealOpen(true)}
              onReview={(a) => void review(a)}
              onMessage={message}
              onDetail={(d) => {
                setDetail(d);
                void loadOverview();
              }}
            />
          ) : (
            <LoadingState label="대화 상세를 불러오는 중" />
          )}
        </aside>
      </div>
      {revealOpen && detail && (
        <RevealDialog
          trialId={detail.trial_id}
          onCancel={() => setRevealOpen(false)}
          onConfirm={async (reason) => {
            const d = await monitorApi.reveal(detail.id, reason);
            setDetail(d);
            setRevealOpen(false);
            toast('열람 사유를 감사 기록에 남겼습니다.');
          }}
        />
      )}
    </div>
  );
}
