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
    <div className="grid grid-cols-[120px_1fr] gap-3 py-2.5 text-[13px]">
      <dt className="text-ink-3">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  );
}

function Chips({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="text-ink-3">{empty}</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((t) => (
        <span key={t} className="rounded-cell bg-surface-2 px-1.5 py-0.5">
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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-scrim p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="policy-modal-title"
        className="max-h-[90dvh] w-full overflow-y-auto rounded-t-overlay bg-surface shadow-overlay sm:max-w-lg sm:rounded-overlay"
      >
        <header className="sticky top-0 flex items-center justify-between gap-2 border-b border-line bg-surface px-5 py-4">
          <h2 id="policy-modal-title" className="flex items-center gap-2 text-[17px] font-bold tracking-[-0.02em] text-ink">
            <Scale className="h-4 w-4 text-ink-3" aria-hidden />
            {caseLabel} 판정 근거
            {load.status === 'success' && <MockBadge source={load.data.source} />}
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="btn-ghost h-8 w-8 px-0"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="px-5 py-3">
          {load.status === 'loading' && <LoadingState label="판정 근거를 불러오는 중" />}
          {load.status === 'error' && <ErrorState message={load.message} onRetry={() => setAttempt((n) => n + 1)} />}
          {load.status === 'success' && (
            <>
              {load.data.source === 'mock' && (
                <p className="mb-2 rounded-control border border-dashed border-caution bg-caution-tint px-3 py-2 text-xs text-caution-text">
                  백엔드 판정 근거가 아직 없어 Mock Service가 만든 예시입니다. 실제 Defender 판정 결과가 아닙니다.
                </p>
              )}
              <dl className="divide-y divide-line">
                <Row label="지금 후보 수">
                  <span className="num font-bold">{load.data.currentK.toLocaleString()}명</span>
                  <span className="ml-1 text-ink-3">(상태 버전 {load.data.stateVersion})</span>
                </Row>
                <Row label="기준">
                  후보가 {load.data.minK}명보다 많으면 그대로 답합니다. 원래 값으로 {load.data.suppressK}명 이하가 되면 가리고, 그 사이는 넓혀서 답합니다.
                </Row>
                <Row label="지금까지 나간 단서">
                  <Chips items={load.data.disclosedQis.map((q) => `${q.attributeLabel} (${q.levelDescription})`)} empty="없음" />
                </Row>
                <Row label="넓혀서 답한 것">
                  <Chips items={load.data.generalized.map((q) => `${q.attributeLabel}: ${q.levelDescription}`)} empty="없음" />
                </Row>
                <Row label="가린 것">
                  <Chips items={load.data.suppressed.map((q) => q.attributeLabel)} empty="없음" />
                </Row>
                <Row label="지금 상태">
                  <span className="font-bold">{load.data.finalDecisionLabel}</span>
                  <span className="ml-1 text-ink-3">({DECISION_LABEL[load.data.finalDecision]})</span>
                </Row>
              </dl>
              {load.data.notes.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-4 text-xs leading-5 text-ink-3">
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
