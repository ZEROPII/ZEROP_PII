import { LockKeyhole, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { emrApi } from '../../api/emrApi';
import type { EmrMe } from '../../types/domain';

/**
 * 담당 외 환자 열기 (예외 열람, ADR-0034): 환자 번호 · 사유 분류 · 직접 쓴 설명을 적어야 열린다.
 * 미리 골라 둔 사유는 없다. 연 일은 이름 · 시각 · 사유와 함께 감사 기록에 남고 보안 담당자가 검토한다.
 */
export function BreakGlassDialog({
  policy,
  onCancel,
  onOpened,
}: {
  policy: NonNullable<EmrMe['breakGlass']>;
  onCancel(): void;
  onOpened(fhirId: string, created: boolean): void;
}) {
  const reasons = policy.reasons ?? [];
  const noteMin = policy.noteMin ?? 5;
  const [number, setNumber] = useState('');
  const [pick, setPick] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const num = number.trim().toLowerCase();
  const text = note.trim();
  const numOk = /^[0-9a-f]{8}/.test(num);
  const ready = numOk && pick !== null && text.length >= noteMin;

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  async function submit() {
    if (!ready || pick === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await emrApi.breakGlass(num, pick, text);
      onOpened(r.fhirId, r.created);
    } catch (e) {
      setError(e instanceof Error ? e.message : '담당 외 환자를 열지 못했습니다.');
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div role="dialog" aria-modal="true" aria-labelledby="bg-title" className="w-full max-w-[460px] rounded-overlay bg-surface p-6 shadow-overlay">
        <div className="flex items-start justify-between gap-3">
          <h2 id="bg-title" className="flex items-center gap-2 text-[17px] font-bold tracking-[-0.02em] text-ink">
            <LockKeyhole className="h-[18px] w-[18px] text-caution-text" aria-hidden />
            담당 외 환자 열기
          </h2>
          <button type="button" onClick={onCancel} className="btn-ghost -mr-2 -mt-1 h-8 w-8 px-0" aria-label="닫기">
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <p className="mt-2 text-[13px] leading-6 text-ink-2">
          협진이나 당직처럼 담당이 아닌 환자를 꼭 봐야 할 때만 씁니다. {policy.hours ?? 12}시간 동안 차트와 진료 지원 AI를 쓸 수 있고, 연 기록은 보안 담당자가 검토합니다.
        </p>
        <label htmlFor="bg-number" className="mt-4 block text-xs font-bold text-ink-2">
          환자 번호
        </label>
        <input
          id="bg-number"
          ref={first}
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          maxLength={36}
          autoComplete="off"
          spellCheck={false}
          placeholder="앞 8자리 (예: 3f9a1c2d)"
          className="mt-1.5 h-10 w-full rounded-control border border-line-input bg-surface px-3 font-mono text-sm text-ink outline-none placeholder:font-sans placeholder:text-ink-3 focus:border-focus"
        />
        <p id="bg-reason-label" className="mt-4 text-xs font-bold text-ink-2">
          여는 사유
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1.5" role="radiogroup" aria-labelledby="bg-reason-label">
          {reasons.map((r) => (
            <button
              key={r.id}
              type="button"
              role="radio"
              aria-checked={pick === r.id}
              onClick={() => setPick(r.id)}
              className={`h-[30px] rounded-full border px-3 text-xs ${pick === r.id ? 'border-iris bg-iris-tint font-bold text-iris-text' : 'border-line-input text-ink-2'}`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <label htmlFor="bg-note" className="mt-4 block text-xs font-bold text-ink-2">
          내용
        </label>
        <textarea
          id="bg-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={300}
          rows={2}
          aria-describedby="bg-note-hint"
          placeholder="예: 호흡기내과 협진 의뢰로 처방 이력 확인"
          className="mt-1.5 w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-sm leading-6 text-ink outline-none focus:border-focus"
        />
        <p id="bg-note-hint" className={`mt-1 text-[11.5px] ${text.length > 0 && text.length < noteMin ? 'text-caution-text' : 'text-ink-3'}`}>
          {noteMin}자 이상 · 적은 내용은 감사 기록에 그대로 남습니다
        </p>
        {error && (
          <p role="alert" className="mt-3 text-xs leading-5 text-danger-text">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-ghost">
            취소
          </button>
          <button type="button" onClick={() => void submit()} disabled={busy || !ready} className="btn-primary">
            사유 남기고 열기
          </button>
        </div>
      </div>
    </div>
  );
}
