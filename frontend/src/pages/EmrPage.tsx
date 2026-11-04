import { ChevronRight, Loader2, Search, Stethoscope } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { emrApi, fhirDate, fhirLabel, type FhirResource } from '../api/emrApi';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useToast } from '../components/layout/Toast';
import { useWorkspace } from '../state/WorkspaceContext';
import type { WorklistPatient } from '../types/domain';

const SEX_KO = { male: '남', female: '여', unknown: '성별 미상' } as const;

function who(p: WorklistPatient): string {
  return [SEX_KO[p.sex], p.birthYear ? `${p.birthYear}년생` : null].filter(Boolean).join(' · ');
}

/** 진단 · 처방 기록 몇 줄 (FHIR 검색 결과, 최근 것부터) */
function ChartList({ title, items, empty }: { title: string; items: FhirResource[] | null; empty: string }) {
  return (
    <section className="border-t border-line px-4 py-3.5">
      <h3 className="text-xs font-semibold text-ink-3">{title}</h3>
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
  const detailRef = useRef<HTMLElement>(null);
  const currentTrial = state.patient.data?.trialId;

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

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!list) return [];
    if (!t) return list;
    return list.filter((p) =>
      [p.identifier, p.region, ...p.conditions, ...p.purposes.map((x) => `${x.mainDx ?? ''} ${x.item ?? ''} ${x.purposeLabel}`)].some((s) =>
        s.toLowerCase().includes(t),
      ),
    );
  }, [list, q]);

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

  function pick(p: WorklistPatient) {
    setPicked(p.fhirId);
    setPurpose((p.purposes.find((x) => x.trialId === currentTrial) ?? p.purposes[0]).purpose);
    window.setTimeout(() => {
      if (window.matchMedia('(max-width: 1023px)').matches) detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  }

  async function open() {
    if (!patient || !purpose) return;
    setBusy(true);
    try {
      await emrApi.launch(patient.fhirId, purpose);
      actions.resetAndReload();
      toast(`환자 ${patient.identifier}로 진료 지원 AI를 열었습니다.`);
      navigate('/');
    } catch (e) {
      toast(e instanceof Error ? e.message : '진료 지원 AI를 열지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  const sel = patient?.purposes.find((x) => x.purpose === purpose) ?? null;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_400px] lg:overflow-hidden">
      <section aria-label="외래 진료 목록" className="flex flex-col lg:min-h-0 lg:border-r lg:border-line">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3 md:px-5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-ink">외래 진료 목록</h2>
            <p className="text-xs text-ink-3">진료 지원 AI를 열 환자와 진료 목적을 고르세요.</p>
          </div>
          <label className="relative ml-auto w-full sm:w-[280px]">
            <span className="sr-only">환자 찾기</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="환자 번호, 진단, 처치, 지역"
              className="h-9 w-full rounded-control border border-line-input bg-surface pl-8 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
            />
          </label>
        </header>
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
                  <th className="hidden border-b border-line px-3 py-2 font-semibold md:table-cell">대표 진단</th>
                  <th className="border-b border-line px-3 py-2 font-semibold">진료 목적</th>
                  <th className="hidden border-b border-line px-3 py-2 text-right font-semibold sm:table-cell">최근 진료일</th>
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
                            <span className="ml-2 rounded-[5px] bg-iris px-1.5 py-px text-[10.5px] font-bold text-iris-on">AI 열림</span>
                          )}
                          {p.featured && !isCurrent && <span className="ml-2 text-[11px] text-ink-3">시연용</span>}
                        </button>
                        <span className="mt-0.5 block text-xs text-ink-3">
                          {who(p)} · {p.region}
                        </span>
                      </td>
                      <td className="hidden max-w-[260px] border-b border-line px-3 py-2.5 align-top text-ink-2 md:table-cell">
                        <span className="line-clamp-2">{p.conditions.slice(0, 2).join(', ') || '기록 없음'}</span>
                      </td>
                      <td className="border-b border-line px-3 py-2.5 align-top">
                        <span className="flex flex-wrap gap-1">
                          {p.purposes.map((x) => (
                            <span key={x.trialId} className="rounded-[5px] border border-line px-1.5 py-px text-[11.5px] text-ink-2">
                              {x.purposeLabel}
                            </span>
                          ))}
                        </span>
                      </td>
                      <td className="num hidden border-b border-line px-3 py-2.5 text-right align-top text-xs text-ink-3 sm:table-cell">{p.lastVisit}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {shown.length === 0 && <p className="px-5 py-8 text-center text-[13px] text-ink-3">맞는 환자가 없습니다.</p>}
            <p className="px-4 py-3 text-xs text-ink-3 md:px-5">
              외래 환자 {list.length}명 (Synthea 합성 데이터, 실제 환자 아님) · 기록은 가상 EMR의 FHIR R4 API에서 읽습니다.
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
                <p className="mt-0.5 text-[13px] text-ink-2">
                  {who(patient)} · {patient.region}
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
                          <span className="num ml-2 text-xs text-ink-3">{x.visitDate} 진료</span>
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
              <ChartList title="최근 진단 (FHIR Condition)" items={chart?.id === patient.fhirId ? chart.conditions : null} empty="진단 기록이 없습니다." />
              <ChartList title="최근 처방 (FHIR MedicationRequest)" items={chart?.id === patient.fhirId ? chart.meds : null} empty="처방 기록이 없습니다." />
            </div>
            <footer className="border-t border-line px-4 py-3.5">
              <button type="button" className="btn-primary h-10 w-full" disabled={busy || !sel} onClick={() => void open()}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
                {busy ? '비슷한 사례를 찾는 중' : sel ? `${sel.purposeLabel} 참고로 진료 지원 AI 열기` : '진료 목적을 고르세요'}
              </button>
              <p role="status" aria-live="polite" className="mt-2 text-xs leading-5 text-ink-2">
                {busy ? 'AI가 과거 사례를 찾고, MediCloak이 첫 답을 확인하고 있습니다. 실제 LLM을 쓰면 수십 초 걸릴 수 있습니다.' : ''}
              </p>
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
