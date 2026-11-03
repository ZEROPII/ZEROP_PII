// 답변 글을 용어 위치에 맞춰 조각으로 나누기 (화면 표시), Mock 모드의 용어 찾기.
// 찾는 규칙은 백엔드 medical/term_service.py detect()와 같다: 긴 표현부터, 영문·숫자 낱말 중간은 건너뜀, 겹치면 먼저 잡힌 것.

import type { TermMention } from '../types/terminology';

export interface TextPart {
  text: string;
  nodeId?: string;
}

export function splitByMentions(text: string, mentions: TermMention[] | undefined): TextPart[] {
  if (!mentions?.length) return [{ text }];
  const parts: TextPart[] = [];
  let at = 0;
  for (const m of [...mentions].sort((a, b) => a.start - b.start)) {
    if (m.start < at || m.end > text.length || m.end <= m.start) continue;
    if (m.start > at) parts.push({ text: text.slice(at, m.start) });
    parts.push({ text: text.slice(m.start, m.end), nodeId: m.node_id });
    at = m.end;
  }
  if (at < text.length) parts.push({ text: text.slice(at) });
  return parts;
}

const isWordChar = (c: string | undefined) => !!c && /[A-Za-z0-9]/.test(c);

/** surfaces: [소문자 표현, node_id] (길이 내림차순일 필요 없음) */
export function detectLocal(text: string, surfaces: [string, string][]): TermMention[] {
  const low = text.toLowerCase();
  const taken = new Uint8Array(text.length);
  const out: TermMention[] = [];
  for (const [surf, nodeId] of [...surfaces].sort((a, b) => b[0].length - a[0].length)) {
    let start = low.indexOf(surf);
    while (start !== -1) {
      const end = start + surf.length;
      const free = !taken.subarray(start, end).some((x) => x === 1);
      if (free && !isWordChar(low[start - 1]) && !isWordChar(low[end])) {
        taken.fill(1, start, end);
        out.push({ start, end, node_id: nodeId });
      }
      start = low.indexOf(surf, end);
    }
  }
  return out.sort((a, b) => a.start - b.start);
}
