import { ACTION_META } from '../../lib/riskStyles';
import type { PrivacyAction } from '../../types/domain';
import { StatusChip } from './StatusChip';

export function ActionBadge({ action }: { action: PrivacyAction }) {
  const meta = ACTION_META[action];
  return (
    <StatusChip tone={meta.tone} title={meta.help}>
      {meta.label}
    </StatusChip>
  );
}
