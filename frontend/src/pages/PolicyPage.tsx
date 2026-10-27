import { ShieldCheck } from 'lucide-react';
import { ActionBadge } from '../components/common/ActionBadge';
import { Card, CardHeader } from '../components/common/Card';
import { MockBadge } from '../components/common/MockBadge';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useWorkspace } from '../state/WorkspaceContext';

const ARM_DESCRIPTION = {
  C0: '방어 없음: 대상 AI 답변을 그대로 내보냅니다 (비교용).',
  C1: '누적 State Defender: 사례마다 앞선 공개를 누적해 판정합니다.',
  C1S: '매 턴 빈 State로 판정하는 대조군입니다.',
} as const;

/** 보호 정책: 백엔드가 알려 준 현재 정책 값을 보여 준다 (이 화면에서 바꾸지 않음). */
export function PolicyPage() {
  const { state, actions } = useWorkspace();
  const { policy } = state;
  const p = policy.data;

  const rows: [string, string][] = p
    ? [
        ['모드', p.modeLabel],
        ['판정 방식', `${p.arm} · ${p.stateModeLabel}`],
        ['설명', ARM_DESCRIPTION[p.arm]],
        ['그대로 공개 기준', `공개 후 후보 수 k > ${p.minK}`],
        ['일반화', `원래 값으로 k ≤ ${p.minK}이면 k > ${p.minK}가 되는 가장 구체적인 상위 값으로 넓힘`],
        ['비공개', `원래 값으로 k ≤ ${p.suppressK}이면 일반화 없이 비공개`],
        ['모집단 규모', `${p.populationSize}명 (위험 막대 로그 눈금의 끝)`],
      ]
    : [];

  return (
    <div className="mx-auto h-full max-w-3xl space-y-3 overflow-y-auto p-4">
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="h-4 w-4 text-blue-600" aria-hidden />
              현재 보호 정책
            </span>
          }
          aside={<MockBadge source={p?.source} />}
        />
        {policy.status === 'error' ? (
          <ErrorState message={policy.error ?? '보호 정책을 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
        ) : !p ? (
          <LoadingState />
        ) : (
          <dl className="divide-y divide-slate-100 px-4 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="grid grid-cols-[130px_1fr] gap-3 py-2.5">
                <dt className="text-slate-500">{label}</dt>
                <dd className="text-slate-800">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      <Card>
        <CardHeader title="보호 조치 표시" />
        <ul className="space-y-2 px-4 py-3 text-sm">
          <li className="flex items-center gap-3">
            <ActionBadge action="allow" /> 수정 없이 공개된 값 (답변에서 점선 밑줄)
          </li>
          <li className="flex items-center gap-3">
            <ActionBadge action="generalize" /> 더 넓은 범위로 바꾼 값
            <mark className="rounded bg-blue-100 px-1 font-semibold text-blue-800">50~54세</mark>
          </li>
          <li className="flex items-center gap-3">
            <ActionBadge action="suppress" /> 재식별 위험으로 공개하지 않은 값 (회색 비공개 표시)
          </li>
        </ul>
        <p className="border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
          k 계산·QI 결합·누적 State 판정은 모두 백엔드가 합니다. 화면은 백엔드가 확정해 보낸 결과만 표시합니다.
        </p>
      </Card>
    </div>
  );
}
