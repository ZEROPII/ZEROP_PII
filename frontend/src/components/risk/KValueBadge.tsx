import { RISK_TONE } from '../../lib/riskStyles';
import type { CaseRiskState } from '../../types/domain';
import { StatusChip } from '../common/StatusChip';

/** 후보 수 배지. 색은 백엔드 riskLevel, 문구는 statusLabel을 따른다 (k만으로 판정하지 않음). */
export function KValueBadge({ risk, showLabel = false }: { risk: CaseRiskState | undefined; showLabel?: boolean }) {
  if (!risk) return <span className="chip bg-surface-2 text-ink-3">후보 –</span>;
  const tone = RISK_TONE[risk.riskLevel].tone;
  return (
    <StatusChip tone={tone} title={`${risk.statusLabel}, 후보 ${risk.k}명`}>
      <span className="num">
        {showLabel ? `${risk.statusLabel} ` : ''}
        {risk.k.toLocaleString()}명
      </span>
    </StatusChip>
  );
}
