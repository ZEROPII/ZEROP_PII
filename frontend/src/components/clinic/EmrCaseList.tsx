import { Lock, MessageSquareText } from 'lucide-react';
import { useClinicMessages } from '../../state/ClinicMessages';
import { useWorkspace } from '../../state/WorkspaceContext';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { LockedText } from './ClinicValue';

/**
 * 의료진 화면 왼쪽: AI가 찾은 비슷한 사례. 유사도 순서, 진단, 대표 항목만 보여 준다.
 * 후보 수는 보이지 않는다. 세부 정보가 제한된 사례에만 '세부 정보 제한' 표시를 붙인다.
 */
export function EmrCaseList({ onSelected }: { onSelected?: () => void }) {
  const { state, actions } = useWorkspace();
  const { cases, riskStates, selectedCaseId, sessions } = state;
  const msgs = useClinicMessages();

  return (
    <section aria-labelledby="emr-cases-title" className="panel flex min-h-0 flex-col overflow-hidden">
      <header className="border-b border-line px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="emr-cases-title" className="text-[15px] font-bold text-ink">
            비슷한 사례
          </h2>
          {cases.data && <span className="text-xs text-ink-3">유사도 순 {cases.data.length}건</span>}
        </div>
        <p className="mt-0.5 text-[11px] leading-4 text-ink-3">사례 하나는 병원 과거 기록의 환자 한 명입니다.</p>
      </header>
      {cases.status === 'error' ? (
        <ErrorState message={cases.error ?? '사례를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !cases.data ? (
        <LoadingState compact label="비슷한 사례를 찾는 중" />
      ) : cases.data.length === 0 ? (
        <EmptyState message="조건에 맞는 사례가 없습니다." />
      ) : (
        <ol className="scroll-thin min-h-0 overflow-y-auto">
          {cases.data.map((c) => {
            const sel = c.caseId === selectedCaseId;
            const risk = riskStates.data?.[c.caseId];
            const restricted = risk ? !risk.disclosureAllowed : false;
            const asked = sessions[c.caseId]?.data?.questionCount ?? 0;
            const notes = msgs.messages.filter((m) => m.caseId === c.caseId).length;
            return (
              <li key={c.caseId} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  onClick={() => {
                    actions.selectCase(c.caseId);
                    onSelected?.();
                  }}
                  aria-current={sel ? 'true' : undefined}
                  className={`grid w-full grid-cols-[26px_minmax(0,1fr)] gap-2.5 px-3.5 py-3 text-left transition-colors ${
                    sel ? 'bg-iris-tint shadow-[inset_3px_0_0_var(--zp-iris)]' : 'hover:bg-surface-2'
                  }`}
                >
                  <span
                    className={`num mt-px grid h-[22px] w-[22px] place-items-center rounded-full text-[11px] font-bold ${sel ? 'bg-iris text-iris-on' : 'bg-surface-2 text-ink-2'}`}
                    aria-label={`유사도 ${c.similarityRank}위`}
                  >
                    {c.similarityRank}
                  </span>
                  <span className="min-w-0">
                    <span className={`block text-sm font-bold ${sel ? 'text-iris-text' : 'text-ink'}`}>{c.label}</span>
                    <span className="block truncate text-[13px] text-ink" title={c.diagnosis}>
                      {c.diagnosis}
                    </span>
                    <span className="block truncate text-xs text-ink-3" title={c.description.replace('(비공개)', '비공개')}>
                      <LockedText text={c.description} />
                    </span>
                    {(restricted || asked > 0 || notes > 0) && (
                      <span className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                        {restricted && (
                          <span className="inline-flex items-center gap-1 rounded-[5px] bg-emr-lock-tint px-1.5 py-px font-semibold text-emr-lock" title="새로 묻는 세부 값은 범위로 보이거나 비공개로 표시될 수 있습니다">
                            <Lock className="h-3 w-3" aria-hidden /> 세부 정보 제한
                          </span>
                        )}
                        {asked > 0 && <span className="rounded-[5px] bg-surface-2 px-1.5 py-px text-ink-2">질문 {asked}회</span>}
                        {notes > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-[5px] bg-surface-2 px-1.5 py-px text-ink-2">
                            <MessageSquareText className="h-3 w-3" aria-hidden /> 메시지 {notes}
                          </span>
                        )}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
