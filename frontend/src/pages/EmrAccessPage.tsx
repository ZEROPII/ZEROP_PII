import { Check, Eye, Flag, LockKeyhole, Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MONITOR_UNAVAILABLE, monitorApi } from '../api/monitorApi';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { ChartSummary } from '../components/emr/ChartSummary';
import { useToast } from '../components/layout/Toast';
import { RevealDialog } from '../components/monitor/RevealDialog';
import { dateTime, relativeTime, timeLeft } from '../lib/time';
import type { EmrAccessEvent, EmrAccessOverview, EmrAccessPatient, EmrGrantRecord, EmrRevealResult, EmrTeamMember } from '../types/monitor';

type Tab = 'patients' | 'grants';
type Filter = 'all' | 'pending' | 'denied' | 'unassigned';
const FILTERS: { id: Filter; label: string; match(p: EmrAccessOverview['patients'][number]): boolean }[] = [
  { id: 'all', label: '전체', match: () => true },
  { id: 'pending', label: '검토 대기', match: (p) => p.pendingReview > 0 },
  { id: 'denied', label: '담당 외 거부', match: (p) => p.denied > 0 },
  { id: 'unassigned', label: '담당 없음', match: (p) => p.team.length === 0 },
];
const CHART_REASONS = ['예외 열람 검토', '접근 기록 확인', '의료진 문의 대응', '기타'];
const DENIED_KO: Record<string, string> = { chart: '차트 열기', launch: '진료 지원 AI 열기', prefetch: '첫 답 미리 준비', visits: '오늘 볼 진단', fhir: 'EMR 연동(FHIR) 조회' };
const STATUS_DOT: Record<string, string> = { ACTIVE: 'bg-safe', RESOLVED: 'bg-ink-3', DORMANT: 'border border-ink-3' };

function teamText(team: EmrTeamMember[]): string {
  return team.map((t) => t.displayName).join(', ') || '없음';
}

function Status({ status, label }: { status: string | null; label: string | null }) {
  if (!status) return null;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-2">
      <span aria-hidden className={`h-[7px] w-[7px] rounded-full ${STATUS_DOT[status] ?? 'bg-ink-3'}`} />
      {label}
    </span>
  );
}

/** 한 줄 요약 (관제 화면과 같은 꼴): 지금 할 일을 먼저 */
function Brief({ o }: { o: EmrAccessOverview }) {
  const k = o.kpi;
  let text;
  if (k.pendingReview > 0)
    text = (
      <>
        담당 외 환자 예외 열람 <em className="not-italic text-iris-text">{k.pendingReview}건</em>이 검토를 기다립니다. 적은 사유가 진료에 맞는지 확인하세요.
      </>
    );
  else if (k.denied7d > 0)
    text = (
      <>
        최근 {o.windowDays}일 동안 담당이 아닌 환자를 열려다 막힌 일이 <em className="not-italic text-danger-text">{k.denied7d}건</em> 있습니다. 누가 왜 열려고 했는지 확인해 보세요.
      </>
    );
  else if (k.unassigned > 0)
    text = (
      <>
        담당 의료진이 없는 외래 환자가 <em className="not-italic text-danger-text">{k.unassigned}명</em> 있습니다. 담당을 배정하세요.
      </>
    );
  else text = <>모든 외래 환자에 담당 의료진이 있고, 검토할 예외 열람은 없습니다.</>;
  const stats: [string, string, string, boolean][] = [
    ['외래 환자', `${k.outpatients}명`, '가상 EMR의 외래 환자 (유사 사례 검색 대상인 과거 기록 환자는 EMR로 열 수 없어 세지 않습니다)', false],
    ['담당 없음', `${k.unassigned}명`, '담당 의료진이 없는 외래 환자. 예외 열람으로만 열립니다', k.unassigned > 0],
    ['24시간 차트 열람', `${k.charts24h}건`, '의료진이 차트 요약 · EMR 연동(FHIR)으로 환자 기록을 연 횟수', false],
    [`${o.windowDays}일 예외 열람`, `${k.breakGlass7d}건`, '담당이 아닌 환자를 사유를 적고 연 횟수', false],
    [`${o.windowDays}일 담당 외 거부`, `${k.denied7d}건`, '담당이 아닌 환자를 열려다 막힌 횟수', k.denied7d > 0],
    [`${o.windowDays}일 보안 담당자 열람`, `${k.reveals7d}건`, '보안 담당자가 사유를 적고 차트를 연 횟수', false],
  ];
  return (
    <section className="grid gap-5 px-4 pb-4 pt-5 md:px-6 xl:grid-cols-[1fr_auto] xl:items-end">
      <p className="max-w-[30em] text-[21px] font-bold leading-[1.42] tracking-[-0.025em] md:text-2xl">{text}</p>
      <dl className="grid grid-cols-[auto_auto] gap-x-5 gap-y-1 text-[13px] sm:grid-cols-[auto_auto_auto_auto]" aria-label="EMR 접근 집계">
        {stats.map(([l, v, help, alarm]) => (
          <div key={l} className="contents" title={help}>
            <dt className="text-ink-3">{l}</dt>
            <dd className={`num text-right font-semibold ${alarm ? 'text-danger-text' : 'text-ink'}`}>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function LastAccess({ e }: { e: EmrAccessEvent | null }) {
  if (!e) return <span className="text-ink-3">–</span>;
  return (
    <span className="block min-w-0">
      <span className={`block truncate ${e.action === 'denied' ? 'text-danger-text' : 'text-ink'}`}>
        {e.displayName ?? '알 수 없음'} · {e.actionLabel}
      </span>
      <span className="num block text-[11.5px] text-ink-3" title={dateTime(e.at)}>
        {relativeTime(e.at)}
      </span>
    </span>
  );
}

function GrantCard({ g, onReviewed, showTag = false, onSelect }: { g: EmrGrantRecord; onReviewed(g: EmrGrantRecord): void; showTag?: boolean; onSelect?(): void }) {
  const toast = useToast();
  const [flagging, setFlagging] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function review(action: 'ok' | 'flag') {
    setBusy(true);
    setError(null);
    try {
      const r = await monitorApi.reviewGrant(g.id, action, action === 'flag' ? note.trim() : undefined);
      toast(action === 'ok' ? '적절한 열람으로 검토했습니다.' : '확인 필요로 표시하고 열람을 끝냈습니다.');
      setFlagging(false);
      onReviewed(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : '검토를 남기지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  const state = g.endedAt && !g.active ? (g.review === 'flag' ? '열람 끝냄' : '끝남') : g.active ? timeLeft(g.expiresAt) : '끝남';
  return (
    <li className="rounded-control border border-line bg-surface px-3.5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {showTag && (
          <button type="button" onClick={onSelect} className="font-mono text-[13px] font-semibold text-iris-text hover:underline">
            {g.tag}
          </button>
        )}
        <span className="text-[13px] font-semibold text-ink">
          {g.displayName}
          {g.department && <span className="ml-1 font-normal text-ink-3">{g.department}</span>}
        </span>
        <span className="rounded-[5px] bg-caution-tint px-1.5 py-px text-[11px] font-bold text-caution-text">{g.reasonLabel}</span>
        <span className="num ml-auto text-[11.5px] text-ink-3" title={`연 시각 ${dateTime(g.createdAt)} · 끝나는 시각 ${dateTime(g.expiresAt)}`}>
          {dateTime(g.createdAt)} · {state}
        </span>
      </div>
      {g.note && <p className="mt-1 text-[13px] leading-6 text-ink-2">{g.note}</p>}
      {g.review ? (
        <p className={`mt-1.5 text-xs leading-5 ${g.review === 'flag' ? 'text-danger-text' : 'text-ink-3'}`}>
          {g.reviewLabel}
          {g.reviewNote ? `: ${g.reviewNote}` : ''} · {g.reviewedBy}
          {g.reviewedAt ? ` · ${dateTime(g.reviewedAt)}` : ''}
        </p>
      ) : flagging ? (
        <div className="mt-2">
          <label htmlFor={`flag-${g.id}`} className="text-xs font-semibold text-ink-2">
            확인이 필요한 까닭
          </label>
          <textarea
            id={`flag-${g.id}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={300}
            placeholder="예: 협진 의뢰 기록이 없어 의료진에게 확인"
            className="mt-1 w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-[13px] leading-6 outline-none focus:border-focus"
          />
          <div className="mt-1.5 flex gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || note.trim().length < 5} onClick={() => void review('flag')}>
              <Flag className="h-3.5 w-3.5" aria-hidden />
              확인 필요로 남기고 열람 끝내기
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setFlagging(false)}>
              취소
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          <button type="button" className="btn-ghost btn-sm border border-line" disabled={busy} onClick={() => void review('ok')}>
            <Check className="h-3.5 w-3.5" aria-hidden />
            적절함
          </button>
          <button type="button" className="btn-ghost btn-sm border border-line text-danger-text" disabled={busy} onClick={() => setFlagging(true)}>
            <Flag className="h-3.5 w-3.5" aria-hidden />
            확인 필요
          </button>
        </div>
      )}
      {error && <p className="mt-1.5 text-xs text-danger-text">{error}</p>}
    </li>
  );
}

function PatientDetail({ tag, onChanged }: { tag: string; onChanged(): void }) {
  const toast = useToast();
  const [d, setD] = useState<EmrAccessPatient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revealOpen, setRevealOpen] = useState(false);
  const [revealed, setRevealed] = useState<EmrRevealResult | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) =>
      monitorApi.emrPatient(tag, signal).then(
        (x) => (setD(x), setError(null)),
        (e) => !(e instanceof DOMException) && setError(e instanceof Error ? e.message : '접근 기록을 불러오지 못했습니다.'),
      ),
    [tag],
  );
  useEffect(() => {
    setD(null);
    setRevealed(null);
    const ctl = new AbortController();
    void load(ctl.signal);
    const t = window.setInterval(() => void load(), 8000);
    return () => {
      ctl.abort();
      window.clearInterval(t);
    };
  }, [load]);

  if (error) return <ErrorState message={error} />;
  if (!d) return <LoadingState label="접근 기록을 불러오는 중" />;
  const view = revealed ?? d;
  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      <header className="border-b border-line px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="font-mono text-[17px] font-bold text-ink">{tag}</h2>
          <Status status={d.status} label={d.statusLabel} />
          {revealed && (
            <span className="rounded-[5px] bg-iris-tint px-1.5 py-px text-[11.5px] font-semibold text-iris-text">
              환자 번호 <span className="font-mono">{revealed.identifier}</span>
            </span>
          )}
        </div>
        <p className="mt-1 text-[13px] text-ink-2">
          담당: {d.team.length ? d.team.map((t) => `${t.displayName}${t.department ? ` (${t.department})` : ''}`).join(', ') : '없음'}
        </p>
        {!revealed ? (
          <button type="button" className="btn-primary btn-sm mt-2.5" onClick={() => setRevealOpen(true)}>
            <Eye className="h-3.5 w-3.5" aria-hidden />
            사유 적고 차트 보기
          </button>
        ) : (
          <button type="button" className="btn-ghost btn-sm mt-2.5 border border-line" onClick={() => setRevealed(null)}>
            <X className="h-3.5 w-3.5" aria-hidden />
            차트 닫기
          </button>
        )}
      </header>
      {revealed && (
        <section aria-label="차트 요약" className="border-b border-line bg-surface-2 px-4 py-3.5">
          <p className="mb-2.5 text-xs leading-5 text-ink-3">사유를 적고 연 차트입니다. 이 열람은 감사 기록에 남았습니다.</p>
          <ChartSummary chart={revealed.chart} wide={false} />
        </section>
      )}
      <section aria-label="예외 열람" className="border-b border-line px-4 py-3.5">
        <h3 className="text-[13px] font-bold text-ink">예외 열람 {view.grants.length > 0 && <span className="num font-normal text-ink-3">{view.grants.length}건</span>}</h3>
        {view.grants.length === 0 ? (
          <p className="mt-1.5 text-[13px] text-ink-3">담당이 아닌 의료진이 연 기록이 없습니다.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {view.grants.map((g) => (
              <GrantCard
                key={g.id}
                g={g}
                onReviewed={() => {
                  void load();
                  setRevealed(null);
                  onChanged();
                }}
              />
            ))}
          </ul>
        )}
      </section>
      <section aria-label="접근 기록" className="px-4 py-3.5">
        <h3 className="text-[13px] font-bold text-ink">접근 기록</h3>
        {view.history.length === 0 ? (
          <p className="mt-1.5 text-[13px] text-ink-3">아직 이 환자의 차트를 연 사람이 없습니다.</p>
        ) : (
          <ol className="mt-2 space-y-0">
            {view.history.map((h, i) => (
              <li key={`${h.at}-${i}`} className="grid grid-cols-[76px_minmax(0,1fr)] gap-2 border-b border-line py-2 last:border-b-0">
                <span className="num text-[11.5px] text-ink-3" title={dateTime(h.at)}>
                  {dateTime(h.at)}
                </span>
                <span className="min-w-0 text-[13px]">
                  <span className={`font-semibold ${h.action === 'denied' ? 'text-danger-text' : 'text-ink'}`}>{h.actionLabel}</span>
                  <span className="text-ink-2">
                    {' '}
                    · {h.displayName ?? '알 수 없음'}
                    {h.viaLabel && h.action !== 'reveal' ? ` (${h.viaLabel})` : ''}
                  </span>
                  {h.detail && <span className="block truncate text-xs text-ink-3" title={h.detail}>{h.action === 'denied' ? `막은 요청: ${DENIED_KO[h.detail] ?? h.detail}` : h.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
      {revealOpen && (
        <RevealDialog
          trialId={tag}
          title={
            <>
              <span className="font-mono">{tag}</span> 차트 보기
            </>
          }
          description="환자 번호와 차트 요약(진단 · 처방 · 시술 · 관리 계획 · 내원)이 보입니다. 사유를 고르고 무엇을 확인하려는지 적어야 열리며, 이름 · 시간과 함께 감사 기록에 남습니다."
          reasons={CHART_REASONS}
          placeholder="예: 협진 사유와 차트 내용 대조"
          onCancel={() => setRevealOpen(false)}
          onConfirm={async (reason, note) => {
            const r = await monitorApi.emrReveal(tag, reason, note);
            setRevealed(r);
            setRevealOpen(false);
            toast('차트를 열었습니다. 감사 기록에 남았습니다.');
            onChanged();                                    // 목록의 마지막 접근 · 열람 수를 바로 고친다
          }}
        />
      )}
    </div>
  );
}

function Assignment({ o }: { o: EmrAccessOverview }) {
  return (
    <div className="px-5 py-8">
      <EmptyState message="왼쪽에서 환자를 고르면 담당 · 예외 열람 · 접근 기록이 여기에 나옵니다. 차트는 사유를 적어야 열립니다." />
      <section aria-label="담당 배정" className="mx-auto mt-2 max-w-[340px] rounded-control border border-line px-4 py-3">
        <h3 className="text-[13px] font-bold text-ink">담당 배정</h3>
        <ul className="mt-1.5 space-y-1 text-[13px]">
          {o.clinicians.map((c) => (
            <li key={c.username} className="flex items-baseline gap-2">
              <span className="text-ink">{c.displayName}</span>
              <span className="text-xs text-ink-3">{c.department}</span>
              <span className="num ml-auto font-semibold text-ink">{c.assigned}명</span>
            </li>
          ))}
        </ul>
        <p className="mt-2.5 text-xs leading-5 text-ink-3">
          예외 열람 {o.breakGlass ? `켬 (사유를 적고 ${o.grantHours}시간)` : '끔 (담당 환자만)'}. 담당을 바꾸려면 서버에서{' '}
          <code className="font-mono text-[11.5px] text-ink-2">python -m medicloak assign</code>을 씁니다.
        </p>
      </section>
    </div>
  );
}

/**
 * EMR 접근 관리 (보안 담당자, 운영 모드): 외래 환자마다 담당 · 마지막 접근 · 예외 열람을 기호(P-xxxxxx)로만 본다.
 * 진단 · 나이 · 환자 번호는 보이지 않고, 차트는 사유를 적은 열람 때만 열린다 (ADR-0034). 예외 열람은 여기서 사후 검토한다.
 */
export function EmrAccessPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('p');
  const [o, setO] = useState<EmrAccessOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('patients');
  const [filter, setFilter] = useState<Filter>('all');
  const [q, setQ] = useState('');

  const load = useCallback(
    (signal?: AbortSignal) =>
      monitorApi.emrAccess(signal).then(
        (x) => (setO(x), setError(null)),
        (e) => !(e instanceof DOMException) && setError(e instanceof Error ? e.message : MONITOR_UNAVAILABLE),
      ),
    [],
  );
  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    const t = window.setInterval(() => void load(), 8000);
    return () => {
      ctl.abort();
      window.clearInterval(t);
    };
  }, [load]);

  const select = (tag: string) => setParams({ p: tag }, { replace: true });
  const rows = useMemo(() => {
    if (!o) return [];
    const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
    const t = q.trim().toLowerCase();
    return o.patients.filter((p) => f.match(p) && (!t || `${p.tag} ${teamText(p.team)}`.toLowerCase().includes(t)));
  }, [o, filter, q]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!o) return <LoadingState label="EMR 접근 기록을 불러오는 중" />;
  const pendingGrants = o.grants.filter((g) => !g.review).length;

  return (
    <div className="scroll-thin flex h-full min-h-0 flex-col overflow-y-auto lg:overflow-hidden">
      <Brief o={o} />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 pb-4 md:px-6 md:pb-6 lg:grid-cols-[minmax(0,1fr)_minmax(400px,480px)]">
        <section className="panel flex min-h-[320px] flex-col overflow-hidden" aria-label="외래 환자 접근">
          <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-2.5">
            {(
              [
                ['patients', '외래 환자', o.patients.length],
                ['grants', '예외 열람', o.grants.length],
              ] as const
            ).map(([id, label, n]) => (
              <button
                key={id}
                type="button"
                aria-pressed={tab === id}
                onClick={() => setTab(id)}
                className={`inline-flex h-[30px] items-center gap-2 rounded-[8px] px-3 text-[13px] font-semibold ${tab === id ? 'bg-surface-2 text-ink' : 'text-ink-2 hover:text-ink'}`}
              >
                {label}
                <span className={`num text-xs font-medium ${id === 'grants' && pendingGrants ? 'text-iris-text' : 'text-ink-3'}`}>
                  {id === 'grants' && pendingGrants ? `검토 대기 ${pendingGrants}` : n}
                </span>
              </button>
            ))}
            {tab === 'patients' && (
              <label className="relative ml-auto w-full sm:w-[200px]">
                <span className="sr-only">기호 · 담당 의료진으로 찾기</span>
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="기호, 담당 의료진"
                  className="h-8 w-full rounded-control border border-line-input bg-surface pl-7 pr-2 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
                />
              </label>
            )}
          </div>
          {tab === 'patients' ? (
            <>
              <div className="flex flex-wrap gap-1.5 border-b border-line px-3 py-2">
                {FILTERS.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={filter === f.id}
                    onClick={() => setFilter(f.id)}
                    className={`h-[26px] rounded-full border px-2.5 text-xs ${filter === f.id ? 'border-iris bg-iris-tint font-semibold text-iris-text' : 'border-line text-ink-2'}`}
                  >
                    {f.label} <span className="num text-ink-3">{o.patients.filter(f.match).length}</span>
                  </button>
                ))}
              </div>
              <div className="scroll-thin min-h-0 flex-1 overflow-auto">
                {rows.length === 0 ? (
                  <EmptyState message="이 조건에 맞는 환자가 없습니다." />
                ) : (
                  <table className="w-full min-w-[560px] border-collapse text-[13px]">
                    <thead className="bg-page lg:sticky lg:top-0 lg:z-[1]">
                      <tr className="text-left text-xs text-ink-3">
                        <th className="border-b border-line px-4 py-2 font-semibold">환자 기호</th>
                        <th className="border-b border-line px-3 py-2 font-semibold">진료 상태</th>
                        <th className="border-b border-line px-3 py-2 font-semibold">담당</th>
                        <th className="border-b border-line px-3 py-2 font-semibold">마지막 접근</th>
                        <th className="border-b border-line px-3 py-2 text-right font-semibold">{o.windowDays}일 접근</th>
                        <th className="border-b border-line px-3 py-2 text-right font-semibold">예외 열람</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((p) => {
                        const on = p.tag === selected;
                        return (
                          <tr key={p.tag} onClick={() => select(p.tag)} aria-selected={on} className={`cursor-pointer ${on ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}>
                            <td className={`border-b border-line px-4 py-2.5 align-top ${on ? 'shadow-[inset_3px_0_0_var(--zp-iris)]' : ''}`}>
                              <button type="button" onClick={() => select(p.tag)} className="font-mono font-semibold text-ink">
                                {p.tag}
                              </button>
                            </td>
                            <td className="border-b border-line px-3 py-2.5 align-top">
                              <Status status={p.status} label={p.statusLabel} />
                            </td>
                            <td className={`border-b border-line px-3 py-2.5 align-top ${p.team.length ? 'text-ink-2' : 'text-danger-text'}`}>{teamText(p.team)}</td>
                            <td className="max-w-[220px] border-b border-line px-3 py-2.5 align-top">
                              <LastAccess e={p.lastAccess} />
                            </td>
                            <td className="num border-b border-line px-3 py-2.5 text-right align-top text-ink-2">
                              {p.recent}
                              {p.denied > 0 && <span className="block text-[11.5px] text-danger-text">거부 {p.denied}</span>}
                            </td>
                            <td className="num border-b border-line px-3 py-2.5 text-right align-top">
                              {p.breakGlass > 0 ? (
                                <span className={p.pendingReview ? 'font-semibold text-iris-text' : 'text-ink-2'}>
                                  {p.breakGlass}
                                  {p.pendingReview > 0 && <span className="block text-[11.5px]">검토 대기 {p.pendingReview}</span>}
                                </span>
                              ) : (
                                <span className="text-ink-3">–</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          ) : (
            <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 py-3">
              {o.grants.length === 0 ? (
                <EmptyState message={o.breakGlass ? '아직 담당 외 환자를 연 기록이 없습니다.' : '이 서버는 예외 열람을 껐습니다 (--break-glass off). 의료진은 담당 환자만 엽니다.'} />
              ) : (
                <ul className="space-y-2">
                  {o.grants.map((g) => (
                    <GrantCard key={g.id} g={g} showTag onSelect={() => select(g.tag)} onReviewed={() => void load()} />
                  ))}
                </ul>
              )}
            </div>
          )}
          <p className="flex items-center gap-1.5 border-t border-line px-4 py-2 text-xs text-ink-3">
            <LockKeyhole className="h-3.5 w-3.5 shrink-0" aria-hidden />
            환자는 기호로만 보입니다. 진단 · 나이 · 환자 번호는 사유를 적고 차트를 열 때만 보입니다.
          </p>
        </section>

        <aside className="panel flex min-h-[480px] flex-col overflow-hidden" aria-label="고른 환자">
          {selected && o.patients.some((p) => p.tag === selected) ? (
            <PatientDetail key={selected} tag={selected} onChanged={() => void load()} />
          ) : (
            <Assignment o={o} />
          )}
        </aside>
      </div>
    </div>
  );
}
