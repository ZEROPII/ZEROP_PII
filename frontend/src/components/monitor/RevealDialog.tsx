import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

const REASONS = ['오탐 확인', '의료진 문의 대응', '규칙 수정 검토'];

/** 원문 열람: 사유를 고르거나 적어야 열리고, 이름과 시간이 감사 기록에 남는다. */
export function RevealDialog({ trialId, onCancel, onConfirm }: { trialId: string; onCancel(): void; onConfirm(reason: string): Promise<void> }) {
  const [pick, setPick] = useState(REASONS[0]);
  const [custom, setCustom] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const reason = pick === '직접 입력' ? custom.trim() : pick;

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('button')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  async function submit() {
    if (reason.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason);
    } catch (e) {
      setError(e instanceof Error ? e.message : '원문을 열지 못했습니다.');
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby="reveal-title" className="w-full max-w-[480px] rounded-overlay bg-surface p-6 shadow-overlay">
        <div className="flex items-start justify-between gap-3">
          <h2 id="reveal-title" className="text-[17px] font-bold tracking-[-0.02em]">
            <span className="font-mono">{trialId}</span> 원문 보기
          </h2>
          <button type="button" onClick={onCancel} className="btn-ghost -mr-2 -mt-1 h-8 w-8 px-0" aria-label="닫기">
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <p className="mt-2 text-[13px] leading-6 text-ink-2">
          가린 값과 원래 답, 환자 번호가 그대로 보입니다. 보는 이유를 고르면 감사 기록에 이름과 시간이 함께 남습니다.
        </p>
        <div className="mt-4 flex flex-wrap gap-1.5" role="radiogroup" aria-label="열람 사유">
          {[...REASONS, '직접 입력'].map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={pick === r}
              onClick={() => setPick(r)}
              className={`h-[30px] rounded-full border px-3 text-xs ${pick === r ? 'border-iris bg-iris-tint font-bold text-iris-text' : 'border-line-input text-ink-2'}`}
            >
              {r}
            </button>
          ))}
        </div>
        {pick === '직접 입력' && (
          <input
            autoFocus
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            maxLength={200}
            placeholder="열람 사유를 적으세요 (2자 이상)"
            className="mt-3 h-10 w-full rounded-control border border-line-input bg-surface px-3 text-sm outline-none focus:border-focus"
          />
        )}
        {error && <p className="mt-3 text-xs text-danger-text">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-ghost">
            취소
          </button>
          <button type="button" onClick={submit} disabled={busy || reason.length < 2} className="btn-primary">
            기록 남기고 보기
          </button>
        </div>
      </div>
    </div>
  );
}
