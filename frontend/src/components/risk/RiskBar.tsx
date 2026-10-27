import { RISK_TONE } from '../../lib/riskStyles';
import type { CaseRiskState } from '../../types/domain';

/** 로그 눈금 위치(0~100%). k = 1이 왼쪽 끝, populationSize가 오른쪽 끝. */
export function logPosition(k: number, max: number): number {
  if (max <= 1) return 0;
  const clamped = Math.min(Math.max(k, 1), max);
  return (Math.log(clamped) / Math.log(max)) * 100;
}

interface Props {
  risk: CaseRiskState;
  threshold: number;
  max: number;
}

export function RiskBar({ risk, threshold, max }: Props) {
  const width = Math.max(logPosition(risk.k, max), 2);
  const marker = logPosition(threshold, max);
  return (
    <div
      className="relative h-2 rounded-full bg-slate-100"
      role="meter"
      aria-valuemin={1}
      aria-valuemax={max}
      aria-valuenow={risk.k}
      aria-valuetext={`후보 수 k ${risk.k}, ${risk.statusLabel}, 기준 k ${threshold}`}
    >
      <div className={`h-full rounded-full transition-[width] duration-500 ${RISK_TONE[risk.riskLevel].bar}`} style={{ width: `${width}%` }} />
      <span
        className="absolute -top-1 h-4 w-0.5 rounded bg-slate-700"
        style={{ left: `calc(${marker}% - 1px)` }}
        title={`기준 k = ${threshold}`}
        aria-hidden
      />
    </div>
  );
}

/** 막대 아래 로그 눈금 축 */
export function RiskAxis({ threshold, max }: { threshold: number; max: number }) {
  const ticks = [1, 10, 100, max].filter((t, i, arr) => t <= max && arr.indexOf(t) === i);
  return (
    <div className="relative mt-1 h-4 text-[10px] tabular-nums text-slate-400" aria-hidden>
      {ticks.map((t) => (
        <span key={t} className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full" style={{ left: `${logPosition(t, max)}%` }}>
          {t}
        </span>
      ))}
      <span className="absolute -translate-x-1/2 font-semibold text-slate-700" style={{ left: `${logPosition(threshold, max)}%` }}>
        {threshold}
      </span>
    </div>
  );
}
