// 후보 렌즈: 점 하나가 후보 한 명. 남은 후보(k)는 가운데에 모여 켜지고, 걸러진 후보는 바깥에서 흐려진다.
// k가 점 수(total)보다 많으면 모두 켜고 숫자로 알린다. ghost가 있으면 '가리지 않았다면 남았을 후보'를 가운데 점선 고리로 표시한다.

import type { Tone } from '../../lib/riskStyles';

const COLOR: Record<Tone, string> = {
  brand: 'var(--zp-iris)',
  safe: 'var(--zp-safe)',
  caution: 'var(--zp-caution)',
  danger: 'var(--zp-danger)',
  plain: 'var(--zp-text-3)',
};

interface Props {
  k: number;
  total?: number;
  size?: number;
  threshold?: number;
  ghost?: number | null;
  tone?: Tone;
  label?: string;
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

export function CrowdLens({ k, total = 60, size = 168, threshold, ghost = null, tone = 'brand', label }: Props) {
  const c = size / 2;
  const R = size / 2 - 6;
  const step = R / Math.sqrt(total + 0.5);
  const d = Math.max(2.2, step * 0.42);
  const pts = Array.from({ length: total }, (_, i) => {
    const r = step * Math.sqrt(i + 0.5);
    return [c + r * Math.cos(i * GOLDEN), c + r * Math.sin(i * GOLDEN)] as const;
  });
  const lit = Math.max(0, Math.min(k, total));
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label={label ?? `후보 ${k}명`} className="shrink-0">
      <circle cx={c} cy={c} r={R + 4} fill="none" stroke="var(--zp-line)" strokeWidth={1} />
      {threshold != null && threshold < total && (
        <circle cx={c} cy={c} r={step * Math.sqrt(threshold + 0.5) + d + 2} fill="none" stroke="var(--zp-text-3)" strokeWidth={1} strokeDasharray="2 4" />
      )}
      {pts.map(([x, y], i) => {
        const on = i < lit;
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={on ? d * 1.45 : d * 0.8}
            fill={on ? COLOR[tone] : 'var(--zp-text-3)'}
            opacity={on ? 1 : 0.22}
            style={{ transition: 'opacity 420ms cubic-bezier(.2,.8,.2,1), r 420ms cubic-bezier(.2,.8,.2,1)' }}
          />
        );
      })}
      {ghost != null && ghost < k && (
        <circle cx={pts[0][0]} cy={pts[0][1]} r={d * 2.6 + Math.sqrt(Math.max(ghost - 1, 0)) * step} fill="none" stroke="var(--zp-danger)" strokeWidth={1.5} strokeDasharray="3 3" />
      )}
    </svg>
  );
}

/** 표 안에 넣는 작은 후보 점 (최대 n개). */
export function MiniCrowd({ k, n = 8, tone = 'brand' }: { k: number; n?: number; tone?: Tone }) {
  return (
    <span className="inline-flex items-center gap-[3px]" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <i key={i} className="block h-1.5 w-1.5 rounded-full" style={{ background: i < k ? COLOR[tone] : 'var(--zp-line)' }} />
      ))}
    </span>
  );
}
