import { FileSearch, History } from 'lucide-react';
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
        title={
          <span className="inline-flex items-center gap-1.5">
            <History className="h-4 w-4 text-blue-600" aria-hidden />
            {summary ? `${summary.label} 공개 내역` : '공개 내역'}
          </span>
        }
        aside={entries.length ? `${entries.length}건` : undefined}
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        {!caseId ? (
          <EmptyState message="사례를 선택하세요." />
        ) : disclosures?.status === 'error' ? (
          <ErrorState message={disclosures.error ?? '공개 내역을 불러오지 못했습니다.'} onRetry={() => actions.loadDisclosures(caseId, true)} />
        ) : disclosures?.status !== 'success' ? (
          <LoadingState compact />
        ) : entries.length === 0 ? (
          <EmptyState message="아직 공개된 항목이 없습니다." />
        ) : (
          <ol className="divide-y divide-slate-100">
            {entries.map((e) => (
              <DisclosureHistoryItem key={e.entryId} entry={e} />
            ))}
          </ol>
        )}
      </div>
      <div className="shrink-0 border-t border-slate-100 p-3">
        <button
          type="button"
          onClick={() => setOpen(true)}
          disabled={!caseId || !risk}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <FileSearch className="h-3.5 w-3.5" aria-hidden />
          판정 근거 보기
        </button>
      </div>
      {open && caseId && risk && (
        <PolicyDecisionModal caseId={caseId} caseLabel={summary?.label ?? caseId} stateVersion={risk.version} onClose={() => setOpen(false)} />
      )}
    </Card>
  );
}
