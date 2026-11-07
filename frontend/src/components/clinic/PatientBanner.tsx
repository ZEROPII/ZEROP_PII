import { ChevronDown, ChevronUp, FileText, RefreshCw, UserRound, Users } from 'lucide-react';
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../../state/AuthContext';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { PatientContext, PatientOption } from '../../types/domain';
import { MockBadge } from '../common/MockBadge';
import { useToast } from '../layout/Toast';

/** 바깥을 누르거나 Esc를 누르면 닫는다 */
function useDismiss(open: boolean, box: RefObject<HTMLDivElement | null>, close: () => void) {
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, box, close]);
}

/** 데모 서버에서만: 다른 질의 환자로 새 대화를 시작한다 (실제 EMR에서는 지금 보는 환자가 바뀌는 자리). */
function DemoPatientSwitcher() {
  const { state, actions, api } = useWorkspace();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<PatientOption[]>([]);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const current = state.patient.data?.trialId;

  useEffect(() => {
    if (!api.listPatients) return;
    const ctl = new AbortController();
    api.listPatients(ctl.signal).then(setOptions, () => undefined);
    return () => ctl.abort();
  }, [api]);
  useEffect(() => {
    if (current) setPick(current);
  }, [current]);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, box, close);

  if (!api.resetSession || !options.length) return null;
  const featured = options.filter((o) => o.featured);
  const rest = options.filter((o) => !o.featured);

  async function restart() {
    setBusy(true);
    try {
      await actions.restart(pick || undefined);
      toast(`${pick || '같은 환자'}로 새 대화를 시작했습니다.`);
      setOpen(false);
    } catch {
      toast('새 대화를 시작하지 못했습니다. 서버 연결을 확인하세요.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={box} className="relative">
      <button type="button" className="btn-ghost btn-sm h-7 gap-1 text-ink-2" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="hidden sm:inline">데모 환자</span> <span className="font-mono">{current}</span>
        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-40 w-[300px] rounded-control border border-line bg-surface p-3 shadow-overlay">
          <p className="mb-2 text-xs leading-5 text-ink-3">실제 EMR에서는 지금 보는 환자가 바뀌는 자리입니다. 다른 질의 환자로 대화를 새로 시작합니다.</p>
          <label htmlFor="patient-pick" className="sr-only">
            다른 질의 환자
          </label>
          <select
            id="patient-pick"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
            className="h-8 w-full rounded-cell border border-line-input bg-surface px-2 text-xs text-ink"
          >
            <optgroup label="먼저 볼 환자">
              {featured.map((o) => (
                <option key={o.trialId} value={o.trialId}>
                  {o.trialId} {o.ageSex} {o.mainDx}
                </option>
              ))}
            </optgroup>
            <optgroup label="전체">
              {rest.map((o) => (
                <option key={o.trialId} value={o.trialId}>
                  {o.trialId} {o.qtypeLabel} {o.mainDx}
                </option>
              ))}
            </optgroup>
          </select>
          <button type="button" onClick={() => void restart()} disabled={busy} className="btn-primary btn-sm mt-2 w-full">
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} aria-hidden />이 환자로 새 대화 시작
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * 'AI에 보내는 요약': 누르면 진료 지원 AI에 실제로 보내는 환자 요약 줄과, 유사 사례 검색에 쓰는 기록 범위를 펼친다.
 * 의사가 보내는 내용을 직접 확인할 수 있게 한다 (예: 동반질환이 빠졌는지).
 */
function AiSummaryButton({ p }: { p: PatientContext }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, box, close);
  const lines = p.aiSummary ?? [];
  const basis = p.searchBasis;
  return (
    <div ref={box} className="relative hidden lg:block">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-0.5 rounded-[5px] border border-line px-1.5 py-px text-[10.5px] font-semibold text-ink-3 hover:border-line-input hover:text-ink-2"
      >
        AI에 보내는 요약
        <ChevronDown className="h-3 w-3" aria-hidden />
      </button>
      {open && (
        <div className="absolute left-0 top-7 z-40 w-[340px] rounded-control border border-line bg-surface p-3 text-xs font-normal shadow-overlay">
          <p className="leading-5 text-ink-2">진료 지원 AI에는 아래 요약만 보냅니다. 이름 · 생년 · 주소는 보내지 않습니다.</p>
          {lines.length > 0 ? (
            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-cell bg-surface-2 px-2.5 py-2">
              {lines.map((l) => (
                <div key={l.label} className="contents">
                  <dt className="text-ink-3">{l.label}</dt>
                  <dd className="break-words font-semibold text-ink">{l.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-2 text-ink-3">연령 / 성별 · 주진단 · 동반질환 · 고려 중 처치 · 조회 목적</p>
          )}
          {p.visitDate && <p className="mt-2 leading-5 text-ink-2">기준 진료일: {p.visitDate}</p>}
          {basis && (
            <p className="mt-1 leading-5 text-ink-2">
              유사 사례 검색에는 {basis.until}까지의 진단 {basis.diagnoses}개 · 약 {basis.medications}개 · 시술 {basis.procedures}개 기록을 씁니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * 환자 띠: 진료 지원 AI 대화가 열려 있는 '지금 보는 환자'. 이 값은 의료진 화면에만 쓰고, 질문 전송 · AI 답 · 사례 데이터 어디에도 섞지 않는다.
 * 운영 모드에서는 대화가 열려 있을 때만 보이고, 내 담당 환자 화면(/emr)에서는 숨긴다 (그 화면은 고른 환자의 차트를 따로 보인다,
 * 목록 위에 한 사람만 떠 있으면 그 사람만 진료 대상처럼 보였다). 좁은 화면에서는 주진단만 보이고 눌러서 펼친다.
 */
export function PatientBanner() {
  const { state, actions } = useWorkspace();
  const product = useAuth().status === 'user';
  const { pathname } = useLocation();
  const { patient } = state;
  const [expanded, setExpanded] = useState(false);
  const p = patient.data;
  if (product && (state.noConversation || pathname === '/emr' || pathname.startsWith('/emr/'))) return null;

  const fields: [string, string][] = p
    ? [
        ...(p.regno ? ([['등록번호', p.regno]] as [string, string][]) : []),
        ['연령 / 성별', p.ageSexLabel],
        ['주진단', p.primaryDiagnosis],
        ['동반질환', p.comorbidities.join(', ') || '없음'],
        ['고려 중 처치', p.plannedProcedure],
        ['조회 목적', p.queryPurpose],
      ]
    : [];

  return (
    <section aria-label="지금 보는 환자" className="shrink-0 border-b border-line bg-emr-banner">
      <div className="flex min-h-[44px] items-center gap-x-4 gap-y-1 px-4 py-1.5 md:px-5">
        <span className="inline-flex shrink-0 items-center gap-2 text-[13px] font-bold text-ink">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-iris text-iris-on">
            <UserRound className="h-3.5 w-3.5" aria-hidden />
          </span>
          지금 보는 환자
          {p && !state.noConversation && <AiSummaryButton p={p} />}
        </span>
        {patient.status === 'error' ? (
          <span className="text-xs text-danger-text">
            환자 정보를 불러오지 못했습니다.{' '}
            <button type="button" className="font-semibold underline" onClick={actions.reloadAll}>
              다시 불러오기
            </button>
          </span>
        ) : !p ? (
          <span className="text-xs text-ink-3">불러오는 중</span>
        ) : (
          <>
            <dl className={`min-w-0 flex-1 flex-wrap items-center gap-y-1 text-[13px] ${expanded ? 'flex' : 'hidden md:flex'}`}>
              {fields.map(([label, value]) => (
                <div key={label} className="flex min-w-0 items-baseline gap-1.5 border-line pr-4 md:border-l md:pl-4 md:first:border-l-0 md:first:pl-0">
                  <dt className="shrink-0 text-xs text-ink-3">{label}</dt>
                  <dd className="min-w-0 truncate font-semibold text-ink" title={value}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
            {!expanded && (
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink md:hidden">
                {p.ageSexLabel}, {p.primaryDiagnosis}
              </span>
            )}
            <button type="button" className="btn-ghost h-7 w-7 shrink-0 px-0 md:hidden" aria-expanded={expanded} aria-label="환자 정보 펼치기" onClick={() => setExpanded((e) => !e)}>
              {expanded ? <ChevronUp className="h-4 w-4" aria-hidden /> : <ChevronDown className="h-4 w-4" aria-hidden />}
            </button>
            <span className="ml-auto flex shrink-0 items-center gap-1">
              <MockBadge source={p.source} />
              {product ? (
                <>
                  {p.fhirId && (
                    <NavLink to={`/emr/${encodeURIComponent(p.fhirId)}`} className="btn-ghost btn-sm h-7 gap-1 text-ink-2" title="이 환자의 차트 요약">
                      <FileText className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">차트</span>
                    </NavLink>
                  )}
                  <NavLink to="/emr" className="btn-ghost btn-sm h-7 gap-1 text-ink-2" title="내 담당 환자 목록">
                    <Users className="h-3.5 w-3.5" aria-hidden />
                    <span className="hidden sm:inline">내 환자</span>
                  </NavLink>
                </>
              ) : (
                <DemoPatientSwitcher />
              )}
            </span>
          </>
        )}
      </div>
    </section>
  );
}
