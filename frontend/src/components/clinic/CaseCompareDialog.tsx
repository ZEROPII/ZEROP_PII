import { Lock, X } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { buildCaseNote, type NoteProperty } from '../../lib/caseNote';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { CaseId, ConversationSession, DisclosureHistoryEntry } from '../../types/domain';

/** 표에 보이는 순서 (노트와 같다) */
const ROWS: [string, string][] = [
  ['DX', '진단'],
  ['MED', '처방 약'],
  ['PROC', '시술'],
  ['PLAN', '관리 계획'],
  ['PERIOD', '시기'],
  ['AGE', '나이'],
  ['SEX', '성별'],
  ['REGION', '거주 지역'],
];

function Cell({ prop }: { prop: NoteProperty | undefined }) {
  if (!prop || prop.values.length === 0) return <span className="text-ink-3">–</span>;
  return (
    <span className="flex flex-col gap-0.5">
      {prop.values.map((v) =>
        v.action === 'suppress' ? (
          <span key={`s-${v.turns.join('.')}`} className="lock-token w-fit">
            <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
            비공개
          </span>
        ) : (
          <span key={`${v.action}:${v.text}`} className="break-words">
            <span className={v.action === 'generalize' ? 'range-value' : ''}>{v.text}</span>
            {v.action === 'generalize' && <span className="range-tag">범위</span>}
          </span>
        ),
      )}
    </span>
  );
}

/**
 * 사례 비교표: 사례(과거 환자 한 명씩) × 항목. 지금까지 답에 실제로 보인 값만 채운다 (사례 노트와 같은 근거).
 * 새로 묻지 않으므로 LLM을 부르지 않고, 위험 판정도 바뀌지 않는다.
 */
export function CaseCompareDialog({ onClose }: { onClose(): void }) {
  const { state, actions } = useWorkspace();
  const cases = useMemo(() => state.cases.data ?? [], [state.cases.data]);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    for (const c of cases) {
      const slot = state.disclosures[c.caseId];
      if (!slot || slot.status === 'idle') actions.loadDisclosures(c.caseId);
    }
  }, [cases, state.disclosures, actions]);

  useEffect(() => {
    box.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const allEntries = useMemo(
    () => Object.fromEntries(Object.entries(state.disclosures).map(([k, v]) => [k, v.data])) as Record<CaseId, DisclosureHistoryEntry[] | undefined>,
    [state.disclosures],
  );
  const sessions = useMemo(
    () => Object.fromEntries(Object.entries(state.sessions).map(([k, v]) => [k, v.data])) as Record<CaseId, ConversationSession | undefined>,
    [state.sessions],
  );
  const notes = useMemo(
    () =>
      cases.map((c) => {
        const entries = allEntries[c.caseId];
        const note = entries ? buildCaseNote({ caseId: c.caseId, entries, allEntries, sessions, cases }) : null;
        return { c, props: new Map((note?.properties ?? []).map((p) => [p.attribute, p])) };
      }),
    [cases, allEntries, sessions],
  );
  const rows = ROWS.filter(([attr]) => notes.some((n) => n.props.has(attr)));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-3 sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={box}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="compare-title"
        className="flex max-h-full w-full max-w-[1080px] flex-col overflow-hidden rounded-overlay bg-surface shadow-overlay outline-none"
      >
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="compare-title" className="text-[15px] font-bold text-ink">
              사례 비교
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-ink-3">
              사례 하나는 과거 환자 한 명입니다. 지금까지 AI 답에 실제로 보인 값만 채웁니다. 빈 칸(–)은 아직 묻지 않았거나 답에 나오지 않은 항목입니다.
            </p>
          </div>
          <button type="button" className="btn-ghost h-8 w-8 shrink-0 px-0" aria-label="닫기" onClick={onClose}>
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="scroll-thin min-h-0 overflow-auto">
          <table className="w-full min-w-[640px] border-collapse text-[13px]">
            <thead className="sticky top-0 bg-surface-2 text-left">
              <tr>
                <th scope="col" className="w-[110px] border-b border-line px-4 py-2 text-xs font-semibold text-ink-3">
                  항목
                </th>
                {notes.map(({ c }) => (
                  <th key={c.caseId} scope="col" className="border-b border-line px-3 py-2 align-bottom">
                    <button
                      type="button"
                      className="text-left font-bold text-ink hover:text-iris-text"
                      onClick={() => {
                        actions.selectCase(c.caseId);
                        onClose();
                      }}
                      title={`${c.label} 대화로 가기`}
                    >
                      {c.label}
                    </button>
                    <span className="num ml-1.5 text-[11px] font-normal text-ink-3">유사도 {c.similarityRank}위</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={notes.length + 1} className="px-4 py-8 text-center text-ink-3">
                    아직 답에 나온 값이 없습니다.
                  </td>
                </tr>
              ) : (
                rows.map(([attr, name]) => (
                  <tr key={attr} className="align-top">
                    <th scope="row" className="border-b border-line px-4 py-2.5 text-left text-xs font-semibold text-ink-3">
                      {name}
                    </th>
                    {notes.map(({ c, props }) => (
                      <td key={c.caseId} className="border-b border-line px-3 py-2.5 text-ink">
                        <Cell prop={props.get(attr)} />
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
