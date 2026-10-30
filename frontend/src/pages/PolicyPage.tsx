import { ActionBadge } from '../components/common/ActionBadge';
import { Card, CardHeader } from '../components/common/Card';
import { MockBadge } from '../components/common/MockBadge';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useWorkspace } from '../state/WorkspaceContext';

const ARM_DESCRIPTION = {
  C0: '방어 없음: 대상 AI 답을 그대로 내보냅니다. 비교용이며 실제 서비스에 쓰면 안 됩니다.',
  C1: '누적 방어: 대화 전체에서 나온 단서를 사례마다 모아 판정합니다. 의료진 화면은 이 방식으로 답합니다.',
  C1S: '턴별 방어: 매 턴 새로 판정하고 앞선 답은 기억하지 않습니다. 단서를 하나씩 모으는 질문에 약한지 보는 대조군입니다.',
} as const;

const TERMS: [string, string][] = [
  ['후보 수', '답에 나온 단서와 조건이 같은 환자 수. 같은 진료 사건의 진단, 나이, 날짜를 한 사람이 함께 만족해야 후보로 셉니다.'],
  ['기준 5명', '공개된 답에서 후보가 5명 아래(1~4명)로 줄면 기준 미달로 봅니다.'],
  ['사례', 'AI가 찾아 보여 준 과거 환자 기록 하나. 사례마다 후보 수를 따로 셉니다.'],
  ['턴', '질문 한 번과 답 한 번.'],
  ['레드팀 점검', '공격 질문을 자동으로 보내 방어 규칙을 시험하는 일.'],
];

/** 보호 정책: 백엔드가 알려 준 현재 정책 값과 화면에서 쓰는 말 (이 화면에서 바꾸지 않음). */
export function PolicyPage() {
  const { state, actions } = useWorkspace();
  const { policy } = state;
  const p = policy.data;

  const rows: [string, string][] = p
    ? [
        ['응답 방식', p.modeLabel],
        ['판정 방식', `${p.stateModeLabel}`],
        ['설명', ARM_DESCRIPTION[p.arm]],
        ['그대로 답함', `새 단서를 모두 더해도 후보가 ${p.minK}명보다 많을 때`],
        ['넓혀서 답함', `그 외에, 원래 값으로 후보가 ${p.suppressK}명보다 많으면 후보가 ${p.minK}명을 넘는 가장 가까운 상위 범주로`],
        ['가림', `원래 값으로 후보가 ${p.suppressK}명 이하일 때`],
        ['기준 집단', `${p.populationSize.toLocaleString()}명 (위험 막대 로그 눈금의 끝)`],
      ]
    : [];

  return (
    <div className="scroll-thin mx-auto h-full max-w-3xl space-y-3 overflow-y-auto p-4 md:p-6">
      <Card>
        <CardHeader title="지금 적용 중인 보호 정책" aside={<MockBadge source={p?.source} />} />
        {policy.status === 'error' ? (
          <ErrorState message={policy.error ?? '보호 정책을 불러오지 못했습니다.'} onRetry={actions.reloadAll} />
        ) : !p ? (
          <LoadingState />
        ) : (
          <dl className="divide-y divide-line px-4 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="grid grid-cols-[110px_1fr] gap-3 py-3">
                <dt className="text-ink-3">{label}</dt>
                <dd className="text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      <Card>
        <CardHeader title="답에 보이는 표시" />
        <ul className="space-y-3 px-4 py-4 text-sm">
          <li className="flex items-center gap-3">
            <ActionBadge action="allow" /> 그대로 답한 값은 점선 밑줄로 보입니다.
          </li>
          <li className="flex items-center gap-3">
            <ActionBadge action="generalize" /> 넓은 범주로 바꾼 값은 주의색 바탕으로 보입니다.
            <mark className="rounded-[5px] bg-caution-tint px-1 font-semibold text-caution-text">0~9세</mark>
          </li>
          <li className="flex items-center gap-3">
            <ActionBadge action="suppress" /> 가린 값은 사선 무늬 막대로 보입니다. <span className="redact" style={{ minWidth: 44 }} />
          </li>
        </ul>
        <p className="border-t border-line px-4 py-3 text-[13px] text-ink-3">
          후보 수 계산과 판정은 모두 서버가 합니다. 화면은 서버가 확정해 보낸 결과만 보여 줍니다.
        </p>
      </Card>

      <Card>
        <CardHeader title="화면에서 쓰는 말" />
        <dl className="divide-y divide-line px-4 text-sm">
          {TERMS.map(([t, d]) => (
            <div key={t} className="grid grid-cols-[110px_1fr] gap-3 py-3">
              <dt className="font-semibold text-ink">{t}</dt>
              <dd className="text-ink-2">{d}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
