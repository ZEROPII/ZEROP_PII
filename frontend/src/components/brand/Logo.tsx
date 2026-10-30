// Zero PII 마크: 같은 크기의 점 6개로 만든 숫자 0. 6은 기준 5명을 넘는 가장 작은 군중이다. 점 하나만 다르게 칠하지 않는다.
const DOTS: [number, number][] = [
  [24, 8.6],
  [33.5, 17.3],
  [33.5, 30.8],
  [24, 39.4],
  [14.5, 30.7],
  [14.5, 17.2],
];

export function LogoMark({ size = 32, className = 'text-iris-text' }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} className={className} role="img" aria-label="Zero PII">
      {DOTS.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r={4} fill="currentColor" />
      ))}
    </svg>
  );
}
