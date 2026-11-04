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
  // 후보 수는 보안 담당자 API에서만 온다. 없으면(의료진 화면 API 응답) 막대를 채우지 않는다
  const width = risk.k == null ? 0 : Math.max(logPosition(risk.k, max), 2);
  const marker = logPosition(threshold, max);
  return (
    <div
      className="relative h-2 rounded-full bg-surface-2"
      role="meter"
      aria-valuemin={1}
      aria-valuemax={max}
      aria-valuenow={risk.k ?? undefined}
      aria-valuetext={risk.k == null ? risk.statusLabel : `후보 ${risk.k}명, ${risk.statusLabel}, 기준 ${threshold}명`}
    >
      <div className={`h-full rounded-full transition-[width] duration-500 ease-zp ${RISK_TONE[risk.riskLevel].bar}`} style={{ width: `${width}%` }} />
      <span className="absolute -top-1 h-4 w-0.5 rounded bg-ink" style={{ left: `calc(${marker}% - 1px)` }} title={`기준 ${threshold}명`} aria-hidden />
    </div>
  );
}

/** 막대 아래 로그 눈금 축 */
export function RiskAxis({ threshold, max }: { threshold: number; max: number }) {
  const ticks = [1, 10, 100, max].filter((t, i, arr) => t <= max && arr.indexOf(t) === i);
  return (
    <div className="num relative mt-1 h-4 text-[11px] text-ink-3" aria-hidden>
      {ticks.map((t) => (
        <span key={t} className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full" style={{ left: `${logPosition(t, max)}%` }}>
          {t}
        </span>
      ))}
      <span className="absolute -translate-x-1/2 font-bold text-ink" style={{ left: `${logPosition(threshold, max)}%` }}>
        {threshold}
      </span>
    </div>
  );
}
