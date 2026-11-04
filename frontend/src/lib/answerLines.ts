// 데모 응답기 답은 '사례1 · [기록11] 처방 약 시작일: 값' 같은 줄로 온다.
// 의료진 화면은 이 줄을 사례 · 항목 · 출처 · 값으로 나눠 표처럼 보여 준다. 다른 모양의 글(Mock, 실제 LLM 문장)은 그대로 둔다.

import type { MessageSegment } from '../types/domain';

export type AnswerRow =
  | { kind: 'fact'; caseRef: string; field: string; source: string | null; value: MessageSegment[] }
  | { kind: 'text'; segments: MessageSegment[] };

const LINE = /^(사례\d+) · (?:\[([^\]]+)\] )?(.+?): ?(.*)$/s;

/** 조각들을 줄 단위로 나눈다 (글 조각 안의 줄바꿈 기준). 보호 조치가 걸린 조각은 쪼개지 않는다. */
function splitLines(segments: MessageSegment[]): MessageSegment[][] {
  const lines: MessageSegment[][] = [[]];
  for (const seg of segments) {
    if (seg.kind !== 'text') {
      lines[lines.length - 1].push(seg);
      continue;
    }
    const parts = seg.text.split('\n');
    parts.forEach((part, i) => {
      if (i > 0) lines.push([]);
      if (part) lines[lines.length - 1].push({ kind: 'text', text: part });
    });
  }
  return lines.filter((l) => l.length > 0);
}

export function toAnswerRows(segments: MessageSegment[]): AnswerRow[] {
  const rows: AnswerRow[] = [];
  for (const line of splitLines(segments)) {
    const head = line[0];
    const m = head.kind === 'text' ? LINE.exec(head.text) : null;
    if (!m) {
      const prev = rows[rows.length - 1];
      // 표 모양이 아닌 줄은 앞의 글 줄에 이어 붙인다 (문단으로 보이게).
      if (prev?.kind === 'text') prev.segments.push({ kind: 'text', text: '\n' }, ...line);
      else rows.push({ kind: 'text', segments: [...line] });
      continue;
    }
    const [, caseRef, source, field, rest] = m;
    const value: MessageSegment[] = [...(rest ? [{ kind: 'text', text: rest } as MessageSegment] : []), ...line.slice(1)];
    rows.push({ kind: 'fact', caseRef, field: field.trim(), source: source ?? null, value });
  }
  return rows;
}

/** 표 모양 줄이 하나라도 있으면 표로 보여 준다. */
export function looksTabular(rows: AnswerRow[]): boolean {
  return rows.some((r) => r.kind === 'fact');
}
