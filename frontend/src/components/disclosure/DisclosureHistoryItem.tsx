import type { DisclosureHistoryEntry } from '../../types/domain';
import { ActionBadge } from '../common/ActionBadge';

export function DisclosureHistoryItem({ entry }: { entry: DisclosureHistoryEntry }) {
  return (
    <li className="flex items-center gap-2.5 py-2">
      <span className="w-9 shrink-0 text-[11px] tabular-nums text-slate-400">턴 {entry.turn}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-slate-800">{entry.attributeLabel}</span>
        <span className="block truncate text-[11px] text-slate-500" title={entry.description}>
          {entry.description}
        </span>
      </span>
      <ActionBadge action={entry.action} />
    </li>
  );
}
