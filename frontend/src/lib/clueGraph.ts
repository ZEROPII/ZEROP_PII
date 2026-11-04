// 단서 그래프 (보안 담당자 화면): 사례와, 답에 나간 단서 값을 잇는다. 옵시디언 그래프 보기와 같은 방식.
//   여러 사례에 같이 나온 값(예: 진단 Acute bronchitis)은 가운데로 모이고, 한 사례에만 나온 값은 그 사례 둘레에 붙는다.
//   한 사례에만 붙은 값이 많을수록 그 사례를 좁히는 단서가 쌓였다는 뜻이다. 가린 값은 사례마다 따로 잠금 점으로 둔다.
// 배치는 난수 없이 정해진 횟수만 힘을 계산한다 (같은 입력 → 같은 그림).

import type { PrivacyAction } from '../types/domain';

export interface ClueFact {
  caseRef: string;
  caseLabel: string;
  attribute: string;
  attributeLabel: string;
  /** 가린 값은 null */
  value: string | null;
  action: PrivacyAction;
  turn: number;
}

export interface GraphNode {
  id: string;
  kind: 'case' | 'value';
  label: string;
  /** 값 노드: 항목 이름 */
  attribute?: string;
  action: PrivacyAction;
  /** 값 노드: 이 값이 나온 사례 */
  cases: string[];
  turns: number[];
}

export interface GraphLink {
  source: string;
  target: string;
  action: PrivacyAction;
}

export interface ClueGraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

const RANK: Record<PrivacyAction, number> = { allow: 0, generalize: 1, suppress: 2 };

export function buildClueGraph(facts: ClueFact[]): ClueGraphData {
  const nodes = new Map<string, GraphNode>();
  const links = new Map<string, GraphLink>();
  const caseOrder: string[] = [];
  for (const f of facts) {
    const cid = `case:${f.caseRef}`;
    if (!nodes.has(cid)) {
      nodes.set(cid, { id: cid, kind: 'case', label: f.caseLabel, action: 'allow', cases: [f.caseRef], turns: [] });
      caseOrder.push(cid);
    }
    const cn = nodes.get(cid)!;
    if (!cn.turns.includes(f.turn)) cn.turns.push(f.turn);
    // 가린 값은 어떤 값인지 모르므로 사례마다 따로 둔다.
    const vid = f.value === null || f.action === 'suppress' ? `lock:${f.caseRef}:${f.attribute}` : `val:${f.attribute}=${f.value}`;
    const vn = nodes.get(vid) ?? {
      id: vid,
      kind: 'value' as const,
      label: f.value === null || f.action === 'suppress' ? '비공개' : f.value,
      attribute: f.attributeLabel,
      action: f.action,
      cases: [],
      turns: [],
    };
    if (RANK[f.action] > RANK[vn.action]) vn.action = f.action;
    if (!vn.cases.includes(f.caseRef)) vn.cases.push(f.caseRef);
    if (!vn.turns.includes(f.turn)) vn.turns.push(f.turn);
    nodes.set(vid, vn);
    const lid = `${cid}>${vid}`;
    const old = links.get(lid);
    if (!old || RANK[f.action] > RANK[old.action]) links.set(lid, { source: cid, target: vid, action: f.action });
  }
  for (const n of nodes.values()) n.turns.sort((a, b) => a - b);
  return { nodes: [...nodes.values()], links: [...links.values()] };
}

export interface Point {
  x: number;
  y: number;
}

export function layoutGraph(g: ClueGraphData, opts: { width: number; height: number; iterations?: number }): Record<string, Point> {
  const { width: W, height: H } = opts;
  const iterations = opts.iterations ?? 320;
  const cx = W / 2;
  const cy = H / 2;
  const pad = 28;
  const caseNodes = g.nodes.filter((n) => n.kind === 'case');
  const pos: Record<string, Point> = {};
  const vel: Record<string, Point> = {};
  const R0 = Math.min(W, H) * 0.34;

  // 시작 위치: 사례는 원 위에, 공유 값은 그 사례들 가운데쯤, 한 사례 값은 그 사례 바깥쪽 작은 원 위에.
  caseNodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(caseNodes.length, 1) - Math.PI / 2;
    pos[n.id] = { x: cx + R0 * Math.cos(a), y: cy + R0 * Math.sin(a) };
  });
  const perCase: Record<string, number> = {};
  for (const n of g.nodes) {
    if (n.kind === 'case') continue;
    const anchors = n.cases.map((c) => pos[`case:${c}`]).filter(Boolean);
    const ax = anchors.reduce((s, p) => s + p.x, 0) / Math.max(anchors.length, 1);
    const ay = anchors.reduce((s, p) => s + p.y, 0) / Math.max(anchors.length, 1);
    if (n.cases.length > 1) {
      pos[n.id] = { x: cx + (ax - cx) * 0.25, y: cy + (ay - cy) * 0.25 };
    } else {
      const key = n.cases[0];
      const k = (perCase[key] = (perCase[key] ?? 0) + 1);
      const out = Math.atan2(ay - cy, ax - cx);
      const a = out + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 0.55;
      pos[n.id] = { x: ax + 44 * Math.cos(a), y: ay + 44 * Math.sin(a) };
    }
  }
  for (const n of g.nodes) vel[n.id] = { x: 0, y: 0 };

  const ids = g.nodes.map((n) => n.id);
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const spread = Math.min(W, H) / 420;
  for (let it = 0; it < iterations; it++) {
    const cool = 1 - it / iterations;
    const f: Record<string, Point> = Object.fromEntries(ids.map((id) => [id, { x: 0, y: 0 }]));
    // 서로 밀어내기
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos[ids[i]];
        const b = pos[ids[j]];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          // 같은 자리면 순서로 비켜 세운다 (난수 대신)
          dx = (i - j) * 0.1;
          dy = 0.1;
          d2 = dx * dx + dy * dy;
        }
        const ni = byId[ids[i]];
        const nj = byId[ids[j]];
        const bothCases = ni.kind === 'case' && nj.kind === 'case';
        const bothShared = ni.kind === 'value' && nj.kind === 'value' && ni.cases.length > 1 && nj.cases.length > 1;
        const rep = ((bothCases ? 5200 : bothShared ? 3600 : 1500) * spread * spread) / Math.max(d2, 64);
        const d = Math.sqrt(d2);
        f[ids[i]].x += (dx / d) * rep;
        f[ids[i]].y += (dy / d) * rep;
        f[ids[j]].x -= (dx / d) * rep;
        f[ids[j]].y -= (dy / d) * rep;
      }
    }
    // 이은 선은 용수철
    for (const l of g.links) {
      const a = pos[l.source];
      const b = pos[l.target];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
      const shared = byId[l.target].cases.length > 1;
      const rest = (shared ? 96 : 52) * spread;
      const k = 0.06 * (d - rest);
      f[l.source].x += (dx / d) * k;
      f[l.source].y += (dy / d) * k;
      f[l.target].x -= (dx / d) * k;
      f[l.target].y -= (dy / d) * k;
    }
    // 가운데로 끌기: 여러 사례에 나온 값일수록 세게
    for (const id of ids) {
      const n = byId[id];
      const g0 = n.kind === 'case' ? 0.012 : n.cases.length > 1 ? 0.02 + 0.006 * n.cases.length : 0.004;
      f[id].x += (cx - pos[id].x) * g0;
      f[id].y += (cy - pos[id].y) * g0;
    }
    for (const id of ids) {
      vel[id].x = (vel[id].x + f[id].x) * 0.82;
      vel[id].y = (vel[id].y + f[id].y) * 0.82;
      const step = 9 * cool + 0.6;
      const v = Math.sqrt(vel[id].x ** 2 + vel[id].y ** 2);
      const s = v > step ? step / v : 1;
      pos[id] = {
        x: Math.min(W - pad, Math.max(pad, pos[id].x + vel[id].x * s)),
        y: Math.min(H - pad, Math.max(pad, pos[id].y + vel[id].y * s)),
      };
    }
  }
  return pos;
}

/** 사례별로 그 사례에만 붙은 값(좁히는 단서)의 수 */
export function uniqueClueCount(g: ClueGraphData): Record<string, number> {
  const out: Record<string, number> = {};
  for (const n of g.nodes) if (n.kind === 'value' && n.cases.length === 1) out[n.cases[0]] = (out[n.cases[0]] ?? 0) + 1;
  return out;
}
