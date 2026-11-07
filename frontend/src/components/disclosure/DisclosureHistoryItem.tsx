import type { DisclosureHistoryEntry } from '../../types/domain';
import { ActionBadge } from '../common/ActionBadge';

export function DisclosureHistoryItem({ entry }: { entry: DisclosureHistoryEntry }) {
  return (
    <li className="flex items-center gap-3 py-2.5">
      <span className="num w-10 shrink-0 text-xs text-ink-3">{entry.turn === 0 ? '검색' : `${entry.turn}턴`}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold text-ink">{entry.attributeLabel}</span>
        <span className="block truncate text-xs text-ink-3" title={entry.description}>
          {entry.description}
        </span>
      </span>
      <ActionBadge action={entry.action} />
    </li>
  );
}
