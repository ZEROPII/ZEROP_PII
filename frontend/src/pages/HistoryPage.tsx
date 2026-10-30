import { ChevronRight, History } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { KValueBadge } from '../components/risk/KValueBadge';
import { formatDateTime } from '../lib/format';
import { useWorkspace } from '../state/WorkspaceContext';

/** 조회 기록: 이번 화면 세션에서 사례별로 나눈 질문 수와 최신 누적 상태. */
export function HistoryPage() {
  const { state, actions } = useWorkspace();
  const navigate = useNavigate();
  const { cases, sessions, riskStates } = state;

  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto p-4">
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-1.5">
              <History className="h-4 w-4 text-blue-600" aria-hidden />
              조회 기록
            </span>
          }
          aside="사례별 대화와 최신 누적 k"
        />
        {cases.status === 'error' ? (
          <ErrorState message={cases.error ?? '사례를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
        ) : !cases.data ? (
          <LoadingState />
        ) : cases.data.length === 0 ? (
          <EmptyState message="조회한 사례가 없습니다." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {cases.data.map((c) => {
              const session = sessions[c.caseId]?.data;
              const risk = riskStates.data?.[c.caseId];
              const lastQuestion = [...(session?.messages ?? [])].reverse().find((m) => m.role === 'user');
              const lastText = lastQuestion?.segments.map((s) => s.text).join('');
              return (
                <li key={c.caseId}>
                  <button
                    type="button"
                    onClick={() => {
                      actions.selectCase(c.caseId);
                      navigate('/');
                    }}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800">{c.label}</span>
                        <span className="truncate text-xs text-slate-500">{c.diagnosis}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-slate-500">
                        {session ? `질문 ${session.questionCount}회${lastText ? ` · 마지막 질문: ${lastText}` : ''}` : '이번 세션에서 아직 열지 않음'}
                      </span>
                      {risk && (
                        <span className="block text-[11px] text-slate-400">
                          상태 갱신 {formatDateTime(risk.updatedAt)} · 버전 {risk.version}
                        </span>
                      )}
                    </span>
                    <KValueBadge risk={risk} showLabel />
                    <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
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
