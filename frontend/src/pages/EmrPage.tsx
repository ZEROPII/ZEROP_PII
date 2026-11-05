import { ArrowLeft, ChevronRight, Info, Loader2, Search, Stethoscope } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { emrApi, fhirDate, fhirLabel, type FhirResource } from '../api/emrApi';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useToast } from '../components/layout/Toast';
import { useWorkspace } from '../state/WorkspaceContext';
import type { LaunchProgress, WorklistPatient } from '../types/domain';

const SEX_KO = { male: '남', female: '여', unknown: '성별 미상' } as const;
type StatusTab = WorklistPatient['status'] | 'ALL';
const TABS: { id: StatusTab; label: string }[] = [
  { id: 'ACTIVE', label: '진료 중' },
  { id: 'RESOLVED', label: '완치' },
  { id: 'DORMANT', label: '장기 미내원' },
  { id: 'ALL', label: '전체' },
];
const STATUS_TITLE: Record<WorklistPatient['status'], (p: WorklistPatient) => string> = {
  ACTIVE: (p) => `끝나지 않은 진단 · 관리 계획 ${p.openItems}건, 최근 3년 안에 기록이 있습니다`,
  RESOLVED: () => '기록된 진단과 관리 계획이 모두 끝났습니다',
  DORMANT: (p) => `끝나지 않은 진단 · 관리 계획 ${p.openItems}건이 있지만 마지막 기록이 3년보다 오래되었습니다`,
};

/** 성별 · 연령대 (생년 · 거주 지역은 보이지 않는다) */
function who(p: WorklistPatient): string {
  return [SEX_KO[p.sex], p.ageBand].filter(Boolean).join(' · ');
}

function StatusTag({ p }: { p: WorklistPatient }) {
  // 점 하나로 상태를 구분한다: 진료 중(채운 초록) · 완치(채운 회색) · 장기 미내원(빈 원)
  const dot = p.status === 'ACTIVE' ? 'bg-safe' : p.status === 'RESOLVED' ? 'bg-ink-3' : 'border border-ink-3';
  return (
    <span title={STATUS_TITLE[p.status](p)} className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${p.status === 'ACTIVE' ? 'text-ink' : 'text-ink-3'}`}>
      <span aria-hidden className={`h-[7px] w-[7px] rounded-full ${dot}`} />
      {p.statusLabel}
    </span>
  );
}

/** 진단 · 처방 기록 몇 줄 (FHIR 검색 결과, 최근 것부터) */
function ChartList({ title, source, items, empty }: { title: string; source: string; items: FhirResource[] | null; empty: string }) {
  return (
    <section className="border-t border-line px-4 py-3.5">
      <h3 className="flex items-baseline justify-between gap-2 text-xs font-semibold text-ink-2">
        {title}
        <span className="font-mono text-[10.5px] font-normal text-ink-3">{source}</span>
      </h3>
      {!items ? (
        <p className="mt-2 text-[13px] text-ink-3">불러오는 중</p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-[13px] text-ink-3">{empty}</p>
      ) : (
        <ul className="mt-1.5 space-y-1">
          {items.map((r) => (
            <li key={r.id} className="flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-ink" title={fhirLabel(r)}>
                {fhirLabel(r)}
              </span>
              <span className="num shrink-0 text-xs text-ink-3">{(fhirDate(r) ?? '').slice(0, 10)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function recent(items: FhirResource[], n: number): FhirResource[] {
  return [...items].sort((a, b) => (fhirDate(b) ?? '').localeCompare(fhirDate(a) ?? '')).slice(0, n);
}

/**
 * EMR 외래 진료 목록 (python -m medicloak). 환자와 진료 목적을 골라 진료 지원 AI를 연다.
 * 환자 기록은 가상 EMR의 FHIR API(/fhir)에서 읽는다. 여기 나오는 환자는 외래 환자뿐이고,
 * 진료 지원 AI가 찾아 줄 비슷한 과거 사례의 기록은 EMR로 열 수 없다 (AI 답과 MediCloak 보호를 거쳐서만 보인다).
 */
export function EmrPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { state, actions } = useWorkspace();
  const [list, setList] = useState<WorklistPatient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [picked, setPicked] = useState<string | null>(null);
  const [purpose, setPurpose] = useState<string | null>(null);
  const [chart, setChart] = useState<{ id: string; conditions: FhirResource[] | null; meds: FhirResource[] | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<StatusTab>('ACTIVE');
  const [confirm, setConfirm] = useState(false);
  const [progress, setProgress] = useState<LaunchProgress | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  const current = state.patient.data ?? null;
  const currentTrial = current?.trialId;

  useEffect(() => {
    const ctl = new AbortController();
    emrApi.worklist(ctl.signal).then(
      (x) => {
        setList(x);
        setError(null);
      },
      (e) => !(e instanceof DOMException) && setError(e instanceof Error ? e.message : '외래 목록을 불러오지 못했습니다.'),
    );
    return () => ctl.abort();
  }, []);

  const counts = useMemo(
    () => {
      const n = (s: WorklistPatient['status']) => list?.filter((p) => p.status === s).length ?? 0;
      return { ACTIVE: n('ACTIVE'), RESOLVED: n('RESOLVED'), DORMANT: n('DORMANT'), ALL: list?.length ?? 0 };
    },
    [list],
  );

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!list) return [];
    const inTab = tab === 'ALL' ? list : list.filter((p) => p.status === tab);
    if (!t) return inTab;
    return inTab.filter((p) =>
      [p.identifier, ...p.conditions, ...p.purposes.map((x) => `${x.mainDx ?? ''} ${x.item ?? ''} ${x.purposeLabel}`)].some((s) =>
        s.toLowerCase().includes(t),
      ),
    );
  }, [list, q, tab]);

  const patient = list?.find((p) => p.fhirId === picked) ?? null;

  // 고른 환자의 진단 · 처방 기록 (FHIR)
  useEffect(() => {
    if (!picked) return;
    const ctl = new AbortController();
    setChart({ id: picked, conditions: null, meds: null });
    emrApi.search('Condition', picked, ctl.signal).then(
      (b) => setChart((c) => (c && c.id === picked ? { ...c, conditions: recent((b.entry ?? []).map((e) => e.resource), 6) } : c)),
      () => setChart((c) => (c && c.id === picked ? { ...c, conditions: [] } : c)),
    );
    emrApi.search('MedicationRequest', picked, ctl.signal).then(
      (b) => setChart((c) => (c && c.id === picked ? { ...c, meds: recent((b.entry ?? []).map((e) => e.resource), 6) } : c)),
      () => setChart((c) => (c && c.id === picked ? { ...c, meds: [] } : c)),
    );
    return () => ctl.abort();
  }, [picked]);

  // 여는 동안 서버가 알려 주는 지금 단계 (실제 LLM 호출이 차례로 몇 번 이어진다)
  useEffect(() => {
    if (!busy) {
      setProgress(null);
      return;
    }
    let stop = false;
    let timer = 0;
    const tick = () => {
      emrApi.launchProgress().then(
        (p) => !stop && setProgress(p),
        () => undefined,
      );
      if (!stop) timer = window.setTimeout(tick, 700);
    };
    timer = window.setTimeout(tick, 250);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [busy]);

  function pick(p: WorklistPatient) {
    setConfirm(false);
    setPicked(p.fhirId);
    setPurpose((p.purposes.find((x) => x.trialId === currentTrial) ?? p.purposes[0]).purpose);
    window.setTimeout(() => {
      if (window.matchMedia('(max-width: 1023px)').matches) detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  }

  async function open() {
    if (!patient || !purpose) return;
    setConfirm(false);
    setBusy(true);
    try {
      const r = await emrApi.launch(patient.fhirId, purpose);
      actions.resetAndReload();
      toast(`환자 ${patient.identifier}로 진료 지원 AI를 열었습니다${r.seconds != null ? ` (${Math.round(r.seconds)}초)` : ''}.`);
      navigate('/');
    } catch (e) {
      toast(e instanceof Error ? e.message : '진료 지원 AI를 열지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  const sel = patient?.purposes.find((x) => x.purpose === purpose) ?? null;
  const selIsCurrent = !!sel && sel.trialId === currentTrial;
  const switching = !!current && !!sel && !selIsCurrent;

  function onOpen() {
    if (selIsCurrent) {
      navigate('/');
      return;
    }
    if (switching && !confirm) {
      setConfirm(true);
      return;
    }
    void open();
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_400px] lg:overflow-hidden">
      <section aria-label="외래 진료 목록" className="flex flex-col lg:min-h-0 lg:border-r lg:border-line">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3 md:px-5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-ink">외래 진료 목록</h2>
            <p className="text-xs text-ink-3">지금 진료할 환자를 고르세요. 고른 환자로 진료 지원 AI가 열리고, 위의 진료 중 환자가 이 환자로 바뀝니다.</p>
          </div>
          <label className="relative ml-auto w-full sm:w-[280px]">
            <span className="sr-only">환자 찾기</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="환자 번호, 진단, 처치"
              className="h-9 w-full rounded-control border border-line-input bg-surface pl-8 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
            />
          </label>
        </header>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-2 md:px-5">
          <div role="tablist" aria-label="진료 상태" className="flex flex-wrap gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                type="button"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                className={`h-7 rounded-[8px] px-2.5 text-[13px] font-semibold ${tab === t.id ? 'bg-surface text-ink shadow-sm ring-1 ring-line' : 'text-ink-3 hover:text-ink'}`}
              >
                {t.label} <span className="num font-normal text-ink-3">{counts[t.id]}</span>
              </button>
            ))}
          </div>
          <p className="flex min-w-0 items-start gap-1.5 text-xs leading-5 text-ink-3">
            <Info className="mt-[3px] h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>비슷한 과거 사례는 이 목록에서 찾지 않습니다. 진료 지원 AI는 이 목록에 없는 병원의 과거 기록 환자에서 찾고, 그 기록은 MediCloak을 거쳐서만 보입니다.</span>
          </p>
        </div>
        {error ? (
          <ErrorState message={error} />
        ) : !list ? (
          <LoadingState label="외래 목록을 불러오는 중" />
        ) : (
          <div className="scroll-thin lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead className="bg-page lg:sticky lg:top-0 lg:z-[1]">
                <tr className="text-left text-xs text-ink-3">
                  <th className="border-b border-line px-4 py-2 font-semibold md:pl-5">환자</th>
                  <th className="hidden border-b border-line px-3 py-2 font-semibold sm:table-cell">진료 상태</th>
                  <th className="hidden border-b border-line px-3 py-2 font-semibold md:table-cell">대표 진단</th>
                  <th className="border-b border-line px-3 py-2 font-semibold">진료 목적</th>
                  <th className="hidden border-b border-line px-3 py-2 text-right font-semibold sm:table-cell">마지막 기록</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => {
                  const active = p.fhirId === picked;
                  const isCurrent = p.purposes.some((x) => x.trialId === currentTrial);
                  return (
                    <tr
                      key={p.fhirId}
                      onClick={() => pick(p)}
                      aria-selected={active}
                      className={`cursor-pointer ${active ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}
                    >
                      <td className={`border-b border-line px-4 py-2.5 align-top md:pl-5 ${active ? 'shadow-[inset_3px_0_0_var(--zp-iris)]' : ''}`}>
                        <button type="button" onClick={() => pick(p)} className="text-left">
                          <span className="font-mono text-[13px] font-semibold text-ink">{p.identifier}</span>
                          {isCurrent && (
                            <span className="ml-2 rounded-[5px] bg-iris px-1.5 py-px text-[10.5px] font-bold text-iris-on" title="위 진료 중 환자 띠에 열려 있는 환자">
                              지금 연 환자
                            </span>
                          )}
                        </button>
                        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-3">
                          {who(p)}
                          <span className="sm:hidden">
                            <StatusTag p={p} />
                          </span>
                        </span>
                      </td>
                      <td className="hidden border-b border-line px-3 py-2.5 align-top sm:table-cell">
                        <StatusTag p={p} />
                      </td>
                      <td className="hidden max-w-[260px] border-b border-line px-3 py-2.5 align-top text-ink-2 md:table-cell">
                        <span className="line-clamp-2">{p.conditions.slice(0, 2).join(', ') || '기록 없음'}</span>
                      </td>
                      <td className="border-b border-line px-3 py-2.5 align-top">
                        <span className="text-xs leading-5 text-ink-2">{p.purposes.map((x) => x.purposeLabel).join(' · ')}</span>
                      </td>
                      <td className="num hidden border-b border-line px-3 py-2.5 text-right align-top text-xs text-ink-3 sm:table-cell">{p.lastRecord ?? '–'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {shown.length === 0 && <p className="px-5 py-8 text-center text-[13px] text-ink-3">맞는 환자가 없습니다.</p>}
            <p className="px-4 py-3 text-xs text-ink-3 md:px-5">
              외래 환자 {list.length}명 · 진단 · 처방 기록은 EMR의 FHIR R4 API에서 읽습니다.
            </p>
          </div>
        )}
      </section>

      <aside ref={detailRef} aria-label="고른 환자" className="flex flex-col border-t border-line bg-surface lg:min-h-0 lg:border-t-0">
        {!patient ? (
          <div className="grid flex-1 place-items-center px-6 py-12 text-center">
            <div>
              <Stethoscope className="mx-auto h-7 w-7 text-ink-3" aria-hidden />
              <p className="mt-3 text-[13px] text-ink-2">목록에서 환자를 고르면 진단 · 처방 기록과 진료 목적이 여기에 나옵니다.</p>
            </div>
          </div>
        ) : (
          <>
            <div className="scroll-thin lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
              <header className="px-4 pb-3 pt-4">
                <p className="text-xs text-ink-3">환자</p>
                <p className="mt-0.5 font-mono text-[18px] font-bold text-ink">{patient.identifier}</p>
                <p className="mt-0.5 flex items-center gap-2 text-[13px] text-ink-2">
                  {who(patient)}
                  <StatusTag p={patient} />
                </p>
              </header>
              <div className="border-t border-line px-4 py-3.5">
                <p id="purpose-label" className="text-xs font-semibold text-ink-3">
                  진료 목적
                </p>
                <div role="radiogroup" aria-labelledby="purpose-label" className="mt-2 space-y-1.5">
                  {patient.purposes.map((x) => {
                    const on = x.purpose === purpose;
                    return (
                      <label
                        key={x.trialId}
                        className={`flex cursor-pointer gap-2.5 rounded-control border px-3 py-2.5 ${on ? 'border-iris bg-iris-tint' : 'border-line hover:bg-surface-2'}`}
                      >
                        <input type="radio" name="purpose" className="mt-1 accent-[var(--zp-iris)]" checked={on} onChange={() => setPurpose(x.purpose)} />
                        <span className="min-w-0 text-[13px]">
                          <span className="font-semibold text-ink">{x.purposeLabel}</span>
                          <span className="num ml-2 text-xs text-ink-3" title="진료 지원 AI는 이 날의 진료를 기준으로 환자 요약(연령대 · 주진단 · 고려 중인 처치)을 만듭니다">
                            {x.visitDate} 진료 기준
                          </span>
                          <span className="mt-0.5 block text-ink-2">
                            {x.mainDx}
                            {x.item ? ` · 고려 중: ${x.item}` : ''}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <ChartList title="최근 진단" source="FHIR Condition" items={chart?.id === patient.fhirId ? chart.conditions : null} empty="진단 기록이 없습니다." />
              <ChartList title="최근 처방" source="FHIR MedicationRequest" items={chart?.id === patient.fhirId ? chart.meds : null} empty="처방 기록이 없습니다." />
            </div>
            <footer className="border-t border-line px-4 py-3.5">
              {confirm && current && (
                <div role="alertdialog" aria-labelledby="switch-title" aria-describedby="switch-desc" className="mb-2.5 rounded-control border border-caution bg-caution-tint px-3 py-2.5">
                  <p id="switch-title" className="text-[13px] font-semibold text-ink">
                    진료 중 환자를 바꿉니다
                  </p>
                  <p id="switch-desc" className="mt-1 text-xs leading-5 text-ink-2">
                    위 띠의 환자({current.ageSexLabel} · {current.primaryDiagnosis})를 닫고 {patient.identifier} 환자로 진료 지원 AI를 엽니다. 지금까지의 대화는 조회 기록에 남습니다.
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button type="button" className="btn-primary btn-sm" onClick={() => void open()}>
                      바꿔서 열기
                    </button>
                    <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirm(false)}>
                      취소
                    </button>
                  </div>
                </div>
              )}
              <button type="button" className="btn-primary h-10 w-full" disabled={busy || !sel || confirm} onClick={onOpen}>
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : selIsCurrent ? (
                  <ArrowLeft className="h-4 w-4" aria-hidden />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden />
                )}
                {busy ? '진료 지원 AI를 여는 중' : !sel ? '진료 목적을 고르세요' : selIsCurrent ? '열린 진료 지원 AI로 돌아가기' : `${sel.purposeLabel} 참고로 진료 지원 AI 열기`}
              </button>
              {busy && (
                <div role="status" aria-live="polite" className="mt-2.5">
                  <div className="h-1 overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full animate-pulse rounded-full bg-iris" style={{ width: `${Math.min(92, 18 + (progress?.calls ?? 0) * 12)}%` }} />
                  </div>
                  <p className="mt-1.5 text-xs leading-5 text-ink-2">{progress?.label ?? '비슷한 과거 사례를 찾고 있습니다'}</p>
                  <p className="num text-[11px] text-ink-3">
                    {Math.round(progress?.elapsed ?? 0)}초 지남 · 실제 LLM 호출 {progress?.calls ?? 0}번
                  </p>
                </div>
              )}
              <p className="mt-1 text-xs leading-5 text-ink-3">
                AI에는 이 환자의 요약(연령대, 성별, 주진단, 고려 중인 처치)만 함께 보냅니다. MediCloak은 AI가 찾아 준 과거 사례 쪽에서 나오는 값을 보호합니다.
              </p>
            </footer>
          </>
        )}
      </aside>
    </div>
  );
}
