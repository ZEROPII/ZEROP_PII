import { Gauge } from 'lucide-react';
import { useWorkspace } from '../../state/WorkspaceContext';
import { Card, CardHeader } from '../common/Card';
import { MockBadge } from '../common/MockBadge';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { KValueBadge } from './KValueBadge';
import { RiskAxis, RiskBar } from './RiskBar';

/** 사례별 최신 누적 k. 값과 판정은 백엔드 CaseRiskState를 그대로 표시한다. */
export function RiskPanel() {
  const { state, actions } = useWorkspace();
  const { riskStates, cases, policy, selectedCaseId } = state;
  const threshold = policy.data?.minK ?? 5;
  const max = policy.data?.populationSize ?? 1000;

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <Gauge className="h-4 w-4 text-blue-600" aria-hidden />
            재식별 위험
          </span>
        }
        aside="사례별 후보 수 k"
      />
      {riskStates.status === 'error' ? (
        <ErrorState message={riskStates.error ?? '위험 상태를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !riskStates.data || !cases.data ? (
        <LoadingState compact />
      ) : cases.data.length === 0 ? (
        <EmptyState message="표시할 사례가 없습니다." />
      ) : (
        <div className="px-4 py-3">
          <ul className="space-y-1">
            {cases.data.map((c) => {
              const risk = riskStates.data?.[c.caseId];
              const selected = c.caseId === selectedCaseId;
              return (
                <li key={c.caseId}>
                  <button
                    type="button"
                    onClick={() => actions.selectCase(c.caseId)}
                    aria-current={selected ? 'true' : undefined}
                    className={`w-full rounded-lg px-2 py-2 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 ${
                      selected ? 'bg-blue-50 ring-1 ring-inset ring-blue-200' : 'hover:bg-slate-50'
                    }`}
                  >
                    <span className="mb-1.5 flex items-center justify-between gap-2">
                      <span className={`text-xs font-semibold ${selected ? 'text-blue-700' : 'text-slate-700'}`}>{c.label}</span>
                      <KValueBadge risk={risk} showLabel />
                    </span>
                    {risk ? <RiskBar risk={risk} threshold={threshold} max={max} /> : <span className="block h-2 rounded-full bg-slate-100" />}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="px-2">
            <RiskAxis threshold={threshold} max={max} />
          </div>
          <p className="mt-1 flex items-center justify-between gap-2 px-2 text-[10px] text-slate-500">
            <span>
              로그 눈금 · <span className="inline-block h-2 w-0.5 bg-slate-700 align-middle" /> 기준 k = {threshold}
            </span>
            <MockBadge source={policy.data?.source} />
          </p>
        </div>
      )}
    </Card>
  );
}
