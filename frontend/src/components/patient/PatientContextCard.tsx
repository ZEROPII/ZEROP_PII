import { RefreshCw, UserRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useWorkspace } from '../../state/WorkspaceContext';
import type { PatientOption } from '../../types/domain';
import { Card, CardHeader } from '../common/Card';
import { MockBadge } from '../common/MockBadge';
import { ErrorState, LoadingState } from '../common/StatusViews';
import { useToast } from '../layout/Toast';

/**
 * 지금 진료 중인 환자. 의료진 화면에만 쓰는 데이터로, 질문 전송·AI 답변·사례 데이터 어디에도 섞지 않는다.
 * 데모 서버에서는 다른 질의 환자를 골라 새 대화를 시작할 수 있다.
 */
export function PatientContextCard() {
  const { state, actions, api } = useWorkspace();
  const { patient } = state;
  const toast = useToast();
  const [options, setOptions] = useState<PatientOption[]>([]);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!api.listPatients) return;
    const ctl = new AbortController();
    api.listPatients(ctl.signal).then(
      (list) => setOptions(list),
      () => undefined,
    );
    return () => ctl.abort();
  }, [api]);

  const current = patient.data?.trialId;
  useEffect(() => {
    if (current) setPick(current);
  }, [current]);

  const featured = options.filter((o) => o.featured);
  const rest = options.filter((o) => !o.featured);

  async function restart() {
    setBusy(true);
    try {
      await actions.restart(pick || undefined);
      toast(`${pick || '같은 환자'}로 새 대화를 시작했습니다.`);
    } catch {
      toast('새 대화를 시작하지 못했습니다. 서버 연결을 확인하세요.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <UserRound className="h-4 w-4 text-ink-3" aria-hidden />
            지금 진료 중인 환자
          </span>
        }
        aside={<MockBadge source={patient.data?.source} />}
      />
      {patient.status === 'error' ? (
        <ErrorState message={patient.error ?? '환자 정보를 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
      ) : !patient.data ? (
        <LoadingState compact />
      ) : (
        <>
          <dl className="space-y-2 px-4 py-3 text-[13px]">
            {[
              ['연령 / 성별', patient.data.ageSexLabel],
              ['주진단', patient.data.primaryDiagnosis],
              ['동반질환', patient.data.comorbidities.join(', ') || '없음'],
              ['고려 중 처치', patient.data.plannedProcedure],
              ['조회 목적', patient.data.queryPurpose],
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[84px_1fr] gap-2">
                <dt className="text-ink-3">{label}</dt>
                <dd className="min-w-0 break-words font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          {api.resetSession && options.length > 0 && (
            <div className="flex items-center gap-2 border-t border-line px-4 py-3">
              <label htmlFor="patient-pick" className="sr-only">
                다른 질의 환자
              </label>
              <select
                id="patient-pick"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
                className="h-[30px] min-w-0 flex-1 rounded-cell border border-line-input bg-surface px-2 text-xs text-ink"
              >
                <optgroup label="시연용">
                  {featured.map((o) => (
                    <option key={o.trialId} value={o.trialId}>
                      {o.trialId} {o.ageSex} {o.mainDx}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="전체">
                  {rest.map((o) => (
                    <option key={o.trialId} value={o.trialId}>
                      {o.trialId} {o.qtypeLabel} {o.mainDx}
                    </option>
                  ))}
                </optgroup>
              </select>
              <button type="button" onClick={restart} disabled={busy} className="btn-secondary btn-sm">
                <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} aria-hidden />
                새 대화
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
