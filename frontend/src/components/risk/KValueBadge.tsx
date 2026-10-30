import { RISK_TONE } from '../../lib/riskStyles';
import type { CaseRiskState } from '../../types/domain';

/** k 값 배지. 색은 백엔드 riskLevel, 문구는 statusLabel을 따른다 (k만으로 판정하지 않음). */
export function KValueBadge({ risk, showLabel = false }: { risk: CaseRiskState | undefined; showLabel?: boolean }) {
  if (!risk) {
    return <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-400">k –</span>;
  }
  const tone = RISK_TONE[risk.riskLevel];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ring-1 ring-inset ${tone.badge}`}
      title={`${risk.statusLabel} · 후보 수 k = ${risk.k}`}
    >
      {showLabel ? `${risk.statusLabel} · ` : ''}k {risk.k}
      {!showLabel && <span className="sr-only"> ({risk.statusLabel})</span>}
    </span>
  );
}
