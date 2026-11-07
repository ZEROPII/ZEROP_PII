import { describe, expect, it } from 'vitest';
import { mockTermApi } from '../api/terminologyApi';
import { detectLocal, splitByMentions } from './termText';

describe('의료 용어 찾기', () => {
  const surfaces: [string, string][] = [
    ['gingivitis', 'DX_A'],
    ['amlodipine', 'MED_IN'],
    ['amlodipine 2.5 mg oral tablet', 'MED_RX'],
    ['아스피린', 'MED_ASA'],
  ];

  it('긴 표현을 먼저 잡고, 영문 낱말 중간은 건너뛰고, 한글 조사가 붙어도 잡는다', () => {
    const text = 'Gingivitis는 amlodipine 2.5 MG Oral Tablet과 다르다. xgingivitis, amlodipines, 아스피린을';
    const m = detectLocal(text, surfaces);
    expect(m.map((x) => [text.slice(x.start, x.end), x.node_id])).toEqual([
      ['Gingivitis', 'DX_A'],
      ['amlodipine 2.5 MG Oral Tablet', 'MED_RX'],
      ['아스피린', 'MED_ASA'],
    ]);
  });

  it('위치대로 글을 나누고, 어긋난 위치는 버린다', () => {
    const parts = splitByMentions('a Gingivitis b', [
      { start: 2, end: 12, node_id: 'DX_A' },
      { start: 5, end: 8, node_id: 'X' },
    ]);
    expect(parts).toEqual([{ text: 'a ' }, { text: 'Gingivitis', nodeId: 'DX_A' }, { text: ' b' }]);
    expect(splitByMentions('그대로', undefined)).toEqual([{ text: '그대로' }]);
  });

  it('Mock: 의료진 보기에는 기준 집단 환자 수가 없다', async () => {
    const sec = await mockTermApi.detect(['시술 후 아스피린 + 클로피도그렐을 12개월'], 'security');
    const cli = await mockTermApi.detect(['시술 후 아스피린 + 클로피도그렐을 12개월'], 'clinician');
    expect(sec.mentions[0]).toHaveLength(2);
    expect(Object.values(sec.terms).every((t) => typeof t.k_patients === 'number')).toBe(true);
    expect(Object.values(cli.terms).every((t) => !('k_patients' in t) && !('total_patients' in t))).toBe(true);
    const card = await mockTermApi.card('MED_IN_32968', 'clinician');
    expect(card.generalization_chain.length).toBeGreaterThan(1);
    expect('k_patients' in card).toBe(false);
  });
});
