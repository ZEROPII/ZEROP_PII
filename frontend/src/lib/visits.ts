// 차트 '내원 이력' 계산 (ADR-0038): 해마다 묶기 · 달마다 내원 수 · 그해 눈여겨볼 일.
import type { EmrChart } from '../types/domain';

type Visit = EmrChart['visits'][number];
type Item = Visit['items'][number];

export interface YearRow {
  year: number;
  /** 그해 내원한 날 (최근 것부터) */
  days: string[];
  /** 달마다 내원한 날 수 (1월이 0번) */
  months: number[];
  /** 그달에 새 진단 · 첫 시술이 있었는지 (자세한 기록이 있는 내원만 본다) */
  fresh: boolean[];
  /** 그해 내원의 자세한 기록 (최근 것부터). 아주 오래된 해는 서버가 줄여 비어 있을 수 있다 */
  visits: Visit[];
}

/** 새 진단 · 첫 시술 (첫 처방 · 관리 계획은 흔해서 해마다 요약에는 넣지 않고, 펼친 내원에만 '처음'으로 보인다) */
const isNew = (x: Item) => !!x.first && (x.kind === 'problems' || x.kind === 'procedures');

/** 내원한 날을 해마다 묶는다 (최근 해부터). 날 수는 visitDates로 세고, 자세한 기록은 visits에서 붙인다 */
export function yearRows(dates: string[], visits: Visit[]): YearRow[] {
  const rows = new Map<number, YearRow>();
  for (const d of dates) {
    const y = Number(d.slice(0, 4));
    const r: YearRow = rows.get(y) ?? { year: y, days: [], months: Array(12).fill(0), fresh: Array(12).fill(false), visits: [] };
    r.days.push(d);
    r.months[Number(d.slice(5, 7)) - 1] += 1;
    rows.set(y, r);
  }
  for (const v of visits) {
    const r = rows.get(Number(v.date.slice(0, 4)));
    if (!r) continue;
    r.visits.push(v);
    if (v.items.some(isNew)) r.fresh[Number(v.date.slice(5, 7)) - 1] = true;
  }
  return [...rows.values()]
    .sort((a, b) => b.year - a.year)
    .map((r) => ({ ...r, days: [...r.days].sort().reverse(), visits: [...r.visits].sort((a, b) => b.date.localeCompare(a.date)) }));
}

const KIND_ORDER: Record<Item['kind'], number> = { problems: 0, procedures: 1, medications: 2, carePlans: 3 };

export interface Highlight {
  /**
   * 'new': 그해 처음 나온 진단 · 시술 (진단 먼저, 그 안에서는 먼저 나온 순)
   * 'main': 처음 나온 것이 없을 때, 그해 여러 날 나온 것 가운데 가장 많은 날 나온 것 하나 ('주로')
   * 'item': 그마저 없을 때 (모두 한 번씩), 그해 기록된 것 (진단 먼저)
   */
  type: 'new' | 'main' | 'item';
  kind: Item['kind'];
  label: string;
}

/** 그해 눈여겨볼 일 */
export function highlightsOf(visits: Visit[]): Highlight[] {
  const byDate = [...visits].sort((a, b) => a.date.localeCompare(b.date));
  const fresh: Highlight[] = [];
  for (const v of byDate)
    for (const x of v.items)
      if (isNew(x) && !fresh.some((h) => h.kind === x.kind && h.label === x.label)) fresh.push({ type: 'new', kind: x.kind, label: x.label });
  if (fresh.length) return fresh.sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);      // 정렬은 안정적이라 같은 종류 안에서는 먼저 나온 순
  const days = new Map<string, { kind: Item['kind']; label: string; n: number; at: number }>();
  byDate.forEach((v, i) => {
    for (const x of new Map(v.items.map((y) => [`${y.kind}:${y.label}`, y])).values()) {
      const key = `${x.kind}:${x.label}`;
      const c = days.get(key) ?? { kind: x.kind, label: x.label, n: 0, at: i };
      c.n += 1;
      days.set(key, c);
    }
  });
  const all = [...days.values()].sort((a, b) => b.n - a.n || KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.at - b.at);
  if (!all.length) return [];
  if (all[0].n >= 2) return [{ type: 'main', kind: all[0].kind, label: all[0].label }];
  return all.map((c) => ({ type: 'item', kind: c.kind, label: c.label }));
}
