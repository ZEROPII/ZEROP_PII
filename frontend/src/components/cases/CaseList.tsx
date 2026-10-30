import { useWorkspace } from '../../state/WorkspaceContext';
import { Card, CardHeader } from '../common/Card';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { CaseListItem } from './CaseListItem';

export function CaseList({ onSelected }: { onSelected?: () => void }) {
  const { state, actions } = useWorkspace();
  const { cases, riskStates, selectedCaseId } = state;

  return (
    <Card className="flex min-h-0 flex-col">
      <CardHeader
        id="case-list-title"
        title="검색된 사례"
        aside={cases.data ? `유사도 순 · ${cases.data.length}건` : undefined}
      />
      {cases.status === 'error' ? (
        <ErrorState message={cases.error ?? '사례를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !cases.data ? (
        <LoadingState compact label="유사 사례 검색 중…" />
      ) : cases.data.length === 0 ? (
        <EmptyState message="조건에 맞는 유사 사례가 없습니다." />
      ) : (
        <ul aria-labelledby="case-list-title" className="divide-y divide-slate-100 overflow-y-auto py-1">
          {cases.data.map((c) => (
            <CaseListItem
              key={c.caseId}
              summary={c}
              risk={riskStates.data?.[c.caseId]}
              selected={c.caseId === selectedCaseId}
              onSelect={(id) => {
                actions.selectCase(id);
                onSelected?.();
              }}
            />
          ))}
        </ul>
      )}
      {riskStates.status === 'error' && (
        <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-red-600">위험 상태를 불러오지 못했습니다.</p>
      )}
    </Card>
  );
}
