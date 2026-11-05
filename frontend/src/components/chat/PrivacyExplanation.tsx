import { useOptionalWorkspace } from '../../state/WorkspaceContext';
import type { ProtectionResult, ReleaseCheck } from '../../types/domain';
import { ActionBadge } from '../common/ActionBadge';
import { StatusIcon } from '../common/StatusChip';

const MODE_KO: Record<string, string> = {
  RAW: '그대로 보냄',
  ROUNDED: '나이 · 날짜를 공개 단위로만 바꾼 답',
  REWRITTEN: '재작성기가 고친 답',
  REWRITTEN_FALLBACK: '값만 글자 그대로 바꾼 답',
  CASE_DROPPED: '통과하지 못한 사례를 뺀 답',
  REFUSAL: '거절 문장',
  REFUSAL_EXTRACTION_FAILED: '거절 문장 (단서 추출 실패)',
};

function caseText(ref: string | null | undefined): string {
  return ref ? ref.replace(/^사례(\d+)$/, '사례 $1') : '';
}

/** 고친 답을 다시 뽑아 확인한 기록 한 줄: 사례별 후보 수와 필요한 수, 규칙에 걸린 단서 */
function CheckLine({ c }: { c: ReleaseCheck }) {
  const why = c.cases
    .map((x) => {
      if (x.reason === 'EXTRACTION_FAILED') return '단서 추출 실패';
      if (x.reason === 'RAW_VALUE_LEFT') return `${caseText(x.case)} ${x.attributeLabel ?? '단서'} 원래 값이 그대로 남음`;
      if (x.reason === 'NO_CASE_FOUND') return '고친 답에서 사례 표기를 찾지 못함';
      if (x.reason === 'DROPPED_CASE_LEFT') return `뺀 ${caseText(x.case)}의 단서가 다시 뽑힘`;
      if (x.rule?.length) return `${caseText(x.case)} 규칙에 걸린 단서가 남음`;
      if (x.kAfter != null && x.need != null) return `${caseText(x.case)} 후보 ${x.kAfter}명 (필요 ${x.need}명 이상)`;
      return null;
    })
    .filter((x): x is string => Boolean(x));
  if (c.dropped?.length) why.unshift(`${c.dropped.map(caseText).join(', ')} 뺌`);
  return (
    <li className="flex gap-2">
      <span className="num w-10 shrink-0 text-ink-3">시도 {c.attempt}</span>
      <span className="min-w-0 flex-1">
        {c.modeLabel}
        {why.length > 0 && <span className="text-ink-3"> · {why.join(', ')}</span>}
      </span>
      <span className={`shrink-0 font-semibold ${c.ok ? 'text-safe-text' : 'text-danger-text'}`}>{c.ok ? '통과' : '통과 못함'}</span>
    </li>
  );
}

/**
 * 답변 아래 보호 처리 설명. 문장과 항목은 모두 백엔드 ProtectionResult에서 온다.
 * 보안 담당자 화면(후보 수가 있는 계약)에서는 단서마다 조치와 '그대로였다면' 후보 수, 고친 답을 다시 확인한 기록을 표로 보인다.
 */
export function PrivacyExplanation({ protection }: { protection: ProtectionResult }) {
  const changed = protection.transformations.filter((t) => t.action !== 'allow');
  const allowed = protection.transformations.length - changed.length;
  const { kBefore, kAfter } = protection;
  const numbers = kBefore != null && kAfter != null;
  const mode = protection.releaseMode ? (MODE_KO[protection.releaseMode] ?? protection.releaseMode) : null;
  const g = useOptionalWorkspace()?.state.policy.data?.minK ?? 5;

  if (!numbers) {
    // 의료진 화면 API 계약 (후보 수 없음)
    if (!changed.length)
      return (
        <p className="mt-2 flex gap-1.5 text-xs leading-5 text-ink-2">
          <StatusIcon tone="safe" className="mt-1 h-2.5 w-2.5 shrink-0 text-safe" />
          <span>{protection.explanation}</span>
        </p>
      );
    return (
      <div className="mt-2 rounded-control border border-line bg-surface-2 px-3 py-2.5 text-xs leading-5 text-ink-2">
        <p>{protection.explanation}</p>
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {changed.map((t) => (
            <li key={t.id} className="inline-flex items-center gap-1.5 rounded-cell bg-surface px-2 py-1 text-ink">
              <span className="font-semibold">{t.attributeLabel}</span>
              <ActionBadge action={t.action} />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-control border border-line bg-surface px-3 py-2.5 text-xs leading-5 text-ink-2">
      <p className="text-ink">{protection.explanation}</p>
      <dl className="num mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-ink-3">후보 수</dt>
        <dd>
          {kBefore!.toLocaleString()}명 → <b className="text-ink">{kAfter!.toLocaleString()}명</b>
          <span className="text-ink-3"> (이 답에 나간 값까지 더한 뒤)</span>
        </dd>
        {mode && (
          <>
            <dt className="text-ink-3">내보낸 답</dt>
            <dd>{mode}</dd>
          </>
        )}
      </dl>
      {changed.length > 0 && (
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left text-[11px] text-ink-3">
              <th className="border-b border-line py-1 pr-2 font-semibold">단서</th>
              <th className="border-b border-line px-2 py-1 font-semibold">조치</th>
              <th className="border-b border-line py-1 pl-2 text-right font-semibold">그대로였다면</th>
            </tr>
          </thead>
          <tbody>
            {changed.map((t) => (
              <tr key={t.id}>
                <td className="border-b border-line/70 py-1.5 pr-2 text-ink">
                  {t.attributeLabel}
                  {t.action === 'generalize' && t.disclosedValue && <span className="text-ink-3"> → {t.disclosedValue}</span>}
                </td>
                <td className="border-b border-line/70 px-2 py-1.5">
                  <span className="inline-flex items-center gap-1.5">
                    <ActionBadge action={t.action} />
                    {t.rule && <span className="text-ink-3">규칙</span>}
                    {t.dropped && <span className="text-ink-3">사례째로 뺌</span>}
                    {t.floor && <span className="text-ink-3" title="후보 수와 관계없이 나이는 5세 구간, 날짜는 월 단위로만 낸다">공개 단위</span>}
                    {t.purpose && <span className="text-ink-3" title="조회 목적에 필요 없는 단서라 후보 수와 관계없이 가린다">조회 목적</span>}
                  </span>
                </td>
                <td className="num border-b border-line/70 py-1.5 pl-2 text-right">
                  {t.kIfRaw != null ? <b className={t.kIfRaw <= g ? 'text-danger-text' : 'text-ink'}>{t.kIfRaw.toLocaleString()}명</b> : '–'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {allowed > 0 && <p className="mt-1.5 text-ink-3">그대로 낸 단서 {allowed}개</p>}
      {protection.checks && protection.checks.length > 0 && (
        <div className="mt-2 border-t border-line pt-2">
          <p className="mb-1 font-semibold text-ink-2">고친 답을 다시 뽑아 확인</p>
          <ol className="space-y-0.5">
            {protection.checks.map((c) => (
              <CheckLine key={c.attempt} c={c} />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
