// 의료진 화면에 들어가는 문구와 데이터 변환 검사.
// 핵심: 의료진 화면 문구에는 후보 수 · 기준값 같은 재식별 위험 숫자가 들어가지 않는다.
import { describe, expect, it } from 'vitest';
import type { ConversationSession, DisclosureHistoryEntry, PreflightRiskAssessment, ProtectionResult } from '../types/domain';
import { parseAnswer, type Inline } from './answerLines';
import { buildCaseNote, entryValue } from './caseNote';
import { attrName, preflightNotice, preflightStatusLine, protectionNote, requestDraft, restrictedNotice, whyText } from './clinicianCopy';

/** 위험 숫자 표현: '6명', '후보', '기준 5', 'k=' */
const RISK_NUMBER = /\d+\s*명|후보|기준\s*\d|k\s*=/;

const assessment = (over: Partial<PreflightRiskAssessment>): PreflightRiskAssessment => ({
  caseId: 'case-1',
  question: 'q',
  requiresWarning: true,
  currentK: 6,
  projectedK: 1,
  message: '그대로 답하면 사례 1 후보가 6명에서 1명으로 줄어듭니다.',
  affectedAttributes: ['시점'],
  suggestions: [],
  source: 'backend',
  ...over,
});

const protection = (over: Partial<ProtectionResult>): ProtectionResult => ({
  decision: 'suppress',
  transformations: [
    { id: 't1', attribute: 'PERIOD', attributeLabel: '사례 1 시기', action: 'suppress', disclosedValue: null, levelDescription: '가림 (그대로면 후보 1명)', caseRef: '사례1' },
    { id: 't2', attribute: 'AGE', attributeLabel: '사례 1 나이', action: 'generalize', disclosedValue: '0~9세', levelDescription: '넓은 범주로 바꿔 공개: 0~9세', caseRef: '사례1' },
  ],
  explanation: '그대로 답하면 후보가 1명까지 줄어들어 일부 값을 보호해 답했습니다 (가림 1건).',
  kBefore: 6,
  kAfter: 6,
  releaseMode: 'REWRITTEN',
  ...over,
});

describe('의료진 화면 문구', () => {
  it('보내기 전 안내는 보내면 어떻게 보이는지만 말하고 숫자를 쓰지 않는다', () => {
    const sup = preflightNotice(assessment({ plannedAction: 'suppress' }), '사례 1')!;
    expect(sup.text).toBe('이 질문에 답하면 사례 1의 시점은 비공개로 표시됩니다. 나머지 내용은 그대로 답합니다.');
    const gen = preflightNotice(assessment({ plannedAction: 'generalize', affectedAttributes: ['나이'] }), '사례 2')!;
    expect(gen.text).toContain('사례 2의 나이는 정확한 값 대신 범위로');
    const unknown = preflightNotice(assessment({ plannedAction: undefined }), '사례 1')!;
    for (const n of [sup, gen, unknown]) expect(n.text).not.toMatch(RISK_NUMBER);
    expect(preflightNotice(assessment({ requiresWarning: false }), '사례 1')).toBeNull();
  });

  it('입력칸 아래 상태 줄에도 숫자가 없다', () => {
    const lines = [
      preflightStatusLine('checking', null),
      preflightStatusLine('error', null),
      preflightStatusLine('done', assessment({ supported: false })),
      preflightStatusLine('done', assessment({ understood: false })),
      preflightStatusLine('done', assessment({ requiresWarning: false, projectedK: 189 })),
      preflightStatusLine('idle', null),
    ];
    for (const l of lines) expect(l).not.toMatch(RISK_NUMBER);
  });

  it('답 아래 설명과 "왜 그런가요?"는 백엔드 설명(숫자 포함)을 쓰지 않고 새로 만든다', () => {
    const p = protection({});
    const note = protectionNote(p)!;
    expect(note.text).toContain('비공개');
    const why = whyText(p, '사례 1');
    expect(why[0]).toContain('사례 1 환자의 시기는');
    expect(why.join(' ')).toContain('나이는');
    for (const t of [note.text, ...why, restrictedNotice('사례 1'), requestDraft('사례 1', ['시기'])]) expect(t).not.toMatch(RISK_NUMBER);
    expect(protectionNote(protection({ transformations: [] }))).toBeNull();
    expect(protectionNote(protection({ releaseMode: 'REFUSAL' }))!.text).toContain('답하지 않았습니다');
  });

  it('나이 · 날짜를 공개 단위로만 바꾼 답은 위험 때문이라고 말하지 않는다', () => {
    const p = protection({
      releaseMode: 'ROUNDED',
      transformations: [
        { id: 't1', attribute: 'AGE', attributeLabel: '사례 1 나이', action: 'generalize', disclosedValue: '90~94세', caseRef: '사례1', floor: true },
        { id: 't2', attribute: 'PERIOD', attributeLabel: '사례 1 시기', action: 'generalize', disclosedValue: '2018-03', caseRef: '사례1', floor: true },
      ],
    });
    expect(protectionNote(p)).toEqual({ tone: 'range', text: '나이 · 날짜는 정해진 공개 단위로 표시했습니다.' });
    const why = whyText(p, '사례 1');
    expect(why[0]).toContain('정해진 공개 단위로만');
    expect(why.join(' ')).not.toContain('환자가 적어');
    for (const t of why) expect(t).not.toMatch(RISK_NUMBER);
    // 위험 때문에 넓힌 값이 하나라도 있으면 그 설명이 먼저다
    const mixed = protection({
      transformations: [...p.transformations, { id: 't3', attribute: 'MED', attributeLabel: '사례 1 처방 약', action: 'generalize', disclosedValue: '항생제', caseRef: '사례1' }],
    });
    expect(protectionNote(mixed)!.text).toContain('정확한 값 대신 범위로');
  });

  it('통과하지 못한 사례를 뺀 답은 그 사례를 따로 설명하고, 뺀 사례의 값은 가린 항목 설명에 섞지 않는다', () => {
    const p = protection({
      releaseMode: 'CASE_DROPPED',
      transformations: [
        { id: 't1', attribute: 'PERIOD', attributeLabel: '사례 1 시기', action: 'suppress', disclosedValue: null, caseRef: '사례1' },
        { id: 't3', attribute: 'DX', attributeLabel: '사례 2 진단', action: 'suppress', disclosedValue: null, caseRef: '사례2', dropped: true },
        { id: 't4', attribute: 'MED', attributeLabel: '사례 2 처방 약', action: 'suppress', disclosedValue: null, caseRef: '사례2', dropped: true },
      ],
    });
    expect(protectionNote(p)!.text).toBe('환자를 알아볼 위험이 있는 사례는 이 답에서 뺐습니다.');
    const why = whyText(p, '사례 1');
    expect(why[0]).toContain('사례 2는');
    expect(why[0]).toContain('이 답에서 뺐습니다');
    expect(why[1]).toContain('사례 1 환자의 시기는');
    expect(why[1]).not.toContain('진단');
    for (const t of why) expect(t).not.toMatch(RISK_NUMBER);
  });

  it('항목 이름은 사례 접두어를 떼고, 모르는 코드는 백엔드 이름을 쓴다', () => {
    expect(attrName({ attribute: 'PERIOD', attributeLabel: '사례 1 시기' })).toBe('시기');
    expect(attrName({ attribute: 'DATE', attributeLabel: '시술 시점' })).toBe('시술 시점');
    expect(attrName({ attribute: 'X', attributeLabel: '사례 3 무엇' })).toBe('무엇');
  });
});

const texts = (run: Inline[]) => run.map((p) => (p.bold ? `**${p.seg.text}**` : p.seg.text)).join('');

describe('답 나누기', () => {
  it("'사례N · [기록M] 항목: 값' 줄을 사례 · 항목 · 출처 · 값으로 나눈다", () => {
    const { blocks } = parseAnswer([
      { kind: 'text', text: '사례1 · [기록11] 처방 약 시작일: ' },
      { kind: 'disclosure', text: '(비공개)', transformationId: 't1' },
      { kind: 'text', text: '\n사례2 · 성별: ' },
      { kind: 'disclosure', text: '여성', transformationId: 't2' },
    ]);
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ kind: 'fact', caseRef: '사례1', field: '처방 약 시작일', source: '기록11' });
    expect(blocks[1]).toMatchObject({ kind: 'fact', caseRef: '사례2', field: '성별', source: null });
    expect(blocks[1].kind === 'fact' && blocks[1].value.map((p) => p.seg)).toEqual([{ kind: 'disclosure', text: '여성', transformationId: 't2' }]);
  });

  it('이어진 줄은 한 문단, 빈 줄에서 문단이 나뉜다', () => {
    const { blocks } = parseAnswer([{ kind: 'text', text: '사례 B는 60~64세에 시술을 받았습니다.\n처방은 아래와 같습니다.\n\n다음 문단입니다.' }]);
    expect(blocks.map((b) => b.kind)).toEqual(['para', 'para']);
    expect(blocks[0].kind === 'para' && blocks[0].lines.map(texts)).toEqual(['사례 B는 60~64세에 시술을 받았습니다.', '처방은 아래와 같습니다.']);
  });

  it('실제 LLM 답의 마크다운 기호(#, **, 목록, 가로줄)는 보이지 않고 모양으로 나뉜다', () => {
    const { blocks, pieces } = parseAnswer([
      { kind: 'text', text: '## 유사 사례 요약\n\n### 사례 2\n- **진단**: Acute bronchitis\n- 처방: ' },
      { kind: 'disclosure', text: '(비공개)', transformationId: 't1' },
      { kind: 'text', text: '\n  - 기간 `7일`\n1) 첫째\n---\n**주목할 점** 끝' },
    ]);
    expect(blocks.map((b) => b.kind)).toEqual(['heading', 'heading', 'list', 'rule', 'para']);
    expect(blocks[0]).toMatchObject({ kind: 'heading', level: 2 });
    const list = blocks[2].kind === 'list' ? blocks[2].items : [];
    expect(list.map((it) => [it.depth, it.marker, texts(it.content)])).toEqual([
      [0, null, '**진단**: Acute bronchitis'],
      [0, null, '처방: (비공개)'],
      [1, null, '기간 7일'],
      [0, '1.', '첫째'],
    ]);
    expect(blocks[4].kind === 'para' && texts(blocks[4].lines[0])).toBe('**주목할 점** 끝');
    expect(pieces.map((p) => p.seg.text).join('|')).not.toMatch(/[#*`]/);
    expect(pieces.map((p) => p.k)).toEqual(pieces.map((_, i) => i)); // 읽는 순서 번호
  });

  it('표는 머리 줄 · 구분 줄을 알아보고, 칸 안의 보호 값 조각을 그대로 둔다', () => {
    const { blocks } = parseAnswer([
      { kind: 'text', text: '| 사례 | 나이 | 처방 |\n|---|:---:|---|\n| 사례1 | ' },
      { kind: 'disclosure', text: '90~94세', transformationId: 't1' },
      { kind: 'text', text: ' | amoxicillin |\n| 사례2 | - | ' },
      { kind: 'disclosure', text: '(비공개)', transformationId: 't2' },
      { kind: 'text', text: ' |\n\n| 다른 | 표 |' },
    ]);
    expect(blocks.map((b) => b.kind)).toEqual(['table', 'table']);
    const t = blocks[0].kind === 'table' ? blocks[0] : null;
    expect(t?.head?.map(texts)).toEqual(['사례', '나이', '처방']);
    expect(t?.rows.map((r) => r.map(texts))).toEqual([
      ['사례1', '90~94세', 'amoxicillin'],
      ['사례2', '-', '(비공개)'],
    ]);
    expect(t?.rows[0][1][0].seg.kind).toBe('disclosure');
    expect(blocks[1].kind === 'table' && blocks[1].head).toBeNull(); // 빈 줄 뒤는 다른 표
  });

  it('짝이 없는 ** 하나 때문에 뒤가 모두 굵어지지 않는다', () => {
    const { blocks } = parseAnswer([{ kind: 'text', text: '**굵게** 보통 ** 남은 글' }]);
    expect(blocks[0].kind === 'para' && texts(blocks[0].lines[0])).toBe('**굵게** 보통  남은 글');
  });
});

const entry = (over: Partial<DisclosureHistoryEntry>): DisclosureHistoryEntry => ({
  entryId: `e-${Math.random()}`,
  turn: 0,
  attribute: 'DX',
  attributeLabel: '진단',
  action: 'allow',
  description: 'Acute bronchitis',
  value: 'Acute bronchitis',
  ...over,
});

const cases = [1, 2, 3].map((n) => ({ caseId: `case-${n}`, label: `사례 ${n}`, diagnosis: 'Acute bronchitis', description: '', similarityRank: n }));

describe('사례 노트', () => {
  const e1 = [
    entry({}),
    entry({ attribute: 'MED', attributeLabel: '처방 약', value: 'loratadine 5 MG' }),
    entry({ turn: 3, attribute: 'PERIOD', attributeLabel: '시기', action: 'suppress', value: null, description: '가림 (그대로면 후보 1명)' }),
    entry({ turn: 5, attribute: 'SEX', attributeLabel: '성별', action: 'allow', value: '남성' }),
  ];
  const sessions: Record<string, ConversationSession> = {
    'case-1': {
      sessionId: 's1',
      caseId: 'case-1',
      questionCount: 1,
      messages: [{ messageId: 'u1', caseId: 'case-1', role: 'user', turn: 1, engineTurn: 3, createdAt: '', status: 'sent', segments: [{ kind: 'text', text: '시술 시기?' }] }],
    },
    'case-2': {
      sessionId: 's2',
      caseId: 'case-2',
      questionCount: 1,
      messages: [{ messageId: 'u2', caseId: 'case-2', role: 'user', turn: 1, engineTurn: 5, createdAt: '', status: 'sent', segments: [{ kind: 'text', text: '모두 성별은?' }] }],
    },
  };
  const all = {
    'case-1': e1,
    'case-2': [entry({}), entry({ turn: 5, attribute: 'SEX', attributeLabel: '성별', value: '남성' })],
    'case-3': [entry({}), entry({ turn: 5, attribute: 'SEX', attributeLabel: '성별', value: '여성' })],
  };

  it('속성은 정해진 순서로 모으고 가린 값은 텍스트 없이 둔다', () => {
    const note = buildCaseNote({ caseId: 'case-1', entries: e1, allEntries: all, sessions, cases });
    expect(note.properties.map((p) => p.label)).toEqual(['진단', '처방 약', '시기', '성별']);
    expect(note.properties[2].values).toEqual([{ text: null, action: 'suppress', turns: [3] }]);
  });

  it('연결된 질문은 대화 전체 턴으로 질문을 찾고, 다른 사례 대화에서 한 질문도 잇는다', () => {
    const note = buildCaseNote({ caseId: 'case-1', entries: e1, allEntries: all, sessions, cases });
    expect(note.backlinks.map((b) => [b.turn, b.askedIn, b.messageId, b.questionNo])).toEqual([
      [0, null, null, null],
      [3, 'case-1', 'u1', 1],
      [5, 'case-2', 'u2', 1],
    ]);
    expect(note.backlinks[2].askedInLabel).toBe('사례 2');
  });

  it('같은 값이 나온 다른 사례를 모은다 (가린 값은 제외)', () => {
    const note = buildCaseNote({ caseId: 'case-1', entries: e1, allEntries: all, sessions, cases });
    expect(note.linked.map((l) => [l.label, l.value, l.cases.map((c) => c.label)])).toEqual([
      ['진단', 'Acute bronchitis', ['사례 2', '사례 3']],
      ['성별', '남성', ['사례 2']],
    ]);
  });

  it('Mock처럼 대화 전체 턴이 없으면 그 사례의 질문 번호로 찾는다', () => {
    const mockSessions: Record<string, ConversationSession> = {
      'case-1': {
        sessionId: 's1',
        caseId: 'case-1',
        questionCount: 2,
        messages: [
          { messageId: 'm1', caseId: 'case-1', role: 'user', turn: 1, createdAt: '', status: 'sent', segments: [{ kind: 'text', text: '첫 질문' }] },
          { messageId: 'm2', caseId: 'case-1', role: 'user', turn: 2, createdAt: '', status: 'sent', segments: [{ kind: 'text', text: '둘째 질문' }] },
        ],
      },
    };
    const note = buildCaseNote({ caseId: 'case-1', entries: [entry({ turn: 2, attribute: 'AGE', attributeLabel: '나이', action: 'generalize', value: '60~64세' })], allEntries: {}, sessions: mockSessions, cases });
    expect(note.backlinks[0]).toMatchObject({ messageId: 'm2', question: '둘째 질문' });
  });

  it('value가 없는 백엔드(연구 서버)는 설명 문장에서 값을 꺼낸다', () => {
    expect(entryValue(entry({ value: undefined, description: '검색 결과 노출 · Acute bronchitis' }))).toBe('Acute bronchitis');
    expect(entryValue(entry({ value: undefined, description: 'Massachusetts (그대로 공개)' }))).toBe('Massachusetts');
    expect(entryValue(entry({ value: undefined, action: 'generalize', description: '1세 단위 → 5세 구간' }))).toBe('5세 구간');
    expect(entryValue(entry({ value: undefined, action: 'suppress', description: '공개하지 않음' }))).toBeNull();
  });
});
