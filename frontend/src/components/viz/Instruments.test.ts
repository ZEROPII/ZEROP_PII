import { describe, expect, it } from 'vitest';
import type { Narrowing } from '../../types/monitor';
import { ladderRows, logPos } from './Instruments';

const base: Narrowing = {
  case: '사례1',
  caseId: 'case-1',
  label: '사례 1',
  population: 461,
  generalizeK: 5,
  suppressK: 3,
  k: 1,
  steps: [
    { attribute: 'DX', attributeLabel: '진단', value: 'Acute bronchitis', turn: 0, approved: false, kBefore: 461, kAfter: 189 },
    { attribute: 'MED', attributeLabel: '처방 약', value: 'loratadine', turn: 0, approved: false, kBefore: 189, kAfter: 6 },
    { attribute: 'PERIOD', attributeLabel: '시기', value: '2004-06-16', turn: null, approved: true, afterTurn: 1, kBefore: 6, kAfter: 1 },
  ],
  hidden: [
    { turn: 1, attribute: 'PERIOD', attributeLabel: '시기', action: 'suppress', kIfRaw: 1, released: true },
    { turn: 2, attribute: 'MED', attributeLabel: '처방 약', action: 'suppress', kIfRaw: 1, released: false },
  ],
  rules: [],
};

describe('후보 수 계기', () => {
  it('로그 눈금: 1은 왼쪽 끝, 기준 집단은 오른쪽 끝', () => {
    expect(logPos(1, 461)).toBe(0);
    expect(logPos(461, 461)).toBe(100);
    expect(logPos(5, 461)).toBeCloseTo((Math.log(5) / Math.log(461)) * 100);
    expect(logPos(0, 461)).toBe(0);
    expect(logPos(9999, 461)).toBe(100);
  });

  it('줄 순서: 턴 순서, 같은 턴은 공개 다음 가린 값, 승인 공개는 그 턴 바로 뒤', () => {
    const rows = ladderRows(base);
    expect(rows.map((r) => `${r.kind}${r.index}`)).toEqual(['step0', 'step1', 'hidden0', 'step2', 'hidden1']);
  });

  it('가린 값의 자리: 그 턴까지 쌓인 후보 수 (승인 공개 뒤면 공개한 뒤의 수)', () => {
    const rows = ladderRows(base);
    const h0 = rows.find((r) => r.kind === 'hidden' && r.index === 0);
    const h1 = rows.find((r) => r.kind === 'hidden' && r.index === 1);
    expect(h0 && 'at' in h0 && h0.at).toBe(6);
    expect(h1 && 'at' in h1 && h1.at).toBe(1);
  });
});
