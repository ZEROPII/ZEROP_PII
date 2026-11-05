// AI 답을 화면에 그릴 단위로 나눈다.
// - 결정적 응답기의 답은 '사례1 · [기록11] 처방 약 시작일: 값' 줄로 온다 → 사례 · 항목 · 출처 · 값 줄(fact).
// - 실제 LLM의 답에는 마크다운(머리글 #, 굵은 글씨 **, 목록, 표, 가로줄)이 섞인다 → 기호를 그대로 보이지 않고 모양으로 그린다.
// 보호 조치가 걸린 값 조각(disclosure)은 쪼개지 않고 그 자리에 둔다 (표 칸 · 목록 줄 안에서도).

import type { MessageSegment } from '../types/domain';

/** 그릴 글 조각. k는 답 전체에서 읽는 순서 (의료 용어 찾기 결과를 맞추는 번호). */
export interface Inline {
  seg: MessageSegment;
  bold: boolean;
  k: number;
}

export interface ListItem {
  /** 들여쓰기 단계 (0부터) */
  depth: number;
  /** 번호 목록이면 '1.', 아니면 null */
  marker: string | null;
  content: Inline[];
}

export type AnswerBlock =
  | { kind: 'fact'; caseRef: string; field: string; source: string | null; value: Inline[] }
  | { kind: 'heading'; level: number; content: Inline[] }
  | { kind: 'para'; lines: Inline[][] }
  | { kind: 'list'; items: ListItem[] }
  | { kind: 'table'; head: Inline[][] | null; rows: Inline[][][] }
  | { kind: 'rule' };

export interface ParsedAnswer {
  blocks: AnswerBlock[];
  /** 모든 글 조각을 읽는 순서대로 (k 순) */
  pieces: Inline[];
}

type Line = MessageSegment[];

const FACT = /^(사례\d+) · (?:\[([^\]]+)\] )?(.+?): ?(.*)$/s;
const HEADING = /^\s{0,3}(#{1,6})\s+/;
const ITEM = /^(\s*)([-*•+]|\d{1,2}[.)])\s+/;
const QUOTE = /^\s{0,3}>\s?/;
const RULE = /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/;
const SEP_CELL = /^:?-{2,}:?$/;

/** 글 조각 안의 줄바꿈으로 줄을 나눈다. 빈 줄도 남긴다 (문단 경계). */
function splitLines(segments: MessageSegment[]): Line[] {
  const lines: Line[] = [[]];
  for (const seg of segments) {
    if (seg.kind !== 'text') {
      lines[lines.length - 1].push(seg);
      continue;
    }
    seg.text.split('\n').forEach((part, i) => {
      if (i > 0) lines.push([]);
      if (part) lines[lines.length - 1].push({ kind: 'text', text: part });
    });
  }
  return lines;
}

const lineText = (line: Line) => line.map((s) => s.text).join('');
const isBlank = (line: Line) => line.every((s) => s.kind === 'text' && !s.text.trim());
const headText = (line: Line) => (line[0]?.kind === 'text' ? line[0].text : '');

/** 첫 글 조각 앞에서 n글자를 뗀다. */
function dropHead(line: Line, n: number): Line {
  if (!n || line[0]?.kind !== 'text') return line;
  const rest = line[0].text.slice(n);
  return rest ? [{ kind: 'text', text: rest }, ...line.slice(1)] : line.slice(1);
}

/** 앞뒤 공백을 떼고, 공백만 남은 글 조각은 버린다. */
function trimRun(run: Line): Line {
  const out = [...run];
  while (out[0]?.kind === 'text' && !out[0].text.trim()) out.shift();
  while (out.length && out[out.length - 1].kind === 'text' && !out[out.length - 1].text.trim()) out.pop();
  if (out[0]?.kind === 'text') out[0] = { kind: 'text', text: out[0].text.trimStart() };
  const last = out.length - 1;
  if (last >= 0 && out[last].kind === 'text') out[last] = { kind: 'text', text: out[last].text.trimEnd() };
  return out;
}

/** 표 한 줄을 칸으로 나눈다. '|'는 글 조각 안에서만 찾는다. */
function cellsOf(line: Line): Line[] {
  const out: Line[] = [];
  let cur: Line = [];
  let open = false;
  for (const s of line) {
    if (s.kind !== 'text') {
      cur.push(s);
      continue;
    }
    s.text.split('|').forEach((part, i) => {
      if (i > 0) {
        if (open) out.push(cur);
        cur = [];
        open = true;
      }
      if (part) cur.push({ kind: 'text', text: part });
    });
  }
  if (!isBlank(cur)) out.push(cur);
  return out.map(trimRun);
}

const isTableRow = (line: Line) => headText(line).trimStart().startsWith('|');
const isSeparator = (line: Line) => {
  if (line.some((s) => s.kind !== 'text')) return false;
  const cells = cellsOf(line).map(lineText);
  return cells.length > 0 && cells.every((c) => SEP_CELL.test(c.trim()));
};

export function parseAnswer(segments: MessageSegment[]): ParsedAnswer {
  const blocks: AnswerBlock[] = [];
  const pieces: Inline[] = [];
  let k = 0;

  /** 굵은 글씨(**)와 인라인 코드(`)의 기호를 떼고 조각마다 굵기를 붙인다. 짝이 없는 마지막 **는 버린다. */
  const inline = (run: Line): Inline[] => {
    const out: Inline[] = [];
    const total = run.reduce((n, s) => n + (s.kind === 'text' ? s.text.split('**').length - 1 : 0), 0);
    let seen = 0;
    let bold = false;
    for (const s of run) {
      if (s.kind !== 'text') {
        out.push({ seg: s, bold, k: k++ });
        continue;
      }
      s.text.split('**').forEach((part, i) => {
        if (i > 0) {
          seen += 1;
          if (!(total % 2 === 1 && seen === total)) bold = !bold;
        }
        const text = part.replace(/`([^`]*)`/g, '$1');
        if (text) out.push({ seg: { kind: 'text', text }, bold, k: k++ });
      });
    }
    pieces.push(...out);
    return out;
  };

  let para: Inline[][] | null = null;
  let gap = false; // 앞 줄이 빈 줄이었다 (표는 빈 줄에서 끝난다)
  const endPara = () => {
    para = null;
  };

  for (const line of splitLines(segments)) {
    if (isBlank(line)) {
      endPara();
      gap = true;
      continue;
    }
    const head = headText(line);
    const prev = blocks[blocks.length - 1];
    const joined = !gap;
    gap = false;

    const fact = FACT.exec(head);
    if (fact) {
      endPara();
      const [, caseRef, source, field, rest] = fact;
      const value = inline(trimRun([...(rest ? [{ kind: 'text', text: rest } as MessageSegment] : []), ...line.slice(1)]));
      blocks.push({ kind: 'fact', caseRef, field: field.trim(), source: source ?? null, value });
      continue;
    }
    if (line.length === 1 && RULE.test(head)) {
      endPara();
      blocks.push({ kind: 'rule' });
      continue;
    }
    const h = HEADING.exec(head);
    if (h) {
      endPara();
      const content = inline(trimRun(dropHead(line, h[0].length)));
      if (content.length) blocks.push({ kind: 'heading', level: h[1].length, content });
      continue;
    }
    if (isTableRow(line)) {
      endPara();
      if (isSeparator(line)) {
        // 머리 줄 바로 아래의 구분 줄: 앞 줄을 머리로 올린다
        if (joined && prev?.kind === 'table' && prev.head === null && prev.rows.length === 1) prev.head = prev.rows.pop()!;
        continue;
      }
      const row = cellsOf(line).map(inline);
      if (joined && prev?.kind === 'table') prev.rows.push(row);
      else blocks.push({ kind: 'table', head: null, rows: [row] });
      continue;
    }
    const it = ITEM.exec(head);
    if (it) {
      endPara();
      const content = inline(trimRun(dropHead(line, it[0].length)));
      if (!content.length) continue;
      const item: ListItem = { depth: Math.min(3, Math.floor(it[1].replace(/\t/g, '  ').length / 2)), marker: /\d/.test(it[2]) ? it[2].replace(')', '.') : null, content };
      if (prev?.kind === 'list') prev.items.push(item);
      else blocks.push({ kind: 'list', items: [item] });
      continue;
    }
    const q = QUOTE.exec(head);
    const body = inline(trimRun(dropHead(line, q ? q[0].length : 0)));
    if (!body.length) continue;
    if (para) {
      (para as Inline[][]).push(body);
    } else {
      para = [body];
      blocks.push({ kind: 'para', lines: para });
    }
  }
  return { blocks, pieces };
}
