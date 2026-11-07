import { useEffect, useMemo, useRef, useState } from 'react';
import { buildClueGraph, layoutGraph, uniqueClueCount, type ClueFact, type GraphNode, type Point } from '../../lib/clueGraph';

const FILL = {
  allow: 'var(--zp-text-3)',
  generalize: 'var(--zp-caution)',
  suppress: 'var(--zp-danger)',
} as const;

const ACTION_KO = { allow: '그대로', generalize: '넓힘', suppress: '가림' } as const;

function short(s: string, n = 18): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** 그래프를 담은 상자의 너비 (20px 단위로 반올림해 배치를 너무 자주 다시 하지 않는다) */
function useBoxWidth(fallback = 560) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => {
      const next = Math.round(e.contentRect.width / 20) * 20;
      if (next > 0) setW(next);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, Math.max(300, Math.min(w, 760))] as const;
}

/** 점에서 바깥쪽(dir 방향)으로 글자를 붙일 자리와 정렬 */
function labelAt(p: Point, dir: Point, gap: number) {
  const len = Math.hypot(dir.x, dir.y) || 1;
  const ux = dir.x / len;
  const uy = dir.y / len;
  return {
    x: p.x + ux * gap,
    y: p.y + uy * gap,
    anchor: (ux > 0.38 ? 'start' : ux < -0.38 ? 'end' : 'middle') as 'start' | 'end' | 'middle',
    dy: uy > 0.38 ? '0.85em' : uy < -0.38 ? '-0.25em' : '0.35em',
  };
}

/** 값 노드 모양: 그대로 원 · 넓힘 마름모 · 가림 삼각형 (상태 칩과 같은 모양, 색만으로 구분하지 않는다) */
function Shape({ n, x, y, r }: { n: GraphNode; x: number; y: number; r: number }) {
  const fill = FILL[n.action];
  if (n.action === 'generalize')
    return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} rx={1.5} transform={`rotate(45 ${x} ${y})`} fill={fill} />;
  if (n.action === 'suppress') return <path d={`M${x} ${y - r * 1.25} L${x + r * 1.2} ${y + r * 0.85} L${x - r * 1.2} ${y + r * 0.85} Z`} fill={fill} />;
  return <circle cx={x} cy={y} r={r} fill={fill} />;
}

interface Props {
  facts: ClueFact[];
  /** 강조할 사례 ('사례1'): 그 사례에만 붙은 값에 이름을 붙인다 */
  focusCase?: string | null;
  onPickCase?(caseRef: string): void;
  turnLabel?(turn: number): string;
}

/**
 * 단서 그래프: 사례(남색 원)와 답에 나간 단서 값을 잇는다 (옵시디언 그래프 보기 방식).
 * 여러 사례가 같이 가진 값은 가운데로 모이고, 한 사례에만 붙은 값은 그 사례 둘레에 남는다. 둘레 값이 많을수록 그 사례를 좁히는 단서가 쌓였다.
 * 노드에 마우스를 올리면 이웃만 밝게, 누르면 아래에 그 값이 나온 사례와 턴을 보여 준다.
 */
export function ClueGraph({ facts, focusCase = null, onPickCase, turnLabel = (t) => (t === 0 ? '검색' : `${t}턴`) }: Props) {
  const [box, W] = useBoxWidth();
  const H = Math.round(Math.max(300, Math.min(W * 0.7, 440)));
  const graph = useMemo(() => buildClueGraph(facts), [facts]);
  const pos = useMemo(() => layoutGraph(graph, { width: W, height: H }), [graph, W, H]);
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const unique = useMemo(() => uniqueClueCount(graph), [graph]);

  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const n of graph.nodes) m.set(n.id, new Set([n.id]));
    for (const l of graph.links) {
      m.get(l.source)?.add(l.target);
      m.get(l.target)?.add(l.source);
    }
    return m;
  }, [graph]);

  const active = hover ?? picked;
  const lit = active ? neighbors.get(active) : null;
  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((n) => [n.id, n])), [graph]);
  const sel = picked ? byId[picked] : null;
  const center = { x: W / 2, y: H / 2 };
  const cases = graph.nodes.filter((n) => n.kind === 'case');

  return (
    <div ref={box}>
      {!graph.nodes.length ? (
        <p className="px-4 py-8 text-center text-[13px] text-ink-3">아직 답에 나간 단서가 없습니다.</p>
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block h-auto max-w-full select-none" role="group" aria-label="사례와 단서 그래프">
            {graph.links.map((l) => {
              const a = pos[l.source];
              const b = pos[l.target];
              const on = !lit || (lit.has(l.source) && lit.has(l.target));
              return (
                <line
                  key={`${l.source}>${l.target}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={l.action === 'allow' ? 'var(--zp-line-input)' : FILL[l.action]}
                  strokeWidth={on && lit ? 1.6 : 1}
                  strokeDasharray={l.action === 'suppress' ? '3 3' : undefined}
                  opacity={on ? 0.7 : 0.1}
                />
              );
            })}
            {graph.nodes
              .filter((n) => n.kind === 'value')
              .map((n) => {
                const p = pos[n.id];
                const r = 4 + Math.min(n.cases.length, 5) * 1.6;
                const on = !lit || lit.has(n.id);
                const shared = n.cases.length > 1;
                const showLabel = shared || n.cases[0] === focusCase || (lit?.has(n.id) ?? false) || picked === n.id;
                const owner = pos[`case:${n.cases[0]}`];
                // 공유 값은 가운데에서 바깥쪽으로, 한 사례 값은 그 사례에서 바깥쪽으로 이름을 붙인다 (가운데 허브 이름과 겹치지 않게)
                const away = shared ? { x: p.x - center.x, y: p.y - center.y } : { x: p.x - owner.x, y: p.y - owner.y };
                const lab = labelAt(p, Math.hypot(away.x, away.y) < 10 ? { x: 0, y: 1 } : away, r + 5);
                const name = `${n.attribute} ${n.action === 'suppress' ? '가림' : n.label}${shared ? `, 사례 ${n.cases.length}곳` : ''}, ${ACTION_KO[n.action]}`;
                return (
                  <g
                    key={n.id}
                    tabIndex={0}
                    role="button"
                    aria-label={name}
                    aria-pressed={picked === n.id}
                    opacity={on ? 1 : 0.16}
                    className="cursor-pointer outline-none"
                    onMouseEnter={() => setHover(n.id)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(n.id)}
                    onBlur={() => setHover(null)}
                    onClick={() => setPicked((x) => (x === n.id ? null : n.id))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setPicked((x) => (x === n.id ? null : n.id));
                      }
                    }}
                  >
                    <title>{name}</title>
                    {picked === n.id && <circle cx={p.x} cy={p.y} r={r + 5} fill="none" stroke="var(--zp-focus)" strokeWidth={1.5} />}
                    <Shape n={n} x={p.x} y={p.y} r={r} />
                    {showLabel && (
                      <text
                        x={lab.x}
                        y={lab.y}
                        dy={lab.dy}
                        textAnchor={lab.anchor}
                        fontSize={11}
                        fill="var(--zp-text-2)"
                        stroke="var(--zp-surface)"
                        strokeWidth={3}
                        style={{ paintOrder: 'stroke' }}
                      >
                        {n.action === 'suppress' ? `${n.attribute} 가림` : short(n.label)}
                      </text>
                    )}
                  </g>
                );
              })}
            {cases.map((n) => {
              const p = pos[n.id];
              const ref = n.cases[0];
              const on = !lit || lit.has(n.id);
              const focus = focusCase === ref;
              const r = focus ? 16 : 14;
              const lab = labelAt(p, { x: p.x - center.x, y: p.y - center.y }, r + 6);
              return (
                <g
                  key={n.id}
                  tabIndex={0}
                  role="button"
                  aria-label={`${n.label}, 이 사례에만 나온 단서 ${unique[ref] ?? 0}개`}
                  opacity={on ? 1 : 0.25}
                  className="cursor-pointer outline-none"
                  onMouseEnter={() => setHover(n.id)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(n.id)}
                  onBlur={() => setHover(null)}
                  onClick={() => onPickCase?.(ref)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onPickCase?.(ref);
                    }
                  }}
                >
                  <title>{n.label}</title>
                  <circle cx={p.x} cy={p.y} r={r} fill="var(--zp-iris)" stroke={focus ? 'var(--zp-text)' : 'var(--zp-surface)'} strokeWidth={2} />
                  <text x={p.x} y={p.y} dy="0.35em" textAnchor="middle" fontSize={11} fontWeight={700} fill="var(--zp-on-iris)">
                    {n.label.replace(/^사례\s*/, '')}
                  </text>
                  <text
                    x={lab.x}
                    y={lab.y}
                    dy={lab.dy}
                    textAnchor={lab.anchor}
                    fontSize={12}
                    fontWeight={700}
                    fill="var(--zp-text)"
                    stroke="var(--zp-surface)"
                    strokeWidth={3}
                    style={{ paintOrder: 'stroke' }}
                  >
                    {n.label}
                  </text>
                </g>
              );
            })}
          </svg>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-[11px] text-ink-3">
            <span className="inline-flex items-center gap-1.5">
              <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden>
                <circle cx="6" cy="6" r="5" fill="var(--zp-iris)" />
              </svg>
              사례
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden>
                <circle cx="6" cy="6" r="4" fill={FILL.allow} />
              </svg>
              그대로 나간 값 (클수록 여러 사례에 공통)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden>
                <rect x="2.5" y="2.5" width="7" height="7" transform="rotate(45 6 6)" fill={FILL.generalize} />
              </svg>
              넓힌 값
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden>
                <path d="M6 1 11 10H1Z" fill={FILL.suppress} />
              </svg>
              가린 값
            </span>
          </div>

          <div className="border-t border-line px-4 py-2.5 text-[13px]">
            {sel ? (
              <p className="text-ink-2">
                <span className="font-semibold text-ink">
                  {sel.attribute} {sel.action === 'suppress' ? '(가림)' : sel.label}
                </span>
                {sel.action !== 'allow' && <span className="ml-1 text-xs text-ink-3">{ACTION_KO[sel.action]}</span>}
                <span className="ml-2">
                  {sel.cases.map((c) => c.replace(/^사례(\d+)$/, '사례 $1')).join(', ')}에 나옴, {sel.turns.map(turnLabel).join(', ')}
                </span>
              </p>
            ) : (
              <p className="text-ink-3">
                이 사례에만 나온 단서{' '}
                {cases.map((n, i) => (
                  <span key={n.id}>
                    {i > 0 && ', '}
                    <span className="text-ink-2">
                      {n.label} <span className="num font-semibold text-ink">{unique[n.cases[0]] ?? 0}개</span>
                    </span>
                  </span>
                ))}
                . 값을 누르면 어느 턴에 나갔는지 봅니다.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
