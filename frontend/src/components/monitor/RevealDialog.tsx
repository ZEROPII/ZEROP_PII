import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

const REASONS = ['오탐 확인', '의료진 문의 대응', '규칙 수정 검토', '기타'];
export const NOTE_MIN = 5;

/**
 * 원문 열람: 사유를 고르고 무엇을 보려는지 한 줄로 적어야 열린다.
 * 미리 골라 둔 사유는 없다 (기본값을 누르기만 하고 여는 일을 막는다, ADR-0030).
 * 이름 · 시간 · 사유 · 적은 내용이 감사 기록에 남는다.
 */
export function RevealDialog({
  trialId,
  onCancel,
  onConfirm,
}: {
  trialId: string;
  onCancel(): void;
  onConfirm(reason: string, note: string): Promise<void>;
}) {
  const [pick, setPick] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const text = note.trim();
  const ready = pick !== null && text.length >= NOTE_MIN;

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="radio"]')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  async function submit() {
    if (!ready || pick === null) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(pick, text);
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
          가린 값과 원래 답, 환자 번호가 그대로 보입니다. 사유를 고르고 무엇을 확인하려는지 적어야 열리며, 이름 · 시간과 함께 감사 기록에 남습니다.
        </p>
        <p id="reveal-reason-label" className="mt-4 text-xs font-bold text-ink-2">
          열람 사유
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1.5" role="radiogroup" aria-labelledby="reveal-reason-label">
          {REASONS.map((r) => (
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
        <label htmlFor="reveal-note" className="mt-4 block text-xs font-bold text-ink-2">
          확인하려는 것
        </label>
        <textarea
          id="reveal-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={300}
          rows={2}
          aria-describedby="reveal-note-hint"
          placeholder="예: 사례 2 처방 가림이 오탐인지 확인"
          className="mt-1.5 w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-sm leading-6 outline-none focus:border-focus"
        />
        <p id="reveal-note-hint" className={`mt-1 text-[11.5px] ${text.length > 0 && text.length < NOTE_MIN ? 'text-caution-text' : 'text-ink-3'}`}>
          {NOTE_MIN}자 이상 · 적은 내용은 감사 기록에 그대로 남습니다
        </p>
        {error && <p className="mt-3 text-xs text-danger-text">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-ghost">
            취소
          </button>
          <button type="button" onClick={submit} disabled={busy || !ready} className="btn-primary">
            기록 남기고 보기
          </button>
        </div>
      </div>
    </div>
  );
}
