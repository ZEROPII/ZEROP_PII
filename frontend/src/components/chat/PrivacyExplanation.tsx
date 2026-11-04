import type { ProtectionResult } from '../../types/domain';
import { ActionBadge } from '../common/ActionBadge';
import { StatusIcon } from '../common/StatusChip';

/** 답변 아래 보호 처리 설명. 문장과 항목 모두 백엔드 ProtectionResult에서 온다. */
export function PrivacyExplanation({ protection }: { protection: ProtectionResult }) {
  const changed = protection.transformations.filter((t) => t.action !== 'allow');
  const { kBefore, kAfter } = protection;
  // 의료진 화면 API에서는 후보 수가 null로 온다 (그때는 후보 수 표시를 뺀다)
  const k =
    kBefore != null && kAfter != null ? (
      <span className="num whitespace-nowrap">
        후보 {kBefore.toLocaleString()}명{kBefore !== kAfter ? ` → ${kAfter.toLocaleString()}명` : ' 유지'}
      </span>
    ) : null;

  if (!changed.length) {
    return (
      <p className="mt-2 flex gap-1.5 text-xs leading-5 text-ink-2">
        <StatusIcon tone="safe" className="mt-1 h-2.5 w-2.5 shrink-0 text-safe" />
        <span>
          {protection.explanation} {k && <span className="text-ink-3">({k})</span>}
        </span>
      </p>
    );
  }

  return (
    <div className="mt-2 rounded-control border border-line bg-surface-2 px-3 py-2.5 text-xs leading-5 text-ink-2">
      <p>{protection.explanation}</p>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {changed.map((t) => (
          <li key={t.id} className="inline-flex items-center gap-1.5 rounded-cell bg-surface px-2 py-1 text-ink">
            <span className="font-semibold">{t.attributeLabel}</span>
            {t.levelDescription && <span className="text-ink-3">{t.levelDescription}</span>}
            <ActionBadge action={t.action} />
          </li>
        ))}
        {k && <li className="inline-flex items-center rounded-cell bg-surface px-2 py-1 text-ink">{k}</li>}
      </ul>
    </div>
  );
}
