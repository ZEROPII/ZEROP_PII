import { RISK_TONE } from '../../lib/riskStyles';
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
    <li>
      <button
        type="button"
        onClick={() => onSelect(summary.caseId)}
        aria-current={selected ? 'true' : undefined}
        className={`group flex w-full items-start gap-2.5 border-l-[3px] px-4 py-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500 ${
          selected ? 'border-blue-600 bg-blue-50' : 'border-transparent hover:bg-slate-50'
        }`}
      >
        <span
          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${risk ? RISK_TONE[risk.riskLevel].dot : 'bg-slate-300'}`}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className={`text-[13px] font-semibold ${selected ? 'text-blue-700' : 'text-slate-800'}`}>{summary.label}</span>
            <KValueBadge risk={risk} />
          </span>
          <span className="mt-0.5 block truncate text-xs text-slate-700">{summary.diagnosis}</span>
          <span className="block truncate text-[11px] text-slate-500">{summary.description}</span>
          {risk && <span className={`mt-0.5 block text-[11px] font-medium ${RISK_TONE[risk.riskLevel].text}`}>{risk.statusLabel}</span>}
        </span>
      </button>
    </li>
  );
}
