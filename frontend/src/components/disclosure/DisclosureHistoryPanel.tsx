import { FileSearch } from 'lucide-react';
import { useState } from 'react';
import { useSelectedCase, useWorkspace } from '../../state/WorkspaceContext';
import { Card, CardHeader } from '../common/Card';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { DisclosureHistoryItem } from './DisclosureHistoryItem';
import { PolicyDecisionModal } from './PolicyDecisionModal';

export function DisclosureHistoryPanel() {
  const { actions } = useWorkspace();
  const { caseId, summary, disclosures, risk } = useSelectedCase();
  const [open, setOpen] = useState(false);
  const entries = disclosures?.data ?? [];

  return (
    <Card className="flex min-h-0 flex-col">
      <CardHeader
        title={summary ? `${summary.label}에서 나간 정보` : '나간 정보'}
        aside={entries.length ? `${entries.length}건` : undefined}
      />
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4">
        {!caseId ? (
          <EmptyState message="사례를 고르세요." />
        ) : disclosures?.status === 'error' ? (
          <ErrorState message={disclosures.error ?? '공개 내역을 불러오지 못했습니다.'} onRetry={() => actions.loadDisclosures(caseId, true)} />
        ) : disclosures?.status !== 'success' ? (
          <LoadingState compact />
        ) : entries.length === 0 ? (
          <EmptyState message="아직 이 사례에서 나간 정보가 없습니다." />
        ) : (
          <ol className="divide-y divide-line">
            {entries.map((e) => (
              <DisclosureHistoryItem key={e.entryId} entry={e} />
            ))}
          </ol>
        )}
      </div>
      <div className="shrink-0 border-t border-line p-3">
        <button type="button" onClick={() => setOpen(true)} disabled={!caseId || !risk} className="btn-secondary w-full">
          <FileSearch className="h-4 w-4" aria-hidden />
          판정 근거 보기
        </button>
      </div>
      {open && caseId && risk && (
        <PolicyDecisionModal caseId={caseId} caseLabel={summary?.label ?? caseId} stateVersion={risk.version} onClose={() => setOpen(false)} />
      )}
    </Card>
  );
}
