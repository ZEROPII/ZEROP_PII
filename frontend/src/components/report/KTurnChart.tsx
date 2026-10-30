// 턴별 후보 수 선 그래프 (로그 눈금). 위험 구간은 바탕 띠로, 범례 대신 선 끝에 이름과 마지막 값을 적는다.

export interface Series {
  key: string;
  name: string;
  color: string;
  values: number[];
}

interface Props {
  series: Series[];
  kReq: number;
  max?: number;
  height?: number;
  markTurn?: number | null;
  markLabel?: string;
}

const W = 840;

export function KTurnChart({ series, kReq, max: maxIn, height = 318, markTurn = null, markLabel }: Props) {
  const m = { l: 44, r: 130, t: 18, b: 34 };
  const top = Math.max(...series.flatMap((s) => s.values), 1);
  const max = maxIn ?? Math.max(200, Math.ceil((top * 1.15) / 100) * 100);
  const n = Math.max(...series.map((s) => s.values.length), 2) - 1;
  const x = (t: number) => m.l + (t / n) * (W - m.l - m.r);
  const y = (v: number) => m.t + (1 - Math.log(Math.max(v, 1)) / Math.log(max)) * (height - m.t - m.b);
  const ends = series
    .map((s) => ({ s, y: y(s.values[s.values.length - 1]) }))
    .sort((a, b) => a.y - b.y);
  // 끝 이름표가 겹치지 않게 아래로 밀어 준다
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 16) ends[i].y = ends[i - 1].y + 16;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="block h-auto w-full" role="img" aria-label="턴별 후보 수 중앙값 그래프">
      <rect x={m.l} y={y(kReq - 0.5)} width={W - m.l - m.r} height={y(1) - y(kReq - 0.5)} fill="var(--zp-danger-tint)" />
      <rect x={m.l} y={y(kReq + 0.5)} width={W - m.l - m.r} height={y(kReq - 0.5) - y(kReq + 0.5)} fill="var(--zp-caution-tint)" />
      <text x={m.l + 8} y={y(1) - 7} fontSize={11} fontWeight={650} fill="var(--zp-danger-text)">
        기준 미달 {kReq - 1}명 이하
      </text>
      <text x={W - m.r - 8} y={y(kReq) + 4} fontSize={11} fontWeight={650} textAnchor="end" fill="var(--zp-caution-text)">
        경계 {kReq}명
      </text>
      {[1, 3, 5, 10, 30, 100, 300].filter((v) => v <= max).map((v) => (
        <g key={v}>
          <line x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} stroke="var(--zp-line)" />
          <text x={m.l - 10} y={y(v) + 4} fontSize={11} textAnchor="end" fill="var(--zp-text-3)">
            {v}
          </text>
        </g>
      ))}
      {Array.from({ length: n + 1 }, (_, t) => t)
        .filter((t) => t % 2 === 0)
        .map((t) => (
          <text key={t} x={x(t)} y={height - 10} fontSize={11} textAnchor="middle" fill="var(--zp-text-3)">
            {t}턴
          </text>
        ))}
      {markTurn != null && (
        <g>
          <line x1={x(markTurn)} x2={x(markTurn)} y1={m.t} y2={height - m.b} stroke="var(--zp-text-3)" strokeDasharray="3 4" />
          {markLabel && (
            <text x={x(markTurn) + 6} y={m.t + 12} fontSize={11} fill="var(--zp-text-2)">
              {markLabel}
            </text>
          )}
        </g>
      )}
      {series.map((s) => (
        <g key={s.key}>
          <path
            d={s.values.map((v, t) => `${t ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join('')}
            fill="none"
            stroke={s.color}
            strokeWidth={2.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {s.values.map((v, t) => (
            <circle key={t} cx={x(t)} cy={y(v)} r={3.2} fill="var(--zp-surface)" stroke={s.color} strokeWidth={2}>
              <title>
                {s.name} {t}턴: {v}명
              </title>
            </circle>
          ))}
        </g>
      ))}
      {ends.map(({ s, y: yy }) => (
        <text key={s.key} x={x(n) + 12} y={yy + 4} fontSize={13} fontWeight={700} fill={s.color}>
          {s.name} {s.values[s.values.length - 1]}명
        </text>
      ))}
    </svg>
  );
}

export function BarRow({ label, value, max, text, color }: { label: string; value: number; max: number; text: string; color: string }) {
  return (
    <div>
      <div className="mb-1.5 flex justify-between gap-2 text-[13px]">
        <span>{label}</span>
        <b className="num font-bold">{text}</b>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full" style={{ width: `${value ? Math.max((value / max) * 100, 0.6) : 0}%`, background: color }} />
      </div>
    </div>
  );
}
