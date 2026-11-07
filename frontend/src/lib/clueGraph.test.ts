import { describe, expect, it } from 'vitest';
import { buildClueGraph, layoutGraph, uniqueClueCount, type ClueFact } from './clueGraph';

const fact = (caseRef: string, attribute: string, value: string | null, action: ClueFact['action'] = 'allow', turn = 0): ClueFact => ({
  caseRef,
  caseLabel: caseRef.replace(/^사례(\d+)$/, '사례 $1'),
  attribute,
  attributeLabel: attribute,
  value,
  action,
  turn,
});

const facts: ClueFact[] = [
  ...['사례1', '사례2', '사례3', '사례4', '사례5'].map((c) => fact(c, '진단', 'Acute bronchitis')),
  fact('사례1', '처방 약', 'loratadine'),
  fact('사례2', '처방 약', 'acetaminophen'),
  fact('사례3', '성별', '남성', 'allow', 2),
  fact('사례4', '성별', '남성', 'allow', 2),
  fact('사례1', '시기', null, 'suppress', 1),
  fact('사례5', '시기', null, 'suppress', 3),
  fact('사례5', '나이', '0~9세', 'generalize', 4),
  fact('사례1', '처방 약', 'loratadine', 'allow', 5), // 같은 값이 다른 턴에 또 나옴
];

describe('단서 그래프', () => {
  const g = buildClueGraph(facts);

  it('같은 값은 노드 하나로 합치고, 가린 값은 사례마다 따로 둔다', () => {
    const dx = g.nodes.find((n) => n.id === 'val:진단=Acute bronchitis')!;
    expect(dx.cases).toHaveLength(5);
    expect(g.nodes.find((n) => n.id === 'val:성별=남성')!.cases).toEqual(['사례3', '사례4']);
    const locks = g.nodes.filter((n) => n.id.startsWith('lock:'));
    expect(locks.map((n) => n.id).sort()).toEqual(['lock:사례1:시기', 'lock:사례5:시기']);
    expect(locks.every((n) => n.action === 'suppress' && n.label === '비공개')).toBe(true);
    expect(g.nodes.find((n) => n.id === 'val:처방 약=loratadine')!.turns).toEqual([0, 5]);
    expect(g.nodes.filter((n) => n.kind === 'case')).toHaveLength(5);
    expect(g.links).toHaveLength(5 + 2 + 2 + 2 + 1);
  });

  it('사례마다 그 사례에만 붙은 단서 수를 센다', () => {
    expect(uniqueClueCount(g)).toEqual({ 사례1: 2, 사례2: 1, 사례5: 2 });
  });

  it('배치는 같은 입력에 같은 결과이고, 모두 영역 안에 있다', () => {
    const a = layoutGraph(g, { width: 560, height: 360 });
    const b = layoutGraph(g, { width: 560, height: 360 });
    expect(a).toEqual(b);
    for (const p of Object.values(a)) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(560);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(360);
    }
  });

  it('여러 사례에 공통인 값이 한 사례에만 붙은 값보다 가운데에 가깝다', () => {
    const pos = layoutGraph(g, { width: 560, height: 360 });
    const dist = (id: string) => Math.hypot(pos[id].x - 280, pos[id].y - 180);
    const shared = g.nodes.filter((n) => n.kind === 'value' && n.cases.length > 1).map((n) => dist(n.id));
    const single = g.nodes.filter((n) => n.kind === 'value' && n.cases.length === 1).map((n) => dist(n.id));
    const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;
    expect(mean(shared)).toBeLessThan(mean(single));
    expect(dist('val:진단=Acute bronchitis')).toBeLessThan(60);
  });

  it('단서가 없으면 빈 그래프', () => {
    expect(buildClueGraph([])).toEqual({ nodes: [], links: [] });
    expect(layoutGraph({ nodes: [], links: [] }, { width: 300, height: 300 })).toEqual({});
  });
});
