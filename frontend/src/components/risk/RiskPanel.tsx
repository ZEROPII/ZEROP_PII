import { useWorkspace } from '../../state/WorkspaceContext';
import { RISK_TONE } from '../../lib/riskStyles';
import { Card, CardHeader } from '../common/Card';
import { MockBadge } from '../common/MockBadge';
import { EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { CrowdLens } from '../viz/CrowdLens';
import { KValueBadge } from './KValueBadge';
import { RiskAxis, RiskBar } from './RiskBar';

/** 사례별 최신 후보 수. 고른 사례는 후보 렌즈로, 나머지는 로그 눈금 막대로. 값과 판정은 백엔드 CaseRiskState 그대로. */
export function RiskPanel() {
  const { state, actions } = useWorkspace();
  const { riskStates, cases, policy, selectedCaseId } = state;
  const threshold = policy.data?.minK ?? 5;
  const max = policy.data?.populationSize ?? 1000;
  const selected = selectedCaseId ? riskStates.data?.[selectedCaseId] : undefined;
  const selectedLabel = cases.data?.find((c) => c.caseId === selectedCaseId)?.label;

  return (
    <Card>
      <CardHeader title="재식별 위험" aside={<MockBadge source={policy.data?.source} />} />
      {riskStates.status === 'error' ? (
        <ErrorState message={riskStates.error ?? '후보 수를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !riskStates.data || !cases.data ? (
        <LoadingState compact />
      ) : cases.data.length === 0 ? (
        <EmptyState message="표시할 사례가 없습니다." />
      ) : (
        <>
          {selected && selected.k != null && (
            <div className="flex items-center gap-4 border-b border-line px-4 py-4">
              <CrowdLens k={selected.k} size={112} threshold={threshold} tone={RISK_TONE[selected.riskLevel].tone === 'safe' ? 'brand' : RISK_TONE[selected.riskLevel].tone} />
              <div className="min-w-0">
                <p className="text-xs text-ink-3">{selectedLabel}과 조건이 같은 환자</p>
                <p className="num text-[44px] font-extrabold leading-none tracking-[-0.04em]">
                  {selected.k.toLocaleString()}
                  <small className="ml-0.5 text-lg font-bold tracking-normal">명</small>
                </p>
                <p className={`mt-1.5 text-xs font-semibold ${RISK_TONE[selected.riskLevel].text}`}>
                  {selected.statusLabel}
                  <span className="ml-2 font-normal text-ink-3">기준 {threshold}명</span>
                </p>
              </div>
            </div>
          )}
          <div className="px-4 py-3">
            <ul className="space-y-1">
              {cases.data.map((c) => {
                const risk = riskStates.data?.[c.caseId];
                const isSel = c.caseId === selectedCaseId;
                return (
                  <li key={c.caseId}>
                    <button
                      type="button"
                      onClick={() => actions.selectCase(c.caseId)}
                      aria-current={isSel ? 'true' : undefined}
                      className={`w-full rounded-control px-2 py-2 text-left transition-colors ${isSel ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}
                    >
                      <span className="mb-1.5 flex items-center justify-between gap-2">
                        <span className="min-w-0">
                          <span className={`text-[13px] font-bold ${isSel ? 'text-iris-text' : 'text-ink'}`}>{c.label}</span>
                          {c.similarity != null && <span className="num ml-1.5 text-[11px] text-ink-3">유사도 {c.similarity.toFixed(2)}</span>}
                        </span>
                        <KValueBadge risk={risk} />
                      </span>
                      {risk ? <RiskBar risk={risk} threshold={threshold} max={max} /> : <span className="block h-2 rounded-full bg-surface-2" />}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="px-2">
              <RiskAxis threshold={threshold} max={max} />
            </div>
            <p className="mt-1 px-2 text-[11px] text-ink-3">로그 눈금, 세로 막대는 기준 {threshold}명</p>
          </div>
        </>
      )}
    </Card>
  );
}
