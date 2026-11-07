import { ArrowLeft, Info, LockKeyhole, Search, Stethoscope } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { emrApi } from '../api/emrApi';
import { ApiError } from '../api/types';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { BreakGlassDialog } from '../components/emr/BreakGlassDialog';
import { ChartSummary } from '../components/emr/ChartSummary';
import { SimilarCaseBox } from '../components/emr/SimilarCaseBox';
import { useToast } from '../components/layout/Toast';
import { koreanNames } from '../lib/koTerms';
import { timeLeft } from '../lib/time';
import { useWorkspace } from '../state/WorkspaceContext';
import type { EmrChart, EmrMe, WorklistPatient } from '../types/domain';

const SEX_KO = { male: '남', female: '여', unknown: '성별 미상' } as const;
type Status = WorklistPatient['status'];
type StatusTab = Status | 'ALL';
const TABS: { id: StatusTab; label: string }[] = [
  { id: 'ACTIVE', label: '진료 중' },
  { id: 'RESOLVED', label: '완치' },
  { id: 'DORMANT', label: '장기 미내원' },
  { id: 'ALL', label: '전체' },
];
const STATUS_TITLE: Record<Status, (open: number) => string> = {
  ACTIVE: (n) => `끝나지 않은 진단 · 관리 계획 ${n}건, 최근 3년 안에 기록이 있습니다`,
  RESOLVED: () => '기록된 진단과 관리 계획이 모두 끝났습니다',
  DORMANT: (n) => `끝나지 않은 진단 · 관리 계획 ${n}건이 있지만 마지막 기록이 3년보다 오래되었습니다`,
};

/** 성별 · 연령대 (생년 · 거주 지역은 보이지 않는다) */
function who(p: { sex: WorklistPatient['sex']; ageBand: string | null }): string {
  return [SEX_KO[p.sex], p.ageBand].filter(Boolean).join(' · ');
}

function StatusTag({ status, label, openItems }: { status: Status; label: string; openItems: number }) {
  // 점 하나로 상태를 구분한다: 진료 중(채운 초록) · 완치(채운 회색) · 장기 미내원(빈 원)
  const dot = status === 'ACTIVE' ? 'bg-safe' : status === 'RESOLVED' ? 'bg-ink-3' : 'border border-ink-3';
  return (
    <span title={STATUS_TITLE[status](openItems)} className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${status === 'ACTIVE' ? 'text-ink' : 'text-ink-3'}`}>
      <span aria-hidden className={`h-[7px] w-[7px] rounded-full ${dot}`} />
      {label}
    </span>
  );
}

function GlassTag({ expiresAt }: { expiresAt: number }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] bg-caution-tint px-1.5 py-px text-[10.5px] font-bold text-caution-text" title="담당이 아닌 환자를 사유를 적고 연 예외 열람입니다. 보안 담당자가 검토합니다.">
      <LockKeyhole className="h-3 w-3" aria-hidden />
      예외 열람 · {timeLeft(expiresAt)}
    </span>
  );
}

function PatientRow({ p, active, current }: { p: WorklistPatient; active: boolean; current: boolean }) {
  return (
    <li>
      <Link
        to={`/emr/${encodeURIComponent(p.fhirId)}`}
        aria-current={active ? 'page' : undefined}
        className={`block border-b border-line px-4 py-2.5 ${active ? 'bg-iris-tint shadow-[inset_3px_0_0_var(--zp-iris)]' : 'hover:bg-surface-2'}`}
      >
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[13px] font-semibold text-ink">{p.identifier}</span>
          {current && <span className="rounded-[5px] bg-iris px-1.5 py-px text-[10.5px] font-bold text-iris-on">AI 대화 중</span>}
          <span className="num ml-auto text-[11.5px] text-ink-3" title="마지막 기록">
            {p.lastRecord ?? '–'}
          </span>
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
          {who(p)}
          <StatusTag status={p.status} label={p.statusLabel} openItems={p.openItems} />
          {p.access === 'break_glass' && p.grant && <GlassTag expiresAt={p.grant.expiresAt} />}
        </span>
        <span className="mt-1 block truncate text-[12.5px] text-ink-2" title={p.conditions.join(', ')}>
          {p.conditions.slice(0, 2).join(', ') || '진단 기록 없음'}
        </span>
      </Link>
    </li>
  );
}

function ChartHeader({ chart, row, onBack }: { chart: EmrChart; row: WorklistPatient | null; onBack(): void }) {
  const p = chart.patient;
  const glass = chart.access?.via === 'break_glass' ? chart.access.grant : null;
  const facts: [string, string][] = [
    ['대표 진단', p.conditions.slice(0, 3).join(', ') || '없음'],
    ['진행 중', `진단 ${chart.problems.active} · 처방 ${chart.medications.active} · 관리 계획 ${chart.carePlans.active}`],
    ['마지막 기록', p.lastRecord ?? '–'],
    ['내원', `${chart.visitDays}일${chart.firstRecord ? ` (${chart.firstRecord.slice(0, 4)}년부터)` : ''}`],
  ];
  return (
    <header className="border-b border-line bg-emr-banner px-4 py-3 md:px-5">
      <button type="button" onClick={onBack} className="btn-ghost btn-sm -ml-2 mb-1 h-7 gap-1 text-ink-2 lg:hidden">
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />내 담당 환자
      </button>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="font-mono text-[19px] font-bold tracking-[-0.01em] text-ink">{p.identifier}</h2>
        <span className="text-[13px] text-ink-2">{who(p)}</span>
        <StatusTag status={p.status} label={p.statusLabel} openItems={p.openItems} />
        {glass ? (
          <GlassTag expiresAt={glass.expiresAt} />
        ) : (
          row?.access === 'assigned' && <span className="rounded-[5px] border border-line px-1.5 py-px text-[10.5px] font-semibold text-ink-3">담당</span>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2 2xl:flex 2xl:flex-wrap">
        {facts.map(([k, v]) => (
          <div key={k} className="flex min-w-0 items-baseline gap-2">
            <dt className="shrink-0 text-xs text-ink-3">{k}</dt>
            <dd className="min-w-0 truncate font-semibold text-ink" title={v}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
      {glass && (
        <p className="mt-2 text-xs leading-5 text-ink-2">
          {glass.reasonLabel}: {glass.note} · 이 열람은 감사 기록에 남고 보안 담당자가 검토합니다.
        </p>
      )}
    </header>
  );
}

/**
 * 내 담당 환자 (python -m medicloak): 로그인한 의료진의 담당 외래 환자 목록 → 차트 요약 → 유사 사례 찾기(진료 지원 AI).
 * 담당이 아닌 환자는 목록에 없고, 협진 · 당직처럼 꼭 봐야 할 때만 '담당 외 환자 열기'로 사유를 적고 연다 (ADR-0034).
 * 여기 나오는 환자는 외래 환자뿐이다. 진료 지원 AI가 찾아 줄 과거 사례의 기록은 EMR로 열 수 없다 (AI 답과 MediCloak 보호를 거쳐서만 보인다).
 */
export function EmrPage() {
  const { fhirId: picked = null } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { state } = useWorkspace();
  const currentTrial = state.patient.data?.trialId;
  const [list, setList] = useState<WorklistPatient[] | null>(null);
  const [me, setMe] = useState<EmrMe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<StatusTab>('ACTIVE');
  const [chart, setChart] = useState<{ id: string; data: EmrChart | null; error: ApiError | Error | null } | null>(null);
  const [glassOpen, setGlassOpen] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    emrApi.worklist(ctl.signal).then(
      (x) => {
        setList(x);
        setError(null);
      },
      (e) => !(e instanceof DOMException) && setError(e instanceof Error ? e.message : '담당 환자 목록을 불러오지 못했습니다.'),
    );
    emrApi.me(ctl.signal).then(setMe, () => undefined);
    return () => ctl.abort();
  }, [reload]);

  // 고른 환자의 차트 요약 (열면 서버가 접근 기록에 남긴다)
  useEffect(() => {
    if (!picked) {
      setChart(null);
      return;
    }
    const ctl = new AbortController();
    setChart({ id: picked, data: null, error: null });
    emrApi.chart(picked, ctl.signal).then(
      (data) => setChart((c) => (c && c.id === picked ? { ...c, data } : c)),
      (e) => !(e instanceof DOMException) && setChart((c) => (c && c.id === picked ? { ...c, error: e instanceof Error ? e : new Error(String(e)) } : c)),
    );
    return () => ctl.abort();
  }, [picked, reload]);

  const mine = useMemo(() => (list ?? []).filter((p) => p.access !== 'break_glass'), [list]);
  const glass = useMemo(() => (list ?? []).filter((p) => p.access === 'break_glass'), [list]);
  const counts = useMemo(() => {
    const n = (s: Status) => mine.filter((p) => p.status === s).length;
    return { ACTIVE: n('ACTIVE'), RESOLVED: n('RESOLVED'), DORMANT: n('DORMANT'), ALL: mine.length };
  }, [mine]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const inTab = tab === 'ALL' ? mine : mine.filter((p) => p.status === tab);
    if (!t) return inTab;
    // 진단 이름이 영어라 한국어 이름(기관지염 · 치은염 …)도 함께 찾는다
    return inTab.filter((p) =>
      [p.identifier, ...p.conditions, ...p.purposes.map((x) => `${x.mainDx ?? ''} ${x.item ?? ''} ${x.purposeLabel}`)].some((s) =>
        `${s} ${koreanNames(s)}`.toLowerCase().includes(t),
      ),
    );
  }, [mine, q, tab]);

  const row = list?.find((p) => p.fhirId === picked) ?? null;
  const isCurrent = (p: WorklistPatient) => p.purposes.some((x) => x.trialId === currentTrial);
  const breakGlass = me?.breakGlass.on ? me.breakGlass : null;
  const chartData = chart?.id === picked ? chart.data : null;
  const chartError = chart?.id === picked ? chart.error : null;

  function onOpened(fhirId: string, created: boolean) {
    setGlassOpen(false);
    toast(created ? `환자 ${fhirId.slice(0, 8)}를 예외 열람으로 열었습니다. 감사 기록에 남았습니다.` : `환자 ${fhirId.slice(0, 8)}는 이미 예외 열람 중입니다.`);
    setReload((n) => n + 1);
    navigate(`/emr/${encodeURIComponent(fhirId)}`);
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside aria-label="내 담당 환자" className={`${picked ? 'hidden lg:flex' : 'flex'} min-h-0 flex-col border-line bg-surface lg:border-r`}>
        <header className="border-b border-line px-4 pb-3 pt-3.5">
          <h2 className="flex items-baseline gap-2 text-[15px] font-bold text-ink">
            내 담당 환자
            {list && <span className="num text-[13px] font-semibold text-ink-3">{mine.length}명</span>}
          </h2>
          <label className="relative mt-2.5 block">
            <span className="sr-only">담당 환자 찾기</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="환자 번호, 진단(한글 · 영문), 처치"
              className="h-9 w-full rounded-control border border-line-input bg-surface pl-8 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
            />
          </label>
          <div role="tablist" aria-label="진료 상태" className="mt-2.5 grid grid-cols-4 gap-0.5 rounded-[9px] bg-surface-2 p-0.5">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                type="button"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                className={`flex h-[34px] flex-col items-center justify-center rounded-[7px] text-[11.5px] font-semibold leading-tight ${tab === t.id ? 'bg-surface text-ink shadow-sm ring-1 ring-line' : 'text-ink-3 hover:text-ink'}`}
              >
                <span className="whitespace-nowrap">{t.label}</span>
                <span className="num text-[10.5px] font-normal text-ink-3">{counts[t.id]}</span>
              </button>
            ))}
          </div>
        </header>
        {error ? (
          <ErrorState message={error} />
        ) : !list ? (
          <LoadingState label="담당 환자를 불러오는 중" />
        ) : (
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            {glass.length > 0 && (
              <section aria-label="예외 열람 중인 환자" className="border-b border-line">
                <h3 className="bg-caution-tint px-4 py-1.5 text-[11.5px] font-bold text-caution-text">담당 외 · 예외 열람 중</h3>
                <ul>
                  {glass.map((p) => (
                    <PatientRow key={p.fhirId} p={p} active={p.fhirId === picked} current={isCurrent(p)} />
                  ))}
                </ul>
              </section>
            )}
            {mine.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] leading-6 text-ink-3">
                아직 담당으로 배정된 환자가 없습니다.
                <br />
                병원 관리자에게 담당 배정을 요청하세요.
              </p>
            ) : shown.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] text-ink-3">맞는 환자가 없습니다.</p>
            ) : (
              <ul>
                {shown.map((p) => (
                  <PatientRow key={p.fhirId} p={p} active={p.fhirId === picked} current={isCurrent(p)} />
                ))}
              </ul>
            )}
          </div>
        )}
        <footer className="border-t border-line px-4 py-3">
          {breakGlass ? (
            <button type="button" className="btn-ghost btn-sm h-8 w-full justify-center gap-1.5 border border-line text-ink-2" onClick={() => setGlassOpen(true)}>
              <LockKeyhole className="h-3.5 w-3.5" aria-hidden />
              담당 외 환자 열기
            </button>
          ) : (
            me && <p className="text-xs leading-5 text-ink-3">이 병원 설정에서는 담당 환자만 열 수 있습니다.</p>
          )}
        </footer>
      </aside>

      <section aria-label="환자 차트" className={`${picked ? 'flex' : 'hidden lg:flex'} min-h-0 flex-col`}>
        {!picked ? (
          <div className="grid flex-1 place-items-center px-6 py-12 text-center">
            <div className="max-w-[360px]">
              <Stethoscope className="mx-auto h-7 w-7 text-ink-3" aria-hidden />
              <p className="mt-3 text-[14px] font-semibold text-ink">환자를 고르면 차트 요약이 나옵니다</p>
              <p className="mt-1.5 text-[13px] leading-6 text-ink-2">진단 이력, 처방, 시술, 관리 계획, 최근 내원을 본 뒤 필요하면 같은 화면에서 유사 사례를 찾습니다.</p>
              <p className="mt-4 flex items-start justify-center gap-1.5 text-left text-xs leading-5 text-ink-3">
                <Info className="mt-[3px] h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>비슷한 과거 사례는 이 목록에서 찾지 않습니다. 진료 지원 AI는 병원의 과거 기록 환자에서 찾고, 그 기록은 MediCloak을 거쳐서만 보입니다.</span>
              </p>
            </div>
          </div>
        ) : chartError ? (
          <div className="flex flex-1 flex-col">
            <div className="px-4 pt-3 lg:hidden">
              <button type="button" onClick={() => navigate('/emr')} className="btn-ghost btn-sm -ml-2 h-7 gap-1 text-ink-2">
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />내 담당 환자
              </button>
            </div>
            <ErrorState message={chartError.message} />
            {chartError instanceof ApiError && chartError.status === 403 && breakGlass && (
              <div className="flex justify-center pb-8">
                <button type="button" className="btn-ghost btn-sm gap-1.5 border border-line" onClick={() => setGlassOpen(true)}>
                  <LockKeyhole className="h-3.5 w-3.5" aria-hidden />
                  담당 외 환자 열기
                </button>
              </div>
            )}
          </div>
        ) : !chartData ? (
          <LoadingState label="차트를 불러오는 중" />
        ) : (
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            <ChartHeader chart={chartData} row={row} onBack={() => navigate('/emr')} />
            <div className="grid grid-cols-1 gap-4 p-4 md:px-5 xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start">
              <div className="xl:sticky xl:top-4 xl:order-2">
                <SimilarCaseBox fhirId={chartData.patient.fhirId} identifier={chartData.patient.identifier} purposes={chartData.purposes ?? row?.purposes ?? []} />
              </div>
              <div className="min-w-0 xl:order-1">
                <ChartSummary chart={chartData} />
                <p className="mt-3 text-xs leading-5 text-ink-3">차트는 병원 EMR(가상 EMR)의 진료 기록에서 만든 요약입니다. 연 일은 접근 기록에 남습니다.</p>
              </div>
            </div>
          </div>
        )}
      </section>
      {glassOpen && breakGlass && <BreakGlassDialog policy={breakGlass} onCancel={() => setGlassOpen(false)} onOpened={onOpened} />}
    </div>
  );
}
