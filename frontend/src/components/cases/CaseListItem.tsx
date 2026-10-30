import type { CaseRiskState, CaseSummary } from '../../types/domain';
import { KValueBadge } from '../risk/KValueBadge';

interface Props {
  summary: CaseSummary;
  risk: CaseRiskState | undefined;
  selected: boolean;
  onSelect(caseId: string): void;
}

export function CaseListItem({ summary, risk, selected, onSelect }: Props) {
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => onSelect(summary.caseId)}
        aria-current={selected ? 'true' : undefined}
        className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
          selected ? 'bg-iris-tint shadow-[inset_3px_0_0_var(--zp-iris)]' : 'hover:bg-surface-2'
        }`}
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className={`text-sm font-bold ${selected ? 'text-iris-text' : 'text-ink'}`}>{summary.label}</span>
            <KValueBadge risk={risk} />
          </span>
          <span className="mt-0.5 block truncate text-[13px] text-ink" title={summary.diagnosis}>
            {summary.diagnosis}
          </span>
          <span className="block truncate text-xs text-ink-3" title={summary.description}>
            {summary.description}
            {summary.similarity != null && ` 유사도 ${summary.similarity.toFixed(2)}`}
          </span>
        </span>
      </button>
    </li>
  );
}
