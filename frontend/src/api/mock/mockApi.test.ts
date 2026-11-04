import { describe, expect, it } from 'vitest';
import { createMockApi } from './mockApi';

const fast = () => createMockApi({ latency: [0, 0] });

async function ask(api: ReturnType<typeof fast>, caseId: string, question: string) {
  const session = await api.getConversation(caseId);
  return api.sendQuestion({ caseId, sessionId: session.sessionId, question, clientMessageId: `c-${Math.random()}` });
}

describe('mock api', () => {
  it('초기 k 값은 사례 A~E 예시와 같다', async () => {
    const risks = await fast().listRiskStates();
    expect(Object.fromEntries(risks.map((r) => [r.caseId, r.k]))).toEqual({
      'case-a': 7,
      'case-b': 31,
      'case-c': 18,
      'case-d': 5,
      'case-e': 42,
    });
    const d = risks.find((r) => r.caseId === 'case-d')!;
    expect(d.disclosureAllowed).toBe(false);
    expect(d.policyDecision).toBe('restrict');
  });

  it('사례 A 시드 대화는 질문 3회와 공개 이력 5건(턴 0~2)을 가진다', async () => {
    const api = fast();
    const session = await api.getConversation('case-a');
    expect(session.questionCount).toBe(3);
    const history = await api.getDisclosureHistory('case-a');
    expect(history.entries.map((e) => [e.turn, e.attributeLabel, e.action])).toEqual([
      [0, '진단 · 시술명', 'allow'],
      [1, '성별', 'allow'],
      [1, '거주 주', 'allow'],
      [2, '나이', 'generalize'],
      [2, '시술 시점', 'suppress'],
    ]);
  });

  it('나이 질문은 5세 구간으로 일반화하고 원본 나이를 응답에 담지 않는다', async () => {
    const api = fast();
    const res = await ask(api, 'case-b', '사례 B 환자는 몇 살에 시술을 받았나요?');
    const age = res.assistantMessage.protection!.transformations.find((t) => t.attribute === 'AGE')!;
    expect(age.action).toBe('generalize');
    expect(age.disclosedValue).toBe('60~64세');
    expect(age.levelDescription).toBe('1세 단위 → 5세 구간');
    expect(res.riskState.k).toBe(12);
    expect(res.newDisclosures).toHaveLength(1);
    expect(JSON.stringify(res)).not.toMatch(/rawK|rawValue/);
  });

  it('한 사례의 공개는 다른 사례의 k와 이력에 영향을 주지 않는다', async () => {
    const api = fast();
    await ask(api, 'case-b', '사례 B 환자 나이와 시술 시점은?');
    const risks = await api.listRiskStates();
    expect(risks.find((r) => r.caseId === 'case-a')!.k).toBe(7);
    expect(risks.find((r) => r.caseId === 'case-b')!.k).toBe(9);
    expect((await api.getDisclosureHistory('case-a')).entries).toHaveLength(5);
  });

  it('새 QI가 없는 질문은 질문 횟수가 늘어도 k를 바꾸지 않는다', async () => {
    const api = fast();
    const res = await ask(api, 'case-a', '시술 후 처방 기간은 어떻게 되나요?');
    expect(res.riskState.k).toBe(7);
    expect(res.riskState.version).toBeGreaterThan(1);
    expect(res.newDisclosures).toHaveLength(0);
  });

  it('거주 도시 질문은 사전 경고를 내고, 전송하면 비공개 처리된다', async () => {
    const api = fast();
    const q = '사례 A 환자는 어느 도시에 살았나요?';
    const pre = await api.assessPreflight('case-a', 'session-case-a', q);
    expect(pre.requiresWarning).toBe(true);
    expect(pre.message).toContain('7명에서 3명');
    expect(pre.suggestions.length).toBeGreaterThan(0);

    const res = await ask(api, 'case-a', q);
    const loc = res.assistantMessage.protection!.transformations[0];
    expect(loc.action).toBe('suppress');
    expect(loc.disclosedValue).toBeNull();
    expect(res.riskState.k).toBe(7);
  });

  it('안전한 질문은 경고하지 않는다', async () => {
    const pre = await fast().assessPreflight('case-a', 'session-case-a', '시술 후 처방 기간은?');
    expect(pre.requiresWarning).toBe(false);
  });

  it('사전 경고는 의료진 화면용 plannedAction을 함께 준다', async () => {
    const api = fast();
    const pre = await api.assessPreflight('case-a', 'session-case-a', '사례 A 환자는 어느 도시에 살았나요?');
    expect(pre.plannedAction).toBe('suppress');
    const calm = await api.assessPreflight('case-a', 'session-case-a', '시술 후 처방 기간은?');
    expect(calm.plannedAction).toBeNull();
  });

  it('공개 이력에는 답에 나간 값이 있고, 가린 값은 null이다', async () => {
    const api = fast();
    await ask(api, 'case-b', '사례 B 환자 나이와 시술 시점은?');
    const entries = (await api.getDisclosureHistory('case-b')).entries;
    expect(entries.find((e) => e.attribute === 'AGE')!.value).toBe('60~64세');
    expect(entries.find((e) => e.turn === 0)!.value).toBe('Coronary arteriosclerosis');
    const hidden = (await api.getDisclosureHistory('case-a')).entries.find((e) => e.action === 'suppress')!;
    expect(hidden.value).toBeNull();
  });

  it('세부 정보 요청에는 예시 답장이 붙고, 잘못된 메시지는 거절한다', async () => {
    const api = createMockApi({ latency: [0, 0], autoReplyMs: 0 });
    expect(await api.listClinicMessages!()).toEqual([]);
    const list = await api.postClinicMessage!({ kind: 'access_request', text: '사례 A 시술 시점이 필요합니다', caseId: 'case-a' });
    expect(list.map((m) => [m.sender, m.kind, m.caseLabel])).toEqual([
      ['clinician', 'access_request', '사례 A'],
      ['security', 'reply', '사례 A'],
    ]);
    expect(list[1].text).toContain('예시');
    await expect(api.postClinicMessage!({ kind: 'reply', text: 'x' })).rejects.toThrow('2자 이상');
    await expect(api.postClinicMessage!({ kind: 'reply', text: '없는 사례', caseId: 'case-z' })).rejects.toThrow('존재하지 않는 사례');
  });

  it('오류 트리거 문구는 ApiError를 낸다', async () => {
    await expect(ask(fast(), 'case-a', '테스트 #오류')).rejects.toThrow('Mock 서버 오류');
  });
});
