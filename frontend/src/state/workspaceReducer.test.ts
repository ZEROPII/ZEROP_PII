import { describe, expect, it } from 'vitest';
import type { CaseRiskState, ChatMessage, SendQuestionResponse } from '../types/domain';
import { initialWorkspaceState, workspaceReducer, type WorkspaceState } from './workspaceReducer';

const risk = (caseId: string, k: number, version: number): CaseRiskState => ({
  caseId,
  k,
  riskLevel: 'caution',
  statusLabel: '주의',
  disclosureAllowed: true,
  policyDecision: 'allow',
  version,
  updatedAt: '2026-10-27T00:00:00Z',
});

const msg = (id: string, caseId: string, role: ChatMessage['role'], status: ChatMessage['status'] = 'sent'): ChatMessage => ({
  messageId: id,
  caseId,
  role,
  turn: 1,
  createdAt: '2026-10-27T00:00:00Z',
  segments: [{ kind: 'text', text: id }],
  status,
});

function seeded(): WorkspaceState {
  let s = workspaceReducer(initialWorkspaceState, {
    type: 'resource/success',
    key: 'riskStates',
    data: { a: risk('a', 7, 3), b: risk('b', 31, 1) },
  });
  for (const id of ['a', 'b']) {
    s = workspaceReducer(s, { type: 'session/success', caseId: id, session: { sessionId: `s-${id}`, caseId: id, messages: [], questionCount: 0 } });
    s = workspaceReducer(s, { type: 'disclosures/success', caseId: id, entries: [] });
  }
  return s;
}

describe('workspaceReducer', () => {
  it('응답은 요청한 사례에만 반영된다', () => {
    let s = seeded();
    s = workspaceReducer(s, { type: 'case/select', caseId: 'a' });
    s = workspaceReducer(s, { type: 'send/start', caseId: 'a', pending: msg('tmp', 'a', 'user', 'pending') });
    s = workspaceReducer(s, { type: 'case/select', caseId: 'b' });
    const response: SendQuestionResponse = {
      userMessage: msg('tmp', 'a', 'user'),
      assistantMessage: msg('ai', 'a', 'assistant'),
      riskState: risk('a', 5, 4),
      newDisclosures: [{ entryId: 'e1', turn: 1, attribute: 'AGE', attributeLabel: '나이', action: 'generalize', description: 'x' }],
    };
    s = workspaceReducer(s, { type: 'send/success', caseId: 'a', clientMessageId: 'tmp', response });

    expect(s.sessions.a.data!.messages.map((m) => [m.messageId, m.status])).toEqual([
      ['tmp', 'sent'],
      ['ai', 'sent'],
    ]);
    expect(s.sessions.a.data!.questionCount).toBe(1);
    expect(s.sessions.b.data!.messages).toHaveLength(0);
    expect(s.riskStates.data!.a.k).toBe(5);
    expect(s.riskStates.data!.b.k).toBe(31);
    expect(s.disclosures.a.data).toHaveLength(1);
    expect(s.disclosures.b.data).toHaveLength(0);
  });

  it('더 낮은 버전의 위험 상태는 무시한다', () => {
    let s = seeded();
    const response: SendQuestionResponse = {
      userMessage: msg('u', 'a', 'user'),
      assistantMessage: msg('ai', 'a', 'assistant'),
      riskState: risk('a', 40, 2),
      newDisclosures: [],
    };
    s = workspaceReducer(s, { type: 'send/success', caseId: 'a', clientMessageId: 'u', response });
    expect(s.riskStates.data!.a.k).toBe(7);
  });

  it('다른 사례가 함께 언급되면 그 사례의 위험 상태만 갱신하고 대화는 섞지 않는다', () => {
    let s = seeded();
    const response: SendQuestionResponse = {
      userMessage: msg('u', 'a', 'user'),
      assistantMessage: msg('ai', 'a', 'assistant'),
      riskState: risk('a', 7, 4),
      newDisclosures: [],
      relatedRiskStates: [risk('b', 12, 4)],
    };
    s = workspaceReducer(s, { type: 'send/success', caseId: 'a', clientMessageId: 'u', response });
    expect(s.riskStates.data!.b.k).toBe(12);
    expect(s.sessions.b.data!.messages).toHaveLength(0);
    expect(s.disclosures.b.status).toBe('idle');
    expect(s.disclosures.a.status).toBe('success');
  });

  it('전송 실패는 메시지를 failed로 두고 sendError를 남긴다', () => {
    let s = seeded();
    s = workspaceReducer(s, { type: 'send/start', caseId: 'a', pending: msg('tmp', 'a', 'user', 'pending') });
    s = workspaceReducer(s, { type: 'send/failure', caseId: 'a', clientMessageId: 'tmp', error: 'boom' });
    expect(s.sessions.a.data!.messages[0].status).toBe('failed');
    expect(s.sessions.a.sendError).toBe('boom');
    expect(s.sessions.a.status).toBe('success');
    s = workspaceReducer(s, { type: 'message/discard', caseId: 'a', messageId: 'tmp' });
    expect(s.sessions.a.data!.messages).toHaveLength(0);
    expect(s.sessions.a.sendError).toBeUndefined();
  });
  it('조용한 새로 고침은 보내는 중인 사례를 건드리지 않고, 바뀐 대화만 바꾼다', () => {
    let s = seeded();
    const fresh = { sessionId: 's-a', caseId: 'a', messages: [msg('u1', 'a', 'user'), msg('a1', 'a', 'assistant')], questionCount: 1 };
    s = workspaceReducer(s, { type: 'session/refresh', caseId: 'a', session: fresh });
    expect(s.sessions.a.data!.messages).toHaveLength(2);
    const same = workspaceReducer(s, { type: 'session/refresh', caseId: 'a', session: { ...fresh } });
    expect(same).toBe(s);
    const busy = workspaceReducer(s, { type: 'send/start', caseId: 'b', pending: msg('p', 'b', 'user', 'pending') });
    const after = workspaceReducer(busy, { type: 'session/refresh', caseId: 'b', session: { sessionId: 's-b', caseId: 'b', messages: [], questionCount: 0 } });
    expect(after.sessions.b.data!.messages.map((m) => m.messageId)).toEqual(['p']);
  });

  it('새로 받은 후보 수도 버전이 더 클 때만 반영한다', () => {
    const s = seeded();
    expect(workspaceReducer(s, { type: 'risk/apply', risk: risk('a', 1, 2) }).riskStates.data!.a.k).toBe(7);
    expect(workspaceReducer(s, { type: 'risk/apply', risk: risk('a', 6, 4) }).riskStates.data!.a.k).toBe(6);
  });
});
