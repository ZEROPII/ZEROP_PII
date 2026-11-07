import { Send, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { emrApi } from '../../api/emrApi';
import type { Clinician, EmrConsult, EmrMe } from '../../types/domain';

/**
 * 협진 의뢰 보내기 (ADR-0036): 담당 의료진이 차트에서 받을 의료진과 의뢰 내용(5자 이상)을 적는다.
 * 받은 의료진은 목록 위 '협진 의뢰'에서 번호 없이 연다. 보낸 일 · 연 일은 감사 기록에 남는다.
 */
export function ConsultDialog({
  fhirId,
  regno,
  policy,
  onCancel,
  onSent,
}: {
  fhirId: string;
  regno: string;
  policy: NonNullable<EmrMe['consult']>;
  onCancel(): void;
  onSent(c: EmrConsult & { created: boolean }): void;
}) {
  const [people, setPeople] = useState<Clinician[] | null>(null);
  const [to, setTo] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLSelectElement>(null);
  const text = note.trim();
  const ready = !!to && text.length >= policy.noteMin;

  useEffect(() => {
    const ctl = new AbortController();
    emrApi.directory(ctl.signal).then(
      (x) => setPeople(x),
      (e) => !(e instanceof DOMException) && setPeople([]),
    );
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    document.addEventListener('keydown', onKey);
    return () => {
      ctl.abort();
      document.removeEventListener('keydown', onKey);
    };
  }, [onCancel]);

  useEffect(() => {
    if (people) first.current?.focus();
  }, [people]);

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      onSent(await emrApi.sendConsult(fhirId, to, text));
    } catch (e) {
      setError(e instanceof Error ? e.message : '협진 의뢰를 보내지 못했습니다.');
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div role="dialog" aria-modal="true" aria-labelledby="cs-title" className="w-full max-w-[460px] rounded-overlay bg-surface p-6 shadow-overlay">
        <div className="flex items-start justify-between gap-3">
          <h2 id="cs-title" className="flex items-center gap-2 text-[17px] font-bold tracking-[-0.02em] text-ink">
            <Send className="h-[17px] w-[17px] text-iris-text" aria-hidden />
            협진 의뢰 보내기
          </h2>
          <button type="button" onClick={onCancel} className="btn-ghost -mr-2 -mt-1 h-8 w-8 px-0" aria-label="닫기">
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <p className="mt-2 text-[13px] leading-6 text-ink-2">
          <span className="num font-semibold text-ink">{regno}</span> 환자를 다른 의료진에게 의뢰합니다. 받은 의료진은 등록번호를 적지 않고 열어{' '}
          {policy.hours}시간 동안 차트와 진료 지원 AI를 씁니다. 의뢰는 {policy.days}일 동안 유효하고, 보낸 일과 연 일은 감사 기록에 남습니다.
        </p>
        <label htmlFor="cs-to" className="mt-4 block text-xs font-bold text-ink-2">
          받을 의료진
        </label>
        <select
          id="cs-to"
          ref={first}
          value={to}
          onChange={(e) => setTo(e.target.value)}
          disabled={!people || people.length === 0}
          className="mt-1.5 h-10 w-full rounded-control border border-line-input bg-surface px-2.5 text-sm text-ink outline-none focus:border-focus"
        >
          <option value="">{!people ? '불러오는 중' : people.length === 0 ? '의뢰할 수 있는 의료진이 없습니다' : '고르세요'}</option>
          {(people ?? []).map((p) => (
            <option key={p.username} value={p.username}>
              {p.displayName}
              {p.department ? ` · ${p.department}` : ''}
            </option>
          ))}
        </select>
        <label htmlFor="cs-note" className="mt-4 block text-xs font-bold text-ink-2">
          의뢰 내용
        </label>
        <textarea
          id="cs-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={300}
          rows={3}
          aria-describedby="cs-note-hint"
          placeholder="예: 당뇨 신장 합병증으로 약 조정 협진 부탁드립니다"
          className="mt-1.5 w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-sm leading-6 text-ink outline-none focus:border-focus"
        />
        <p id="cs-note-hint" className={`mt-1 text-[11.5px] ${text.length > 0 && text.length < policy.noteMin ? 'text-caution-text' : 'text-ink-3'}`}>
          {policy.noteMin}자 이상 · 받는 의료진과 보안 담당자에게 그대로 보입니다
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
            의뢰 보내기
          </button>
        </div>
      </div>
    </div>
  );
}
