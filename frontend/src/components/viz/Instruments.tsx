// 보안 담당자 화면의 후보 수 계기. 모든 표시가 숫자 하나에 대응한다 (장식 점 · 그림 없음).
//
//   눈금: 로그 눈금. 1이 왼쪽 끝, 기준 집단(461명)이 오른쪽 끝. 후보가 줄면 표시가 왼쪽으로 간다.
//   기준선: 넓힘 기준(5명, 진한 선)과 가림 기준(3명, 점선)을 모든 줄에 같은 자리에 긋는다.
//   줄 하나 = 단서 하나: 이 단서가 더해지기 전 → 뒤의 후보 수를 막대로, 뒤의 값을 점으로.
//   가린 값: 그대로 냈다면 내려갔을 자리를 빨간 고리와 점선으로 (실제로는 내려가지 않았다).

import type { ReactNode } from 'react';
import type { Narrowing } from '../../types/monitor';

export function logPos(k: number, max: number): number {
  if (max <= 1) return 0;
  const c = Math.min(Math.max(k, 1), max);
  return (Math.log(c) / Math.log(max)) * 100;
}

function ticksFor(max: number, g: number, s: number): number[] {
  return [...new Set([1, s, g, 10, 50, 100, max])].filter((t) => t >= 1 && t <= max).sort((a, b) => a - b);
}

function where(turn: number | null): string {
  if (turn == null) return '승인';
  return turn === 0 ? '검색' : `질문 ${turn}`;
}

/** 기준선 두 개 (넓힘 기준 g · 가림 기준 s). 부모가 relative여야 한다. */
function Guides({ max, g, s }: { max: number; g: number; s: number }) {
  return (
    <>
      <span aria-hidden className="absolute inset-y-0 w-px border-l border-dashed border-ink-3/70" style={{ left: `${logPos(s, max)}%` }} />
      <span aria-hidden className="absolute inset-y-0 w-px bg-ink" style={{ left: `${logPos(g, max)}%` }} />
    </>
  );
}

type Mark =
  | { kind: 'step'; from: number; to: number; tone: 'iris' | 'caution' }
  | { kind: 'blocked'; at: number; raw: number }
  | { kind: 'point'; at: number };

function Track({ mark, max, g, s }: { mark: Mark; max: number; g: number; s: number }) {
  const dot = (k: number, cls: string) => (
    <span aria-hidden className={`absolute top-1/2 h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full ${cls}`} style={{ left: `${logPos(k, max)}%` }} />
  );
  return (
    <div className="relative h-3.5">
      <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-line" />
      <Guides max={max} g={g} s={s} />
      {mark.kind === 'step' && (
        <>
          <span
            aria-hidden
            className={`absolute top-1/2 h-[5px] -translate-y-1/2 rounded-full ${mark.tone === 'caution' ? 'bg-caution/40' : 'bg-iris/30'}`}
            style={{ left: `${logPos(mark.to, max)}%`, width: `${Math.max(logPos(mark.from, max) - logPos(mark.to, max), 0.8)}%` }}
          />
          {dot(mark.to, mark.to <= g ? 'bg-danger' : mark.tone === 'caution' ? 'bg-caution' : 'bg-iris')}
        </>
      )}
      {mark.kind === 'blocked' && (
        <>
          <span
            aria-hidden
            className="absolute top-1/2 h-0 -translate-y-1/2 border-t border-dashed border-danger"
            style={{ left: `${logPos(mark.raw, max)}%`, width: `${Math.max(logPos(mark.at, max) - logPos(mark.raw, max), 0.8)}%` }}
          />
          {dot(mark.raw, 'border-[1.5px] border-danger bg-surface')}
        </>
      )}
      {mark.kind === 'point' && dot(mark.at, mark.at <= g ? 'bg-danger' : 'bg-ink')}
    </div>
  );
}

function Axis({ max, g, s }: { max: number; g: number; s: number }) {
  return (
    <div aria-hidden className="num relative mt-1 h-4 text-[10.5px] leading-4 text-ink-3">
      {ticksFor(max, g, s).map((t) => (
        <span
          key={t}
          className={`absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full ${t === g ? 'font-bold text-ink' : ''}`}
          style={{ left: `${logPos(t, max)}%` }}
        >
          {t}
        </span>
      ))}
    </div>
  );
}

function Row({ label, sub, num, numTone, children }: { label: ReactNode; sub?: ReactNode; num: ReactNode; numTone?: string; children: ReactNode }) {
  return (
    <li className="py-1.5">
      <div className="flex items-baseline gap-2 text-xs">
        <span className="min-w-0 flex-1 truncate text-ink">
          {sub && <span className="mr-1.5 text-ink-3">{sub}</span>}
          {label}
        </span>
        <span className={`num shrink-0 whitespace-nowrap ${numTone ?? 'text-ink-2'}`}>{num}</span>
      </div>
      <div className="mt-1">{children}</div>
    </li>
  );
}

export type LadderRow = { kind: 'step'; index: number; place: number } | { kind: 'hidden'; index: number; place: number; at: number };

/** 승인 공개는 턴이 아니다: 공개한 턴 바로 뒤 자리(턴 + 0.5)에 놓는다 */
function placeOf(st: Narrowing['steps'][number]): number {
  return st.approved ? (st.afterTurn ?? Number.MAX_SAFE_INTEGER - 1) + 0.5 : (st.turn ?? Number.MAX_SAFE_INTEGER);
}

/**
 * 계기 줄 순서: 턴 순서로, 같은 턴에서는 공개된 단서 다음에 가린 값. 가린 값의 at은 그 턴까지 쌓인 후보 수
 * (그대로 냈다면 여기서 내려갔을 것이다).
 */
export function ladderRows(data: Narrowing): LadderRow[] {
  const rows: (LadderRow & { order: number })[] = data.steps.map((st, i) => ({ kind: 'step' as const, index: i, place: placeOf(st), order: i }));
  data.hidden.forEach((h, i) => {
    const before = data.steps.filter((st) => placeOf(st) <= h.turn).pop();
    rows.push({ kind: 'hidden', index: i, place: h.turn, at: before ? before.kAfter : data.population, order: 10_000 + i });
  });
  rows.sort((a, b) => a.place - b.place || a.order - b.order);
  return rows.map(({ order: _o, ...r }) => r);
}

/**
 * 후보가 줄어든 과정: 기준 집단에서 시작해 공개된 단서를 쌓인 순서대로 하나씩 더하며 센 후보 수.
 * 가린 값은 그 턴 자리에 '그대로였다면'으로 함께 놓는다 (State에는 더해지지 않았다).
 */
export function NarrowingLadder({ data, labelOf }: { data: Narrowing; labelOf?: (attribute: string, fallback: string) => string }) {
  const { population: max, generalizeK: g, suppressK: s } = data;
  const lab = (a: string, f: string) => (labelOf ? labelOf(a, f) : f);
  const kNow = data.steps.length ? data.steps[data.steps.length - 1].kAfter : max;
  const nodes = ladderRows(data).map((row) => {
    if (row.kind === 'step') {
      const st = data.steps[row.index];
      return (
        <Row
          key={`s${row.index}`}
          sub={st.approved ? (st.afterTurn != null ? `${where(st.afterTurn)} 뒤 승인` : '승인 공개') : where(st.turn)}
          label={
            <>
              <span className="text-ink-2">{lab(st.attribute, st.attributeLabel)}</span> <span className="font-semibold">{st.value}</span>
            </>
          }
          num={
            <>
              {st.kBefore.toLocaleString()} → <b className={st.kAfter <= g ? 'text-danger-text' : 'text-ink'}>{st.kAfter.toLocaleString()}</b>
            </>
          }
        >
          <Track mark={{ kind: 'step', from: st.kBefore, to: st.kAfter, tone: st.approved ? 'caution' : 'iris' }} max={max} g={g} s={s} />
        </Row>
      );
    }
    const h = data.hidden[row.index];
    return (
      <Row
        key={`h${row.index}`}
        sub={where(h.turn)}
        label={
          <>
            <span className="text-ink-2">{lab(h.attribute, h.attributeLabel)}</span>{' '}
            <span className="font-semibold text-danger-text">{h.released ? '가렸다가 승인 공개' : h.dropped ? '사례째로 뺌' : h.action === 'generalize' ? '넓힘' : '가림'}</span>
          </>
        }
        num={h.kIfRaw != null ? <>그대로면 <b className="text-danger-text">{h.kIfRaw.toLocaleString()}</b></> : '–'}
      >
        {h.kIfRaw != null ? <Track mark={{ kind: 'blocked', at: row.at, raw: h.kIfRaw }} max={max} g={g} s={s} /> : <div className="h-3.5" />}
      </Row>
    );
  });

  return (
    <div>
      <ul className="divide-y divide-line/70">
        <Row sub="시작" label={<span className="text-ink-2">기준 집단 (과거 기록 환자 전체)</span>} num={<b className="text-ink">{max.toLocaleString()}</b>}>
          <Track mark={{ kind: 'point', at: max }} max={max} g={g} s={s} />
        </Row>
        {nodes}
      </ul>
      <Axis max={max} g={g} s={s} />
      <p className="mt-1.5 text-[11px] leading-4 text-ink-3">
        로그 눈금. 진한 세로선 = 넓힘 기준 {g}명, 점선 = 가림 기준 {s}명. 막대는 그 단서가 줄인 범위, 빨간 고리는 가리지 않았다면 내려갔을 자리입니다.
      </p>
      {data.rules.length > 0 && (
        <p className="mt-2 rounded-cell bg-surface-2 px-2 py-1.5 text-xs text-ink-2">
          규칙: 이 사례의 {data.rules.map((r) => lab(r.attribute, r.attributeLabel)).join(', ')}은(는) 이 대화에서 늘 가립니다.
        </p>
      )}
      <span className="sr-only">지금 후보 {kNow}명</span>
    </div>
  );
}

/** 표 한 칸에 넣는 작은 계기: 그대로였다면(빨간 고리) → 지금(점), 기준선 하나. */
export function RangeMini({ raw, now, max, g, width = 96 }: { raw: number | null; now: number; max: number; g: number; width?: number }) {
  const showRaw = raw != null && raw !== now;
  return (
    <span aria-hidden className="relative inline-block h-3 align-middle" style={{ width }}>
      <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
      <span className="absolute inset-y-0 w-px bg-ink" style={{ left: `${logPos(g, max)}%` }} />
      {showRaw && (
        <>
          <span
            className="absolute top-1/2 h-0 -translate-y-1/2 border-t border-dashed border-danger"
            style={{ left: `${Math.min(logPos(raw!, max), logPos(now, max))}%`, width: `${Math.abs(logPos(now, max) - logPos(raw!, max))}%` }}
          />
          <span className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-danger bg-surface" style={{ left: `${logPos(raw!, max)}%` }} />
        </>
      )}
      <span className={`absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full ${now <= g ? 'bg-danger' : 'bg-iris'}`} style={{ left: `${logPos(now, max)}%` }} />
    </span>
  );
}

/** 같은 질문을 세 갈래에 보냈을 때 대화 끝의 후보 수 (한 축 위에). */
export function ArmCompare({ rows, max, g, s }: { rows: { key: string; label: string; note: string; k: number | null }[]; max: number; g: number; s: number }) {
  return (
    <div>
      <ul className="divide-y divide-line/70">
        {rows.map((r) => (
          <Row
            key={r.key}
            label={<span className="font-semibold">{r.label}</span>}
            sub={<span className="text-ink-3">{r.note}</span>}
            num={r.k == null ? '–' : <b className={r.k <= g ? 'text-danger-text' : 'text-ink'}>{r.k.toLocaleString()}명</b>}
          >
            {r.k != null ? <Track mark={{ kind: 'point', at: r.k }} max={max} g={g} s={s} /> : <div className="h-3.5" />}
          </Row>
        ))}
      </ul>
      <Axis max={max} g={g} s={s} />
    </div>
  );
}
