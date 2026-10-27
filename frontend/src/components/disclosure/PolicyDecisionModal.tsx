import { Scale, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { DECISION_LABEL } from '../../lib/riskStyles';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, PolicyDecisionRationale } from '../../types/domain';
import { MockBadge } from '../common/MockBadge';
import { ErrorState, LoadingState } from '../common/StatusViews';

interface Props {
  caseId: CaseId;
  caseLabel: string;
  /** 누적 상태가 바뀌면 근거를 다시 받는다. */
  stateVersion: number;
  onClose(): void;
}

type LoadState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'success'; data: PolicyDecisionRationale };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-3 py-2 text-xs">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children}</dd>
    </div>
  );
}

function Chips({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="text-slate-400">{empty}</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((t) => (
        <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5">
          {t}
        </span>
      ))}
    </span>
  );
}

/** 판정 근거. 백엔드가 공개 가능하다고 준 요약만 표시한다 (원본 값·내부 계산 세부는 받지 않음). */
export function PolicyDecisionModal({ caseId, caseLabel, stateVersion, onClose }: Props) {
  const { api } = useWorkspace();
  const [load, setLoad] = useState<LoadState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoad({ status: 'loading' });
    api.getPolicyDecision(caseId, controller.signal).then(
      (data) => setLoad({ status: 'success', data }),
      (error) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setLoad({ status: 'error', message: error instanceof Error ? error.message : '판정 근거를 불러오지 못했습니다.' });
      },
    );
    return () => controller.abort();
  }, [api, caseId, stateVersion, attempt]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab' && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>('button, [href], [tabindex]:not([tabindex="-1"])');
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="policy-modal-title"
        className="max-h-[90dvh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:max-w-lg sm:rounded-2xl"
      >
        <header className="sticky top-0 flex items-center justify-between gap-2 border-b border-slate-100 bg-white px-5 py-3.5">
          <h2 id="policy-modal-title" className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Scale className="h-4 w-4 text-blue-600" aria-hidden />
            {caseLabel} 판정 근거
            {load.status === 'success' && <MockBadge source={load.data.source} />}
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="px-5 py-3">
          {load.status === 'loading' && <LoadingState label="판정 근거를 불러오는 중…" />}
          {load.status === 'error' && <ErrorState message={load.message} onRetry={() => setAttempt((n) => n + 1)} />}
          {load.status === 'success' && (
            <>
              {load.data.source === 'mock' && (
                <p className="mb-2 rounded-md border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
                  백엔드 판정 근거가 아직 없어 Mock Service가 만든 예시입니다. 실제 Defender 판정 결과가 아닙니다.
                </p>
              )}
              <dl className="divide-y divide-slate-100">
                <Row label="현재 k">
                  <span className="font-semibold tabular-nums">{load.data.currentK}</span>
                  <span className="ml-1 text-slate-500">(상태 버전 {load.data.stateVersion})</span>
                </Row>
                <Row label="최소 허용 k">
                  그대로 공개는 k &gt; {load.data.minK} · 원래 값 k ≤ {load.data.suppressK}이면 비공개 · 판정 방식 {load.data.arm}
                </Row>
                <Row label="공개된 QI">
                  <Chips items={load.data.disclosedQis.map((q) => `${q.attributeLabel} (${q.levelDescription})`)} empty="없음" />
                </Row>
                <Row label="일반화 조치">
                  <Chips items={load.data.generalized.map((q) => `${q.attributeLabel}: ${q.levelDescription}`)} empty="없음" />
                </Row>
                <Row label="비공개 항목">
                  <Chips items={load.data.suppressed.map((q) => q.attributeLabel)} empty="없음" />
                </Row>
                <Row label="Defender 최종 판정">
                  <span className="font-semibold">{load.data.finalDecisionLabel}</span>
                  <span className="ml-1 text-slate-500">({DECISION_LABEL[load.data.finalDecision]})</span>
                </Row>
              </dl>
              {load.data.notes.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] text-slate-500">
                  {load.data.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
