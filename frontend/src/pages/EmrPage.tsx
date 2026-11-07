import { ArrowDownUp, ArrowLeft, Info, LockKeyhole, Search, Send, Stethoscope, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { emrApi } from '../api/emrApi';
import { ApiError } from '../api/types';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { BreakGlassDialog } from '../components/emr/BreakGlassDialog';
import { ChartSummary } from '../components/emr/ChartSummary';
import { ConsultDialog } from '../components/emr/ConsultDialog';
import { SimilarCaseBox } from '../components/emr/SimilarCaseBox';
import { useToast } from '../components/layout/Toast';
import { TRI, TRI_KO, type TriageLevel } from '../lib/kindStyle';
import { koreanNames } from '../lib/koTerms';
import { dateTime, sinceDay, timeLeft } from '../lib/time';
import { useWorkspace } from '../state/WorkspaceContext';
import type { EmrChart, EmrConsult, EmrMe, PatientRisk, WorklistPatient } from '../types/domain';

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
  ACTIVE: (n) => `진행 중인 진단 · 처방 · 관리 계획 ${n}건, 최근 3년 안에 내원했습니다`,
  RESOLVED: () => '진행 중인 진단 · 처방 · 관리 계획이 없습니다',
  DORMANT: (n) => `진행 중인 진단 · 처방 · 관리 계획 ${n}건이 있지만 마지막 내원이 3년보다 오래되었습니다`,
};

/**
 * 성별 · 연령대 (생년 · 거주 지역은 보이지 않는다). 연령대는 마지막 내원 때 나이라, 장기 미내원 환자는 그 해를 같이 적는다
 * ('40대(1970년 기준)'). 오래전 기록의 나이를 지금 나이로 읽지 않게.
 */
function who(p: { sex: WorklistPatient['sex']; ageBand: string | null; ageYear?: number | null; status?: Status }): string {
  const age = p.ageBand && p.status === 'DORMANT' && p.ageYear ? `${p.ageBand}(${p.ageYear}년 기준)` : p.ageBand;
  return [SEX_KO[p.sex], age].filter(Boolean).join(' · ');
}

const LEVELS: TriageLevel[] = [1, 2, 3, 4, 5];
const RISK_NOTE = '기록 기반 참고 등급이며 임상 판단을 대신하지 않습니다';
const riskTitle = (r: PatientRisk) => `환자 위험 등급 ${r.level} ${r.label}: ${r.reasons.join(' · ')}. ${RISK_NOTE}.`;

/** 목록 줄 왼쪽의 위험 등급 칸: 응급실 분류판처럼 등급 숫자와 이름을 색 칸에 */
function RiskTile({ risk }: { risk?: PatientRisk }) {
  if (!risk) return <span aria-hidden className="w-[34px]" />;
  return (
    <span className={`flex h-[44px] w-[34px] flex-col items-center justify-center rounded-[7px] ${TRI[risk.level].badge}`} title={riskTitle(risk)}>
      <span className="sr-only">위험 등급 </span>
      <span className="num text-[15px] font-extrabold leading-none">{risk.level}</span>
      <span className="mt-1 text-[10px] font-bold leading-none">{risk.label}</span>
    </span>
  );
}

/** 다섯 등급 띠: 지금 등급만 진하게 (어느 쪽 끝에 가까운지 한눈에) */
function RiskScale({ level }: { level: TriageLevel }) {
  return (
    <span aria-hidden className="inline-flex items-center gap-[3px]">
      {LEVELS.map((l) => (
        <span key={l} className={`rounded-[2px] ${TRI[l].bar} ${l === level ? 'h-3 w-[18px]' : 'h-2 w-3 opacity-30'}`} />
      ))}
    </span>
  );
}

/** 차트 머리의 위험 등급 줄: 등급 · 까닭 · 참고 문구 */
function RiskLine({ risk }: { risk: PatientRisk }) {
  const t = TRI[risk.level];
  return (
    <div className={`mt-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-[8px] px-2.5 py-1.5 ${t.tint}`}>
      <span className={`text-xs font-bold ${t.text}`}>환자 위험 등급</span>
      <span className={`inline-flex h-6 items-center gap-1 rounded-[6px] px-2 text-[12.5px] font-bold ${t.badge}`}>
        <span className="num">{risk.level}</span>
        {risk.label}
      </span>
      <RiskScale level={risk.level} />
      <span className="min-w-0 flex-1 basis-[240px] text-[12.5px] leading-5 text-ink">{risk.reasons.join(' · ')}</span>
      <span className="text-[11px] leading-4 text-ink-2">{RISK_NOTE}</span>
    </div>
  );
}

/** 목록 · 차트에 보이는 환자 번호: 등록번호 (없으면 예전처럼 환자 번호 앞 8자리) */
function numberOf(p: { regno?: string | null; identifier: string }): string {
  return p.regno ?? p.identifier;
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

function ConsultTag({ expiresAt }: { expiresAt: number }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] bg-iris-tint px-1.5 py-px text-[10.5px] font-bold text-iris-text" title="담당 의료진이 보낸 협진 의뢰로 연 환자입니다. 감사 기록에 남고 보안 담당자가 검토합니다.">
      <Users className="h-3 w-3" aria-hidden />
      협진 · {timeLeft(expiresAt)}
    </span>
  );
}

function AccessTag({ p }: { p: Pick<WorklistPatient, 'access' | 'grant'> }) {
  if (p.access === 'consult' && p.grant) return <ConsultTag expiresAt={p.grant.expiresAt} />;
  if (p.access === 'break_glass' && p.grant) return <GlassTag expiresAt={p.grant.expiresAt} />;
  return null;
}

/** 받은 협진 의뢰: 목록 맨 위. '열기'를 누르면 번호를 적지 않고 연다 (사유는 의뢰 내용). */
function ConsultInbox({ items, onOpen, onDecline }: { items: EmrConsult[]; onOpen(c: EmrConsult): void; onDecline(c: EmrConsult): void }) {
  const [asking, setAsking] = useState<number | null>(null);
  return (
    <section aria-label="받은 협진 의뢰" className="border-b border-line">
      <h3 className="flex items-center gap-1.5 bg-iris-tint px-4 py-1.5 text-[11.5px] font-bold text-iris-text">
        <Send className="h-3 w-3" aria-hidden />
        받은 협진 의뢰 {items.length}건
      </h3>
      <ul className="divide-y divide-line">
        {items.map((c) => (
          <li key={c.id} className="px-4 py-2.5">
            <p className="flex items-baseline gap-2">
              <span className="num text-[13px] font-semibold text-ink">{c.regno ?? '등록번호 없음'}</span>
              <span className="text-xs text-ink-3">{who({ sex: c.sex ?? 'unknown', ageBand: c.ageBand ?? null })}</span>
              <span className="num ml-auto text-[11px] text-ink-3" title="보낸 시각">
                {dateTime(c.createdAt)}
              </span>
            </p>
            <p className="mt-0.5 text-xs text-ink-2">
              {c.sender.displayName}
              {c.sender.department ? `(${c.sender.department})` : ''} 선생님이 보냄{c.status === 'opened' ? ' · 연 적 있음' : ''}
            </p>
            <p className="mt-1 line-clamp-2 text-[12.5px] leading-5 text-ink" title={c.note}>
              {c.note}
            </p>
            {asking === c.id ? (
              <div className="mt-2 rounded-control bg-surface-2 px-2.5 py-2 text-xs text-ink-2">
                보낸 의료진에게 거절로 보입니다.
                <span className="mt-1.5 flex gap-1.5">
                  <button type="button" className="btn-primary btn-sm h-7" onClick={() => onDecline(c)}>
                    거절하기
                  </button>
                  <button type="button" className="btn-ghost btn-sm h-7" onClick={() => setAsking(null)}>
                    취소
                  </button>
                </span>
              </div>
            ) : (
              <div className="mt-2 flex gap-1.5">
                <button type="button" className="btn-primary btn-sm h-7" onClick={() => onOpen(c)}>
                  {c.status === 'opened' ? '다시 열기' : '열기'}
                </button>
                {c.status === 'pending' && (
                  <button type="button" className="btn-ghost btn-sm h-7 text-ink-2" onClick={() => setAsking(c.id)}>
                    거절
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function PatientRow({ p, active, current }: { p: WorklistPatient; active: boolean; current: boolean }) {
  return (
    <li>
      <Link
        to={`/emr/${encodeURIComponent(p.fhirId)}`}
        aria-current={active ? 'page' : undefined}
        className={`grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 border-b border-line py-2.5 pl-3 pr-4 ${active ? 'bg-iris-tint shadow-[inset_3px_0_0_var(--zp-iris)]' : 'hover:bg-surface-2'}`}
      >
        <RiskTile risk={p.risk} />
        <span className="min-w-0">
          <span className="flex items-baseline gap-2">
            <span className="num text-[13px] font-semibold text-ink" title={p.regno ? '등록번호' : '환자 번호'}>
              {numberOf(p)}
            </span>
            {current && <span className="rounded-[5px] bg-iris px-1.5 py-px text-[10.5px] font-bold text-iris-on">AI 대화 중</span>}
            <span className="num ml-auto text-[11.5px] text-ink-3" title="마지막 내원">
              {p.lastRecord ?? '–'}
            </span>
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
            {who(p)}
            <StatusTag status={p.status} label={p.statusLabel} openItems={p.openItems} />
            <AccessTag p={p} />
          </span>
          <span className="mt-1 block truncate text-[12.5px] text-ink-2" title={p.conditions.join(', ')}>
            {p.conditions.slice(0, 2).join(', ') || '진단 기록 없음'}
          </span>
        </span>
      </Link>
    </li>
  );
}

function ChartHeader({
  chart,
  row,
  onBack,
  onConsult,
  onCancelConsult,
}: {
  chart: EmrChart;
  row: WorklistPatient | null;
  onBack(): void;
  /** 담당 의료진이면 협진 의뢰 보내기 */
  onConsult: (() => void) | null;
  onCancelConsult(c: EmrConsult): void;
}) {
  const p = chart.patient;
  const via = chart.access?.via;
  const grant = chart.access?.grant ?? null;
  const received = chart.consult?.received ?? null;
  const sent = chart.consult?.sent ?? [];
  const last = p.lastRecord;
  const facts: [string, string][] = [
    ['대표 진단', p.conditions.slice(0, 3).join(', ') || '없음'],
    [p.status === 'DORMANT' ? '마지막 내원 때 진행 중' : '진행 중', `진단 ${chart.problems.active} · 처방 ${chart.medications.active} · 관리 계획 ${chart.carePlans.active}`],
    ['마지막 내원', last ? `${last} (${sinceDay(last)})` : '–'],
    ['내원', `${chart.visitDays}회${chart.firstRecord ? ` (${chart.firstRecord.slice(0, 4)}년부터)` : ''}`],
  ];
  return (
    <header className="border-b border-line bg-emr-banner px-4 py-3 md:px-5">
      <button type="button" onClick={onBack} className="btn-ghost btn-sm -ml-2 mb-1 h-7 gap-1 text-ink-2 lg:hidden">
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />내 담당 환자
      </button>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="flex items-baseline gap-1.5 text-ink">
          <span className="text-xs font-semibold text-ink-3">{p.regno ? '등록번호' : '환자 번호'}</span>
          <span className="num text-[19px] font-bold tracking-[-0.01em]">{numberOf(p)}</span>
        </h2>
        <span className="text-[13px] text-ink-2">{who(p)}</span>
        <StatusTag status={p.status} label={p.statusLabel} openItems={p.openItems} />
        {via === 'consult' && grant ? (
          <ConsultTag expiresAt={grant.expiresAt} />
        ) : via === 'break_glass' && grant ? (
          <GlassTag expiresAt={grant.expiresAt} />
        ) : (
          row?.access === 'assigned' && <span className="rounded-[5px] border border-line px-1.5 py-px text-[10.5px] font-semibold text-ink-3">담당</span>
        )}
        {onConsult && (
          <button type="button" className="btn-ghost btn-sm ml-auto h-8 gap-1.5 border border-line bg-surface text-ink-2" onClick={onConsult}>
            <Send className="h-3.5 w-3.5" aria-hidden />
            협진 의뢰
          </button>
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
      {p.risk && <RiskLine risk={p.risk} />}
      {via === 'break_glass' && grant && (
        <p className="mt-2 text-xs leading-5 text-ink-2">
          {grant.reasonLabel}: {grant.note} · 이 열람은 감사 기록에 남고 보안 담당자가 검토합니다.
        </p>
      )}
      {via === 'consult' && (
        <p className="mt-2 text-xs leading-5 text-ink-2">
          {received ? `${received.sender.displayName}${received.sender.department ? `(${received.sender.department})` : ''} 선생님의 협진 의뢰: ${received.note}` : grant?.note}
          {' · '}이 열람은 감사 기록에 남고 보안 담당자가 검토합니다.
        </p>
      )}
      {sent.length > 0 && (
        <ul className="mt-2 space-y-1">
          {sent.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-2">
              <Send className="h-3 w-3 text-iris-text" aria-hidden />
              <span>
                {c.receiver.displayName}
                {c.receiver.department ? `(${c.receiver.department})` : ''} 선생님께 협진 의뢰함 ·{' '}
                <strong className="font-semibold text-ink">{c.status === 'opened' ? '상대가 열어 봄' : '아직 열지 않음'}</strong>
              </span>
              <button type="button" className="btn-ghost btn-sm h-6 px-1.5 text-xs text-ink-3 hover:text-ink" onClick={() => onCancelConsult(c)}>
                의뢰 취소
              </button>
            </li>
          ))}
        </ul>
      )}
    </header>
  );
}

/**
 * 내 담당 환자 (python -m medicloak): 로그인한 의료진의 담당 외래 환자 목록 → 차트 요약 → 유사 사례 찾기(진료 지원 AI).
 * 담당이 아닌 환자는 목록에 없다. 협진은 담당 의료진이 보낸 의뢰를 목록 위에서 번호 없이 열고, 당직 · 응급처럼 꼭 봐야 할 때만
 * '담당 외 환자 열기'에 등록번호와 사유를 적고 연다 (ADR-0034 · ADR-0036).
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
  const [level, setLevel] = useState<TriageLevel | null>(null);
  const [byRisk, setByRisk] = useState(false);
  const [chart, setChart] = useState<{ id: string; data: EmrChart | null; error: ApiError | Error | null } | null>(null);
  const [glassOpen, setGlassOpen] = useState(false);
  const [consultOpen, setConsultOpen] = useState(false);
  const [consults, setConsults] = useState<EmrConsult[]>([]);
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
    emrApi.consults(ctl.signal).then(
      (x) => setConsults(x.received),
      () => undefined,
    );
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

  const mine = useMemo(() => (list ?? []).filter((p) => !p.access || p.access === 'assigned'), [list]);
  const glass = useMemo(() => (list ?? []).filter((p) => p.access === 'consult' || p.access === 'break_glass'), [list]);
  // 받은 협진 의뢰 중 열 것: 아직 열지 않았거나, 열었던 열람이 끝나 목록에 없는 것 (기한 안)
  const inbox = useMemo(() => consults.filter((c) => c.open && (c.status === 'pending' || !glass.some((p) => p.fhirId === c.fhirId))), [consults, glass]);
  const counts = useMemo(() => {
    const n = (s: Status) => mine.filter((p) => p.status === s).length;
    return { ACTIVE: n('ACTIVE'), RESOLVED: n('RESOLVED'), DORMANT: n('DORMANT'), ALL: mine.length };
  }, [mine]);
  const inTab = useMemo(() => (tab === 'ALL' ? mine : mine.filter((p) => p.status === tab)), [mine, tab]);
  // 위험 등급마다 환자 수 (지금 진료 상태 탭 안에서)
  const levelCounts = useMemo(() => LEVELS.map((l) => inTab.filter((p) => p.risk?.level === l).length), [inTab]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const byLevel = level ? inTab.filter((p) => p.risk?.level === level) : inTab;
    // 진단 이름이 영어라 한국어 이름(기관지염 · 치은염 …)도 함께 찾는다
    const found = !t
      ? byLevel
      : byLevel.filter((p) =>
          [p.regno ?? '', p.regno?.replace('-', '') ?? '', p.identifier, ...p.conditions, ...p.purposes.map((x) => `${x.mainDx ?? ''} ${x.item ?? ''} ${x.purposeLabel}`)].some((s) =>
            `${s} ${koreanNames(s)}`.toLowerCase().includes(t),
          ),
        );
    // 위험 높은 순: 등급(1 위급 먼저) → 같은 등급은 최근 내원 먼저. 아니면 서버 순서 그대로
    return byRisk ? [...found].sort((a, b) => (a.risk?.level ?? 9) - (b.risk?.level ?? 9) || (b.lastRecord ?? '').localeCompare(a.lastRecord ?? '')) : found;
  }, [inTab, q, level, byRisk]);

  const row = list?.find((p) => p.fhirId === picked) ?? null;
  const isCurrent = (p: WorklistPatient) => p.purposes.some((x) => x.trialId === currentTrial);
  const breakGlass = me?.breakGlass.on ? me.breakGlass : null;
  const chartData = chart?.id === picked ? chart.data : null;
  const chartError = chart?.id === picked ? chart.error : null;

  function onOpened(fhirId: string, created: boolean, regno?: string | null) {
    setGlassOpen(false);
    const no = regno ?? fhirId.slice(0, 8);
    toast(created ? `${no} 환자를 예외 열람으로 열었습니다. 감사 기록에 남았습니다.` : `${no} 환자는 이미 예외 열람 중입니다.`);
    setReload((n) => n + 1);
    navigate(`/emr/${encodeURIComponent(fhirId)}`);
  }

  async function openConsult(c: EmrConsult) {
    try {
      const r = await emrApi.openConsult(c.id);
      toast(`협진 의뢰로 ${c.regno ?? '환자'} 차트를 열었습니다. ${me?.consult?.hours ?? 12}시간 동안 볼 수 있습니다.`);
      setReload((n) => n + 1);
      navigate(`/emr/${encodeURIComponent(r.fhirId)}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : '협진 의뢰를 열지 못했습니다.');
      setReload((n) => n + 1);
    }
  }

  async function declineConsult(c: EmrConsult) {
    try {
      await emrApi.declineConsult(c.id);
      toast(`${c.sender.displayName} 선생님의 협진 의뢰를 거절했습니다.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : '협진 의뢰를 거절하지 못했습니다.');
    }
    setReload((n) => n + 1);
  }

  async function cancelConsult(c: EmrConsult) {
    try {
      await emrApi.cancelConsult(c.id);
      toast(`${c.receiver.displayName} 선생님께 보낸 협진 의뢰를 취소했습니다. 그 의뢰로 연 열람도 끝났습니다.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : '협진 의뢰를 취소하지 못했습니다.');
    }
    setReload((n) => n + 1);
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside aria-label="내 담당 환자" className={`${picked ? 'hidden lg:flex' : 'flex'} min-h-0 flex-col border-line bg-surface lg:border-r`}>
        <header className="border-b border-line px-4 pb-3 pt-3.5">
          <h2 className="flex items-center gap-2 text-[15px] font-bold text-ink">
            내 담당 환자
            {list && <span className="num text-[13px] font-semibold text-ink-3">{mine.length}명</span>}
            <button
              type="button"
              aria-pressed={byRisk}
              onClick={() => setByRisk((b) => !b)}
              className={`ml-auto inline-flex h-7 shrink-0 items-center gap-1 whitespace-nowrap rounded-[7px] border px-2 text-[11.5px] font-semibold ${byRisk ? 'border-ink bg-ink text-surface' : 'border-line bg-surface text-ink-2 hover:bg-surface-2'}`}
              title="위험 등급이 높은 환자부터 (같은 등급은 최근 내원 먼저)"
            >
              <ArrowDownUp className="h-3 w-3" aria-hidden />
              위험 높은 순
            </button>
          </h2>
          <label className="relative mt-2.5 block">
            <span className="sr-only">담당 환자 찾기</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="등록번호, 진단(한글 · 영문), 처치"
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
          <div role="group" aria-label="환자 위험 등급으로 거르기" className="mt-2 grid grid-cols-5 gap-1">
            {LEVELS.map((l, i) => {
              const on = level === l;
              return (
                <button
                  key={l}
                  type="button"
                  aria-pressed={on}
                  disabled={!levelCounts[i] && !on}
                  onClick={() => setLevel(on ? null : l)}
                  title={`위험 등급 ${l} ${TRI_KO[l]} 환자만 보기`}
                  className={`flex h-[30px] items-center justify-center gap-1 rounded-[7px] border text-[11px] font-semibold disabled:opacity-40 ${on ? `${TRI[l].badge} border-transparent` : `border-line ${TRI[l].tint} ${TRI[l].text} hover:border-line-input`}`}
                >
                  <span aria-hidden className={`h-2 w-2 rounded-full ${on ? 'bg-current' : TRI[l].bar}`} />
                  {TRI_KO[l]}
                  <span className="num font-normal">{levelCounts[i]}</span>
                </button>
              );
            })}
          </div>
        </header>
        {error ? (
          <ErrorState message={error} />
        ) : !list ? (
          <LoadingState label="담당 환자를 불러오는 중" />
        ) : (
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            {inbox.length > 0 && <ConsultInbox items={inbox} onOpen={(c) => void openConsult(c)} onDecline={(c) => void declineConsult(c)} />}
            {glass.length > 0 && (
              <section aria-label="담당 외 환자 (협진 · 예외 열람)" className="border-b border-line">
                <h3 className="bg-surface-2 px-4 py-1.5 text-[11.5px] font-bold text-ink-2">담당 외 환자 · 협진 · 예외 열람</h3>
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
              <p className="px-4 py-8 text-center text-[13px] text-ink-3">
                맞는 환자가 없습니다.
                {level && (
                  <button type="button" className="mt-2 block w-full text-xs font-semibold text-iris-text hover:underline" onClick={() => setLevel(null)}>
                    위험 등급 거르기 풀기
                  </button>
                )}
              </p>
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
              <p className="mt-1.5 text-[13px] leading-6 text-ink-2">내원 이력, 진단 이력, 처방, 시술, 관리 계획을 본 뒤 필요하면 같은 화면에서 유사 사례를 찾습니다.</p>
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
          // 좁은 화면: 머리 · 유사 사례 찾기 · 차트가 한 줄로 함께 내려간다.
          // 넓은 화면(xl): 머리는 위에 두고, 차트와 유사 사례 찾기가 따로 내려간다 (한쪽이 길어도 다른 쪽 끝까지 볼 수 있게)
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto xl:flex xl:flex-col xl:overflow-hidden">
            <ChartHeader
              chart={chartData}
              row={row}
              onBack={() => navigate('/emr')}
              onConsult={chartData.consult?.canSend && me?.consult?.on ? () => setConsultOpen(true) : null}
              onCancelConsult={(c) => void cancelConsult(c)}
            />
            <div className="grid grid-cols-1 gap-4 p-4 md:px-5 xl:min-h-0 xl:flex-1 xl:grid-cols-[minmax(0,1fr)_372px] xl:gap-0 xl:p-0">
              <div className="scroll-thin xl:order-2 xl:min-h-0 xl:overflow-y-auto xl:border-l xl:border-line xl:p-4">
                <SimilarCaseBox fhirId={chartData.patient.fhirId} identifier={numberOf(chartData.patient)} purposes={chartData.purposes ?? row?.purposes ?? []} />
              </div>
              <div className="scroll-thin min-w-0 xl:order-1 xl:min-h-0 xl:overflow-y-auto xl:p-4 xl:pl-5">
                <ChartSummary chart={chartData} />
                <p className="mt-3 text-xs leading-5 text-ink-3">차트는 병원 EMR(가상 EMR)의 진료 기록에서 만든 요약입니다. 연 일은 접근 기록에 남습니다.</p>
              </div>
            </div>
          </div>
        )}
      </section>
      {glassOpen && breakGlass && <BreakGlassDialog policy={breakGlass} onCancel={() => setGlassOpen(false)} onOpened={onOpened} />}
      {consultOpen && chartData && me?.consult && (
        <ConsultDialog
          fhirId={chartData.patient.fhirId}
          regno={numberOf(chartData.patient)}
          policy={me.consult}
          onCancel={() => setConsultOpen(false)}
          onSent={(c) => {
            setConsultOpen(false);
            toast(c.created ? `${c.receiver.displayName} 선생님께 협진 의뢰를 보냈습니다.` : `${c.receiver.displayName} 선생님께 보낸 협진 의뢰가 이미 있습니다.`);
            setReload((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}
