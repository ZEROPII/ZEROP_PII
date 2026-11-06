import { useCallback, useEffect, useState } from 'react';
import { apiMode } from '../api';
import { MOCK_POLICY } from '../api/mock/mockData';
import { MONITOR_UNAVAILABLE, monitorApi } from '../api/monitorApi';
import { ActionBadge } from '../components/common/ActionBadge';
import { Card, CardHeader } from '../components/common/Card';
import { MockBadge } from '../components/common/MockBadge';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import type { ProtectionPolicy } from '../types/domain';
import type { MonitorPolicy } from '../types/monitor';

const ARM_DESCRIPTION = {
  C0: '방어 없음: 대상 AI 답을 그대로 내보냅니다. 비교용이며 실제 서비스에 쓰면 안 됩니다.',
  C1: '누적 방어: 대화 전체에서 나온 단서를 사례마다 모아 판정합니다. 의료진 화면은 이 방식으로 답합니다.',
  C1S: '턴별 방어: 매 턴 새로 판정하고 앞선 답은 기억하지 않습니다. 단서를 하나씩 모으는 질문에 약한지 보는 대조군입니다.',
} as const;

const ROLE_KO: Record<string, string> = { target: '대상 AI', extractor: '추출기', rewriter: '재작성기', reviewer: '검토 보조' };

function usageText(u: NonNullable<MonitorPolicy['llmUsage']>): string {
  const roles = Object.entries(u.by_role);
  if (!roles.length) return '아직 호출 없음';
  const tin = roles.reduce((s, [, v]) => s + v.input_tokens, 0);
  const tout = roles.reduce((s, [, v]) => s + v.output_tokens, 0);
  return `${roles.map(([r, v]) => `${ROLE_KO[r] ?? r} ${v.calls}회`).join(' · ')} (입력 ${tin.toLocaleString()} · 출력 ${tout.toLocaleString()} 토큰)`;
}

const TERMS: [string, string][] = [
  ['후보 수', '한 사례(과거 환자 한 명)에 대해 지금까지 답에 나온 단서를 모두 만족하는 과거 기록 환자 수. 같은 진료 사건의 진단, 나이, 날짜를 한 사람이 함께 만족해야 후보로 셉니다. 1명이면 그 사례가 누구인지 특정됩니다.'],
  ['기준 5명', '공개된 답에서 후보가 5명 아래(1~4명)로 줄면 기준 미달로 봅니다.'],
  ['사례', 'AI가 찾아 보여 준 과거 환자 한 명의 기록. 사례마다 후보 수를 따로 세고, 대화가 이어지는 동안 그 사람에 대해 나온 단서를 모두 합쳐 셉니다.'],
  ['턴', '질문 한 번과 답 한 번.'],
  ['레드팀 점검', '공격 질문을 자동으로 보내 방어 규칙을 시험하는 일.'],
];

/** 의료진 대화 보강 (ADR-0032) 한 줄씩 */
function protectionRows(x: NonNullable<MonitorPolicy['protections']>): [string, string][] {
  const out: [string, string][] = [];
  const l = x.ledger;
  out.push([
    '공개 원장',
    l.on
      ? `켬: 같은 과거 환자에 대해 다른 대화 · 다른 의료진에게 공개된 값${l.windowDays ? `(최근 ${l.windowDays}일)` : ''}까지 합쳐 후보 수를 셈${l.persistent ? ', DB에 남김' : ', 메모리에만'}`
      : '끔 (--ledger off): 후보 수는 대화마다 따로 셈',
  ]);
  out.push([
    '입력 단계 게이팅',
    x.inputGate.on
      ? '켬: 대상 AI에 사례 기록을 넣기 전에 값마다 판정해, 가릴 값은 (비공개), 넓힐 값은 상위 범주, 횟수는 범위로 넣음 (실제 LLM 의료진 대화)'
      : '끔 (--input-gate off): 대상 AI에는 사례 기록 원문이 들어가고, 답을 공개하기 전에만 고침',
  ]);
  out.push(['답 시간 한도', x.answerBudgetSec ? `${x.answerBudgetSec}초: 넘기면 확인하지 못한 답 대신 안내 문장 (실제 LLM 의료진 대화)` : '없음 (--answer-budget 0)']);
  const s = x.sensitivity;
  out.push([
    '민감 정보',
    s.on
      ? `켬: ${(s.categories ?? []).filter((c) => c.grade >= 2).map((c) => c.name).join(', ')} 값은 후보가 ${s.strictK}명 이상일 때만 공개${s.excludedPatients ? `, 미성년 물질 사용 기록 환자 ${s.excludedPatients}명은 사례 검색에서 뺌` : ''}`
      : '끔 (--sensitivity off)',
  ]);
  return out;
}

/**
 * 보호 정책: 백엔드가 알려 준 현재 정책 값과 화면에서 쓰는 말 (이 화면에서 바꾸지 않음).
 * 기준값은 의료진 화면 API에서 지워지므로 보안 담당자 API(/api/monitor/policy)에서 받는다.
 */
export function PolicyPage() {
  const [p, setP] = useState<(ProtectionPolicy & Partial<MonitorPolicy>) | null>(apiMode === 'http' ? null : MOCK_POLICY);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (apiMode !== 'http') return;
    setError(null);
    monitorApi.policy().then(setP, (e) => setError(e instanceof Error ? e.message : MONITOR_UNAVAILABLE));
  }, []);
  useEffect(load, [load]);

  const rows: [string, string][] = p
    ? [
        ['응답 방식', p.modeLabel],
        ['판정 방식', `${p.stateModeLabel}`],
        ['설명', ARM_DESCRIPTION[p.arm]],
        ['그대로 답함', `새 단서를 모두 더해도 후보가 ${p.minK}명보다 많을 때`],
        ['넓혀서 답함', `그 외에, 원래 값으로 후보가 ${p.suppressK}명보다 많으면 후보가 ${p.minK}명을 넘는 가장 가까운 상위 범주로`],
        ['가림', `원래 값으로 후보가 ${p.suppressK}명 이하일 때`],
        ['기준 집단', `${(p.populationSize ?? 0).toLocaleString()}명 (후보 수 로그 눈금의 오른쪽 끝)`],
        ...(p.auth !== undefined
          ? ([
              ['비교 갈래', p.compare ? '방어 없음(C0)은 바로, 턴별 방어(C1S)는 의료진 답을 보낸 뒤 계산' : '계산하지 않음 (--no-compare)'],
              ['서버', `${p.auth ? '로그인 · 역할 분리' : '로그인 없는 데모'} · ${p.persist ? '기록을 DB에 남김' : '기록은 메모리에만 (다시 켜면 지워짐)'}`],
              ...(p.llmLive
                ? ([
                    ['날짜 · 나이 규칙 추출', p.ruleExtract ? '켬: 추출기가 놓친 날짜 · 나이도 답에서 찾아 단서로 셈 (의료진 대화 · 레드팀)' : '끔 (--no-rule-extract)'],
                    [
                      '대상 AI 답 형식',
                      p.answerStyle
                        ? '짧게: 사례마다 두세 문장, 표 · 머리글 없이, 묻지 않은 날짜 · 나이는 덧붙이지 않음 (의료진 대화 · 레드팀 같은 설정)'
                        : '지시 없음 (--answer-style off)',
                    ],
                    ['공개 단위', '나이는 5세 구간, 날짜는 월보다 자세히 내지 않음 (공개 승인한 값은 예외)'],
                    ['조회 목적', '거주 지역은 어느 조회 목적(처방 · 시술·치료 · 경과·관리)에도 쓰지 않아 후보 수와 관계없이 가림, 공개 승인 대상도 아님 (의료진 대화 · 레드팀)'],
                  ] as [string, string][])
                : []),
              ...(p.protections ? protectionRows(p.protections) : []),
              ['검토 반영', '규칙(이 대화에서 사례 · 단서는 늘 가림), 세부 정보 요청 승인 공개 (사유 · 감사 기록)'],
              ['검토 보조', '세부 정보 요청마다 검토 초안: 추천은 규칙(후보 수 · 조회 목적), 요약 · 답장 문장은 실제 LLM. 보내는 것은 담당자'],
              ...(p.autoRedteam
                ? ([
                    [
                      '자동 레드팀 점검',
                      [p.autoRedteam.onChange ? '설정이 바뀌면 켤 때 유형마다 1명' : null, p.autoRedteam.daily ? `매일 ${p.autoRedteam.daily}` : null]
                        .filter(Boolean)
                        .join(' · ') || '끔',
                    ],
                    ['이번에 켤 때', p.autoRedteam.decisionText],
                  ] as [string, string][])
                : []),
              ...(p.llmUsage ? ([['LLM 호출', `서버를 켠 뒤 ${usageText(p.llmUsage)}`]] as [string, string][]) : []),
            ] as [string, string][])
          : []),
      ]
    : [];

  return (
    <div className="scroll-thin mx-auto h-full max-w-3xl space-y-3 overflow-y-auto p-4 md:p-6">
      <Card>
        <CardHeader title="지금 적용 중인 보호 정책" aside={<MockBadge source={p?.source} />} />
        {error ? (
          <ErrorState message={error} onRetry={load} />
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
