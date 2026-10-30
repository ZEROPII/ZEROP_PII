import { ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { KValueBadge } from '../components/risk/KValueBadge';
import { formatDateTime } from '../lib/format';
import { useWorkspace } from '../state/WorkspaceContext';

/** 조회 기록: 이번 대화에서 사례별로 나눈 질문 수와 최신 후보 수. */
export function HistoryPage() {
  const { state, actions } = useWorkspace();
  const navigate = useNavigate();
  const { cases, sessions, riskStates } = state;

  return (
    <div className="scroll-thin mx-auto h-full max-w-3xl overflow-y-auto p-4 md:p-6">
      <Card>
        <CardHeader title="조회 기록" aside="사례별 질문과 최신 후보 수" />
        {cases.status === 'error' ? (
          <ErrorState message={cases.error ?? '사례를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
        ) : !cases.data ? (
          <LoadingState />
        ) : cases.data.length === 0 ? (
          <EmptyState message="조회한 사례가 없습니다." />
        ) : (
          <ul>
            {cases.data.map((c) => {
              const session = sessions[c.caseId]?.data;
              const risk = riskStates.data?.[c.caseId];
              const lastQuestion = [...(session?.messages ?? [])].reverse().find((m) => m.role === 'user');
              const lastText = lastQuestion?.segments.map((s) => s.text).join('');
              return (
                <li key={c.caseId} className="border-b border-line last:border-b-0">
                  <button
                    type="button"
                    onClick={() => {
                      actions.selectCase(c.caseId);
                      navigate('/');
                    }}
                    className="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-surface-2"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-[15px] font-bold text-ink">{c.label}</span>
                        <span className="truncate text-[13px] text-ink-3">{c.diagnosis}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-[13px] text-ink-2">
                        {session ? `질문 ${session.questionCount}회${lastText ? `, 마지막 질문: ${lastText}` : ''}` : '이번 대화에서 아직 열지 않았습니다'}
                      </span>
                      {risk && <span className="block text-xs text-ink-3">상태 갱신 {formatDateTime(risk.updatedAt)}</span>}
                    </span>
                    <KValueBadge risk={risk} showLabel />
                    <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
