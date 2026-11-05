import { ChevronDown, ChevronUp, ClipboardList, RefreshCw, UserRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../state/AuthContext';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { PatientOption } from '../../types/domain';
import { MockBadge } from '../common/MockBadge';
import { useToast } from '../layout/Toast';

/** 데모 서버에서만: 다른 질의 환자로 새 대화를 시작한다 (실제 EMR에서는 진료 중 환자가 바뀌는 자리). */
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
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

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
          <p className="mb-2 text-xs leading-5 text-ink-3">실제 EMR에서는 진료 중인 환자가 바뀌는 자리입니다. 다른 질의 환자로 대화를 새로 시작합니다.</p>
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
 * EMR 환자 띠: 지금 진료 중인 환자. 이 값은 의료진 화면에만 쓰고, 질문 전송 · AI 답 · 사례 데이터 어디에도 섞지 않는다.
 * 좁은 화면에서는 주진단만 보이고 눌러서 펼친다.
 */
export function PatientBanner() {
  const { state, actions } = useWorkspace();
  const product = useAuth().status === 'user';
  const { patient } = state;
  const [expanded, setExpanded] = useState(false);
  const p = patient.data;

  const fields: [string, string][] = p
    ? [
        ['연령 / 성별', p.ageSexLabel],
        ['주진단', p.primaryDiagnosis],
        ['동반질환', p.comorbidities.join(', ') || '없음'],
        ['고려 중 처치', p.plannedProcedure],
        ['조회 목적', p.queryPurpose],
      ]
    : [];

  return (
    <section aria-label="진료 중 환자" className="shrink-0 border-b border-line bg-emr-banner">
      <div className="flex min-h-[44px] items-center gap-x-4 gap-y-1 px-4 py-1.5 md:px-5">
        <span className="inline-flex shrink-0 items-center gap-2 text-[13px] font-bold text-ink">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-iris text-iris-on">
            <UserRound className="h-3.5 w-3.5" aria-hidden />
          </span>
          진료 중 환자
          {p && !state.noConversation && (
            <span
              className="hidden rounded-[5px] border border-line px-1.5 py-px text-[10.5px] font-semibold text-ink-3 lg:inline"
              title="진료 지원 AI에는 이 요약(연령대 · 성별 · 주진단 · 동반질환 · 고려 중 처치 · 조회 목적)만 보냅니다. 이름 · 생년 · 주소는 보내지 않습니다."
            >
              AI에 보내는 요약
            </span>
          )}
        </span>
        {state.noConversation ? (
          <span className="flex min-w-0 flex-1 items-center gap-3 text-xs text-ink-3">
            열린 환자가 없습니다.
            <NavLink to="/emr" className="btn-ghost btn-sm ml-auto h-7 gap-1 text-ink-2">
              <ClipboardList className="h-3.5 w-3.5" aria-hidden />
              외래 진료 목록
            </NavLink>
          </span>
        ) : patient.status === 'error' ? (
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
                <NavLink to="/emr" className="btn-ghost btn-sm h-7 gap-1 text-ink-2">
                  <ClipboardList className="h-3.5 w-3.5" aria-hidden />
                  <span className="hidden sm:inline">다른 환자</span>
                </NavLink>
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
