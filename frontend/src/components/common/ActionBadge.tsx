import { ACTION_META } from '../../lib/riskStyles';
import type { PrivacyAction } from '../../types/domain';

export function ActionBadge({ action }: { action: PrivacyAction }) {
  const meta = ACTION_META[action];
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${meta.badge}`}>
      {meta.label}
    </span>
  );
}
