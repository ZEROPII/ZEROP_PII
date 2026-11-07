import { AlertCircle, ArrowLeft, ChevronRight, Loader2, RotateCw, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { emrApi } from '../../api/emrApi';
import { ApiError } from '../../api/types';
import { openFailure, type OpenFailure } from '../../lib/openFailure';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { LaunchProgress, VisitChoice, WorklistPurpose } from '../../types/domain';
import { useToast } from '../layout/Toast';

const BASIS_HINT = '진료 지원 AI는 이 목적에 맞는 가장 최근 진료를 기준으로 환자 요약(나이 · 성별 · 주진단 · 동반질환 · 고려 중인 처치)을 만듭니다';

/**
 * 차트에서 진료 지원 AI로 넘어가는 자리: 진료 목적과 오늘 볼 진단을 고르고 비슷한 과거 사례를 찾는다.
 * 고르고 1초쯤 머물면 서버가 첫 답을 뒤에서 미리 만들어 둔다 (ADR-0029). 다른 환자의 대화가 열려 있으면 바꾸기 전에 묻는다.
 */
export function SimilarCaseBox({ fhirId, identifier, purposes }: { fhirId: string; identifier: string; purposes: WorklistPurpose[] }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { state, actions } = useWorkspace();
  const current = state.patient.data ?? null;
  const currentTrial = current?.trialId;
  const [purpose, setPurpose] = useState<string | null>(null);
  // 오늘 볼 진단: 진료 목적마다 고를 수 있는 진단(서버) · 의사가 기본과 다르게 고른 것 (진료 목적 → 진단 사건 번호)
  const [visits, setVisits] = useState<{ id: string; purposes: Record<string, VisitChoice[]> | null } | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<OpenFailure | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [progress, setProgress] = useState<LaunchProgress | null>(null);

  // 환자가 바뀌면 처음부터: 지금 연 대화의 환자면 그 목적 · 그 진단을 골라 둔다 ('돌아가기'가 되게)
  useEffect(() => {
    const cur = purposes.find((x) => x.trialId === currentTrial);
    setPurpose((cur ?? purposes[0])?.purpose ?? null);
    setChosen(cur && current?.visitChosen && current.visitEvent ? { [cur.purpose]: current.visitEvent } : {});
    setFailed(null);
    setConfirm(false);
    // 지금 연 대화가 바뀌어도(다시 받기) 고른 목적은 그대로 둔다: 환자가 바뀔 때만
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fhirId]);

  // 오늘 볼 진단 후보 (받지 못하면 고르기 없이 기본 기준 진료로 연다)
  useEffect(() => {
    if (!purposes.length) return;
    const ctl = new AbortController();
    setVisits({ id: fhirId, purposes: null });
    emrApi.visits(fhirId, ctl.signal).then(
      (x) => setVisits((v) => (v && v.id === fhirId ? { id: fhirId, purposes: x.purposes } : v)),
      () => setVisits((v) => (v && v.id === fhirId ? { id: fhirId, purposes: {} } : v)),
    );
    return () => ctl.abort();
  }, [fhirId, purposes.length]);

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

  const sel = purposes.find((x) => x.purpose === purpose) ?? null;
  const choices = (purpose && visits?.id === fhirId && visits.purposes?.[purpose]) || null;
  const defaultChoice = choices?.find((c) => c.isDefault) ?? null;
  // 기본과 다르게 고른 진단 (없으면 null = 기본 기준 진료)
  const choice = (purpose && chosen[purpose] && choices?.find((c) => c.eventId === chosen[purpose] && !c.isDefault)) || null;
  const visitEvent = choice?.eventId ?? null;
  // 진료 목적이 모두 같은 날 기준이면 날짜를 한 번만 보인다 (오늘 진단을 골랐으면 카드마다)
  const days = [...new Set(purposes.map((x) => x.visitDate))];
  const sameDay = days.length === 1 && !choice ? days[0] : null;
  const selIsCurrent = !!sel && sel.trialId === currentTrial && (current?.visitChosen ? current.visitEvent === visitEvent : visitEvent === null);
  const switching = !!current && !!sel && !selIsCurrent;

  function choose(eventId: string) {
    if (!purpose) return;
    setChosen((c) => {
      const next = { ...c };
      if (eventId === defaultChoice?.eventId) delete next[purpose];
      else next[purpose] = eventId;
      return next;
    });
    setConfirm(false);
  }

  // 환자 · 진료 목적(· 오늘 진단)을 고르고 1초쯤 머물면 첫 답을 뒤에서 미리 만들어 둔다. 결과는 화면에 알리지 않는다
  const prefetchFor = sel && !selIsCurrent ? JSON.stringify([fhirId, sel.purpose, visitEvent]) : null;
  useEffect(() => {
    if (!prefetchFor) return;
    const [id, why, ev] = JSON.parse(prefetchFor) as [string, string, string | null];
    const t = window.setTimeout(() => void emrApi.prefetch(id, why, ev), 1000);
    return () => window.clearTimeout(t);
  }, [prefetchFor]);

  async function open() {
    if (!sel) return;
    setConfirm(false);
    setFailed(null);
    setBusy(true);
    const started = Date.now();
    try {
      const r = await emrApi.launch(fhirId, sel.purpose, visitEvent);
      actions.resetAndReload();
      toast(`환자 ${identifier}로 진료 지원 AI를 열었습니다${r.seconds != null ? ` (${Math.round(r.seconds)}초)` : ''}.`);
      navigate('/');
    } catch (e) {
      const status = e instanceof ApiError ? (e.status ?? 0) : 0;
      setFailed(openFailure(status, e instanceof Error ? e.message : '진료 지원 AI를 열지 못했습니다.', (Date.now() - started) / 1000));
      // 앞단이 끊었어도 서버는 그 사이 환자를 열었을 수 있다: 지금 보는 환자 띠를 다시 받는다
      if (!status || status >= 500) actions.resetAndReload();
    } finally {
      setBusy(false);
    }
  }

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
    <section aria-labelledby="similar-title" className="flex flex-col rounded-control border border-line bg-surface">
      <header className="border-b border-line px-4 py-3">
        <h3 id="similar-title" className="flex items-center gap-1.5 text-[14px] font-bold text-ink">
          <Sparkles className="h-4 w-4 text-iris-text" aria-hidden />
          유사 사례 찾기
        </h3>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">진료 목적을 고르면 진료 지원 AI가 병원의 과거 기록에서 비슷한 사례를 찾아 보여 줍니다.</p>
      </header>
      {purposes.length === 0 ? (
        <p className="px-4 py-4 text-[13px] leading-6 text-ink-2">이 환자는 유사 사례를 찾을 진료 기록(처방 · 시술 · 경과 관리)이 없습니다. 차트만 볼 수 있습니다.</p>
      ) : (
        <>
          <div className="px-4 py-3.5">
            <p id="purpose-label" className="flex items-baseline justify-between gap-2 text-xs font-semibold text-ink-3">
              진료 목적
              {sameDay && (
                <span className="num font-normal" title={BASIS_HINT}>
                  {sameDay} 진료 기준
                </span>
              )}
            </p>
            <div role="radiogroup" aria-labelledby="purpose-label" className="mt-2 space-y-1.5">
              {purposes.map((x) => {
                const on = x.purpose === purpose;
                // 오늘 진단을 골랐으면 고른 진료 목적 카드는 그 진단의 진료일 기준으로 보인다
                const v = on && choice ? { date: choice.date, dx: choice.label, item: choice.item, co: choice.comorbidity } : { date: x.visitDate, dx: x.mainDx, item: x.item, co: x.comorbidity };
                return (
                  <label
                    key={x.trialId}
                    className={`flex cursor-pointer gap-2.5 rounded-control border px-3 py-2.5 ${on ? 'border-iris bg-iris-tint' : 'border-line hover:bg-surface-2'}`}
                  >
                    <input
                      type="radio"
                      name="purpose"
                      className="mt-1 accent-[var(--zp-iris)]"
                      checked={on}
                      onChange={() => {
                        setPurpose(x.purpose);
                        setConfirm(false);
                      }}
                    />
                    <span className="min-w-0 text-[13px]">
                      <span className="font-semibold text-ink">{x.purposeLabel}</span>
                      {!sameDay && (
                        <span className="num ml-2 text-xs text-ink-3" title={BASIS_HINT}>
                          {v.date} 진료 기준
                        </span>
                      )}
                      <span className="mt-0.5 block text-ink-2">
                        {v.dx}
                        {v.item ? ` · 고려 중: ${v.item}` : ''}
                      </span>
                      {v.co && <span className="mt-0.5 block text-xs text-ink-3">동반질환: {v.co}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
            {choices && choices.length > 1 && (
              <div className="mt-3">
                <label htmlFor="visit-pick" className="text-xs font-semibold text-ink-3">
                  오늘 볼 진단
                </label>
                <select
                  id="visit-pick"
                  value={choice?.eventId ?? defaultChoice?.eventId ?? ''}
                  onChange={(e) => choose(e.target.value)}
                  className="mt-1 h-9 w-full rounded-control border border-line-input bg-surface px-2 text-[13px] text-ink focus:border-focus"
                >
                  {choices.map((c) => (
                    <option key={c.eventId} value={c.eventId}>
                      {c.label} · {c.date}
                      {c.isDefault ? ' (기본)' : ''}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs leading-5 text-ink-3">다른 진단을 고르면 그 진료일을 기준으로 환자 요약을 만들고 비슷한 사례를 찾습니다.</p>
              </div>
            )}
          </div>
          <footer className="border-t border-line px-4 py-3.5">
            {confirm && current && (
              <div role="alertdialog" aria-labelledby="switch-title" aria-describedby="switch-desc" className="mb-2.5 rounded-control border border-caution bg-caution-tint px-3 py-2.5">
                <p id="switch-title" className="text-[13px] font-semibold text-ink">
                  지금 보는 환자를 바꿉니다
                </p>
                <p id="switch-desc" className="mt-1 text-xs leading-5 text-ink-2">
                  진료 지원 AI에 열려 있는 환자({current.ageSexLabel} · {current.primaryDiagnosis})를 닫고 {identifier} 환자로 엽니다. 지금까지의 대화는 조회 기록에 남습니다.
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
              {busy ? '진료 지원 AI를 여는 중' : !sel ? '진료 목적을 고르세요' : selIsCurrent ? '열린 진료 지원 AI로 돌아가기' : `${sel.purposeLabel} 참고로 유사 사례 찾기`}
            </button>
            {failed && !busy && (
              <div role="alert" className="mt-2.5 rounded-control border border-danger bg-danger-tint px-3 py-2.5">
                <p className="flex items-center gap-1.5 text-[13px] font-semibold text-danger-text">
                  <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
                  진료 지원 AI를 열지 못했습니다
                </p>
                <p className="mt-1 text-xs leading-5 text-ink">{failed.detail}</p>
                {failed.hint && <p className="mt-0.5 text-xs leading-5 text-ink-2">{failed.hint}</p>}
                <div className="mt-2 flex gap-2">
                  {failed.retry && (
                    <button type="button" className="btn-primary btn-sm" onClick={() => void open()}>
                      <RotateCw className="h-3.5 w-3.5" aria-hidden />
                      다시 시도
                    </button>
                  )}
                  <button type="button" className="btn-ghost btn-sm" onClick={() => setFailed(null)}>
                    닫기
                  </button>
                </div>
              </div>
            )}
            {busy && (
              <div role="status" aria-live="polite" className="mt-2.5">
                <div className="h-1 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full animate-pulse rounded-full bg-iris" style={{ width: `${Math.min(92, 18 + (progress?.calls ?? 0) * 12)}%` }} />
                </div>
                <p className="mt-1.5 text-xs leading-5 text-ink-2">{progress?.label ?? '비슷한 과거 사례를 찾고 있습니다'}</p>
                <p className="num text-[11px] text-ink-3">{Math.round(progress?.elapsed ?? 0)}초 지남</p>
              </div>
            )}
            <p className="mt-2 text-xs leading-5 text-ink-3">
              AI에는 이 환자의 요약(나이, 성별, 주진단, 동반질환, 고려 중인 처치)만 보냅니다. MediCloak은 AI가 찾아 준 과거 사례 쪽에서 나오는 값을 보호합니다.
            </p>
          </footer>
        </>
      )}
    </section>
  );
}
