// 사례 노트 (의료진 화면 오른쪽): 지금까지 답에 나온 이 사례의 내용을 노트 한 장으로 모은다.
//   속성      항목별 값 (그대로 · 범위 · 비공개)
//   연결된 질문 그 값을 꺼낸 질문 (누르면 대화의 그 자리로) — 옵시디언의 백링크
//   같은 값    다른 사례에도 나온 같은 값 — 옵시디언의 링크된 언급
// 공개 이력(DisclosureHistoryEntry)과 대화 기록만 쓴다. 후보 수는 쓰지 않는다.

import type { CaseId, CaseSummary, ChatMessage, ConversationSession, DisclosureHistoryEntry, PrivacyAction } from '../types/domain';
import { ATTR_LABEL } from './clinicianCopy';

/** 노트에 속성을 보여 주는 순서 */
const ORDER = ['DX', 'PROC', 'MED', 'PLAN', 'PERIOD', 'DURATION', 'AGE', 'SEX', 'REGION'];

export interface NoteValue {
  /** 가린 값은 null */
  text: string | null;
  action: PrivacyAction;
  turns: number[];
}

export interface NoteProperty {
  attribute: string;
  label: string;
  values: NoteValue[];
}

export interface NoteBacklink {
  turn: number;
  /** 질문한 대화의 사례 (다른 사례 대화에서 한 '모든 사례' 질문일 수 있다) */
  askedIn: CaseId | null;
  askedInLabel: string | null;
  messageId: string | null;
  /** 그 대화 안에서 몇 번째 질문인지 (사례 검색이면 null) */
  questionNo: number | null;
  question: string;
  facts: { label: string; action: PrivacyAction; text: string | null }[];
}

export interface NoteLinked {
  label: string;
  value: string;
  cases: { caseId: CaseId; label: string }[];
}

export interface CaseNote {
  properties: NoteProperty[];
  backlinks: NoteBacklink[];
  linked: NoteLinked[];
}

/** 백엔드가 value를 주지 않으면(실제 연구 서버) 설명 문장에서 값을 꺼낸다. */
export function entryValue(e: DisclosureHistoryEntry): string | null {
  if (e.action === 'suppress') return null;
  if (e.value !== undefined) return e.value;
  const d = e.description.replace(/^검색 결과 노출\s*·\s*/, '').replace(/\s*\(그대로 공개\)$/, '');
  if (e.action === 'generalize') {
    const m = /(?:→|:)\s*(.+)$/.exec(d);
    return (m ? m[1] : d).trim() || null;
  }
  return d.trim() || null;
}

function attrLabel(e: DisclosureHistoryEntry): string {
  return ATTR_LABEL[e.attribute] ?? e.attributeLabel;
}

/** 공개 이력 turn → 그 턴의 질문. 데모 백엔드는 대화 전체 턴(engineTurn)을, Mock은 사례별 턴을 쓴다. */
export function findQuestion(
  turn: number,
  caseId: CaseId,
  sessions: Record<CaseId, ConversationSession | undefined>,
): { message: ChatMessage; caseId: CaseId } | null {
  for (const [cid, s] of Object.entries(sessions)) {
    const m = s?.messages.find((x) => x.role === 'user' && x.engineTurn === turn);
    if (m) return { message: m, caseId: cid };
  }
  const own = sessions[caseId]?.messages.find((x) => x.role === 'user' && x.engineTurn === undefined && x.turn === turn);
  return own ? { message: own, caseId } : null;
}

export function buildCaseNote(input: {
  caseId: CaseId;
  entries: DisclosureHistoryEntry[];
  allEntries: Record<CaseId, DisclosureHistoryEntry[] | undefined>;
  sessions: Record<CaseId, ConversationSession | undefined>;
  cases: CaseSummary[];
}): CaseNote {
  const { caseId, entries, allEntries, sessions, cases } = input;
  const label = (id: CaseId) => cases.find((c) => c.caseId === id)?.label ?? id;

  // 속성: 항목별로 값 모으기 (같은 값은 한 번만, 나온 턴은 모두)
  const props = new Map<string, NoteProperty>();
  for (const e of entries) {
    const p = props.get(e.attribute) ?? { attribute: e.attribute, label: attrLabel(e), values: [] };
    const text = entryValue(e);
    const same = p.values.find((v) => v.text === text && v.action === e.action);
    if (same) {
      if (!same.turns.includes(e.turn)) same.turns.push(e.turn);
    } else p.values.push({ text, action: e.action, turns: [e.turn] });
    props.set(e.attribute, p);
  }
  const rank = (a: string) => (ORDER.indexOf(a) < 0 ? ORDER.length : ORDER.indexOf(a));
  const properties = [...props.values()].sort((a, b) => rank(a.attribute) - rank(b.attribute));

  // 연결된 질문: 턴마다 이 사례에 나온 값
  const byTurn = new Map<number, DisclosureHistoryEntry[]>();
  for (const e of entries) byTurn.set(e.turn, [...(byTurn.get(e.turn) ?? []), e]);
  const backlinks: NoteBacklink[] = [...byTurn.entries()]
    .sort(([a], [b]) => a - b)
    .map(([turn, es]) => {
      const q = turn === 0 ? null : findQuestion(turn, caseId, sessions);
      return {
        turn,
        askedIn: q?.caseId ?? null,
        askedInLabel: q ? label(q.caseId) : null,
        messageId: q?.message.messageId ?? null,
        questionNo: q?.message.turn ?? null,
        question: turn === 0 ? 'AI가 비슷한 사례를 찾으며 함께 보여 준 내용' : q ? q.message.segments.map((s) => s.text).join('') : `질문 ${turn}`,
        facts: es.map((e) => ({ label: attrLabel(e), action: e.action, text: entryValue(e) })),
      };
    });

  // 같은 값: 이 사례의 그대로·범위 값 중 다른 사례에도 나온 것
  const linked: NoteLinked[] = [];
  for (const p of properties) {
    for (const v of p.values) {
      if (v.text === null) continue;
      const others = Object.entries(allEntries)
        .filter(([cid, es]) => cid !== caseId && es?.some((e) => e.attribute === p.attribute && entryValue(e) === v.text))
        .map(([cid]) => ({ caseId: cid, label: label(cid) }))
        .sort((a, b) => a.label.localeCompare(b.label, 'ko', { numeric: true }));
      if (others.length) linked.push({ label: p.label, value: v.text, cases: others });
    }
  }
  return { properties, backlinks, linked };
}
