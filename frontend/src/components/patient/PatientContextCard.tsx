import { UserRound } from 'lucide-react';
import { useWorkspace } from '../../state/WorkspaceContext';
import { Card, CardHeader } from '../common/Card';
import { MockBadge } from '../common/MockBadge';
import { ErrorState, LoadingState } from '../common/StatusViews';

/**
 * 현재 진료 중인 환자 맥락. 의료진 화면에만 쓰는 데이터로,
 * 질문 전송·AI 응답·사례 데이터 어디에도 섞지 않는다.
 */
export function PatientContextCard() {
  const { state, actions } = useWorkspace();
  const { patient } = state;

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <UserRound className="h-4 w-4 text-blue-600" aria-hidden />
            현재 환자 맥락
          </span>
        }
        aside={<MockBadge source={patient.data?.source} />}
      />
      {patient.status === 'error' ? (
        <ErrorState message={patient.error ?? '환자 맥락을 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !patient.data ? (
        <LoadingState compact />
      ) : (
        <dl className="space-y-2 px-4 py-3 text-xs">
          {[
            ['연령 / 성별', patient.data.ageSexLabel],
            ['주진단', patient.data.primaryDiagnosis],
            ['동반질환', patient.data.comorbidities.join(', ') || '없음'],
            ['고려 중 처치', patient.data.plannedProcedure],
            ['조회 목적', patient.data.queryPurpose],
          ].map(([label, value]) => (
            <div key={label} className="grid grid-cols-[76px_1fr] gap-2">
              <dt className="text-slate-500">{label}</dt>
              <dd className="text-right font-medium text-slate-800">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
