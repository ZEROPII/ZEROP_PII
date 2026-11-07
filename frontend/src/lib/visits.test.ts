import { describe, expect, it } from 'vitest';
import { highlightsOf, yearRows } from './visits';

const v = (date: string, items: { kind: 'problems' | 'medications' | 'procedures' | 'carePlans'; label: string; first?: boolean }[]) => ({ date, items });

describe('내원 이력 (ADR-0038)', () => {
  it('내원한 날을 해마다 묶고 달마다 센다 (최근 해부터), 자세한 기록은 그해에 붙인다', () => {
    const rows = yearRows(['2024-01-05', '2024-01-20', '2024-07-01', '2026-03-02'], [
      v('2026-03-02', [{ kind: 'medications', label: 'metformin', first: true }]),
      v('2024-07-01', [{ kind: 'problems', label: 'Prediabetes', first: true }]),
    ]);
    expect(rows.map((r) => [r.year, r.days.length])).toEqual([
      [2026, 1],
      [2024, 3],
    ]);
    expect(rows[1].months.slice(0, 7)).toEqual([2, 0, 0, 0, 0, 0, 1]);
    expect(rows[1].days[0]).toBe('2024-07-01');
    expect(rows[1].visits.map((x) => x.date)).toEqual(['2024-07-01']);
    expect(rows[1].fresh.indexOf(true)).toBe(6);                  // 7월에 새 진단
    expect(rows[0].fresh.some(Boolean)).toBe(false);              // 첫 처방은 해마다 요약의 '새로'에 넣지 않는다
  });

  it('그해 눈여겨볼 일: 새 진단 · 첫 시술(진단 먼저), 없으면 여러 날 나온 것, 그마저 없으면 그해 기록', () => {
    const fresh = highlightsOf([
      v('2024-07-01', [{ kind: 'procedures', label: 'Colonoscopy', first: true }, { kind: 'medications', label: 'amoxicillin', first: true }]),
      v('2024-05-01', [{ kind: 'problems', label: 'Hypertension', first: true }]),
      v('2024-02-01', [{ kind: 'procedures', label: 'Dental cleaning', first: true }, { kind: 'problems', label: 'Prediabetes', first: true }]),
    ]);
    expect(fresh.map((h) => [h.type, h.label])).toEqual([
      ['new', 'Prediabetes'],
      ['new', 'Hypertension'],
      ['new', 'Dental cleaning'],
      ['new', 'Colonoscopy'],
    ]);
    const main = highlightsOf([
      v('2025-01-01', [{ kind: 'problems', label: 'Gingivitis' }, { kind: 'medications', label: 'insulin' }]),
      v('2025-03-01', [{ kind: 'medications', label: 'insulin' }]),
      v('2025-05-01', [{ kind: 'medications', label: 'insulin' }, { kind: 'problems', label: 'Gingivitis' }]),
      v('2025-07-01', [{ kind: 'medications', label: 'insulin' }]),
    ]);
    expect(main).toEqual([{ type: 'main', kind: 'medications', label: 'insulin' }]);
    const once = highlightsOf([v('2025-01-01', [{ kind: 'medications', label: 'lisinopril' }, { kind: 'carePlans', label: 'Diet plan' }, { kind: 'problems', label: 'Otitis media' }])]);
    expect(once.map((h) => [h.type, h.label])).toEqual([
      ['item', 'Otitis media'],
      ['item', 'lisinopril'],
      ['item', 'Diet plan'],
    ]);
    expect(highlightsOf([])).toEqual([]);
  });
});
