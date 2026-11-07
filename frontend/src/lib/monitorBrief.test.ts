// 관제 상세 맨 위 세 줄 (ADR-0030)
import { describe, expect, it } from 'vitest';
import type { Approval, MonitorDetail, MonitorRow, ThreadMessage, TurnView } from '../types/monitor';
import { detailBrief } from './monitorBrief';

function row(over: Partial<MonitorRow> = {}): MonitorRow {
  return {
    id: 's1', trial_id: 'T0014', source: 'clinic', source_label: '의료진 화면', qtype_label: '처방', turns: 3, suppressed: 0, generalized: 0,
    status: 'safe', status_label: '이상 없음', focus_case: '사례1', k_if_raw: null, k_now: 40, repeated: [], flag: null, violated: [],
    approved_low: [], asked_subjects: [], repeat_subjects: [], last_question: null, last_active: 0, created: 0, review: null, needs_review: false,
    messages: 0, pending_request: false, awaiting_clinician: false, request_case: null, ...over,
  };
}

function turn(n: number, over: Partial<TurnView> = {}): TurnView {
  return { turn: n, question: `질문 ${n}`, mode: 'live', refused: false, lines: [], change_notes: [], target_qi: null, picked_by: null, ...over };
}

function detail(r: MonitorRow, over: Partial<MonitorDetail> = {}): MonitorDetail {
  const arm = { label: '의료진 화면', case_A: '사례1', k_series: {}, first_violation_A: null, violated_cases: [], utility: null, decisions: {}, turns: [turn(0), turn(1)] };
  return {
    id: r.id, trial_id: r.trial_id, patient: null, qtype_label: '처방', profile_label: '', turn: r.turns, budget: 10, k_req: 5, p_ref: 461,
    source: 'clinic', source_label: '의료진 화면', arms: { C1: arm, C1S: arm, C0: arm }, retrieval: [], row: r, revealed: false, live_arm: 'C1',
    messages: [], ...over,
  };
}

const request: ThreadMessage = { id: 'm1', at: 0, sender: 'clinician', kind: 'access_request', kind_label: '세부 정보 요청', case: '사례2', text: '시기를 알려 주세요', actor: 'doctor1' };

describe('관제 상세 세 줄 요약', () => {
  it('위험한 답이 없으면 할 일도 없다', () => {
    const b = detailBrief(detail(row()));
    expect(b.risk).toContain('위험한 답은 없었습니다');
    expect(b.done).toBe('모든 답을 그대로 보냈습니다.');
    expect(b.todo).toBe('할 일은 없습니다.');
    expect(b.tone).toBeNull();
  });

  it('가린 답: 그대로였다면 특정될 수 있었다 · 지킨 후보 수', () => {
    const r = row({ status: 'danger', suppressed: 2, k_if_raw: 1, k_now: 12 });
    const b = detailBrief(detail(r));
    expect(b.risk).toBe('사례 1 환자를 좁히는 답이었습니다. 그대로 냈다면 후보가 1명으로 줄어 환자가 특정될 수 있었습니다.');
    expect(b.done).toBe('값 2개를 가려 답했습니다. 사례 1 후보 12명을 지켰습니다.');
    expect(b.todo).toBe('할 일은 없습니다. 방어 규칙이 처리했습니다.');
  });

  it('의료진 세부 정보 요청이 기다리면 요청 상자로 이끈다', () => {
    const r = row({ status: 'danger', suppressed: 1, k_if_raw: 3, pending_request: true, focus_case: '사례2', flag: '의료진 세부 정보 요청' });
    const b = detailBrief(detail(r, { messages: [request] }));
    expect(b.todo).toContain('사례 2의 세부 정보를 요청했습니다');
    expect(b.todo).toContain("'값 공개 승인'");
    expect(b.tone).toBe('request');
  });

  it('방어 규칙을 거치고도 기준 아래면 경보: 원문을 열고 규칙을 걸라고 한다', () => {
    const r = row({ status: 'danger', suppressed: 1, k_if_raw: 2, k_now: 3, violated: ['사례1'] });
    const b = detailBrief(detail(r));
    expect(b.risk).toBe('사례 1은 방어 규칙을 거치고도 후보가 기준 5명 아래로 내려갔습니다.');
    expect(b.done).not.toContain('지켰습니다');
    expect(b.todo).toContain("'이 대화에 규칙 걸기'");
    expect(b.tone).toBe('danger');
  });

  it('승인 공개로 기준 아래가 된 사례는 경보가 아니라 승인 공개로 적는다', () => {
    const ap: Approval = {
      id: 'AP1', at: 0, by: 'privacy1', reason: '약물 조정 판단에 시작 시기가 꼭 필요함', high_risk: true, k_after: { 사례1: 1 },
      items: [{ turn: 1, case: '사례1', index: 0, attribute: 'PERIOD', attribute_label: '시점', value: null, after_turn: 1 }],
    };
    const r = row({ status: 'danger', suppressed: 1, k_if_raw: 1, k_now: 1, approved_low: ['사례1'] });
    const d = detail(r, { approvals: [ap], arms: detail(r).arms });
    d.arms.C1.turns = [turn(0), turn(1, { cases: { 사례1: { k: 9, k_if_raw: 1 } } }), turn(2, { cases: { 사례1: { k: 1, k_if_raw: 1 } } })];
    const b = detailBrief(d);
    expect(b.risk).not.toContain('기준 5명 아래로 내려갔습니다');
    expect(b.done).toContain('사례 1 후보 9명을 지켰습니다');                      // 승인 전까지 지킨 수
    expect(b.done).toContain('값 1개를 공개했습니다 (고위험 승인)');
    expect(b.done).toContain('경보가 아니라 승인 공개로 셉니다');
    expect(b.tone).toBeNull();
  });

  it('같은 과거 환자를 다른 대화에서도 물었으면 기호와 대화 수를 적고 확인 요청을 권한다', () => {
    const r = row({
      needs_review: true,
      flag: '같은 과거 환자 다른 대화에서도 조회',
      repeat_subjects: [
        { case: '사례1', tag: 'P-0d0d0d', conversations: 1, clinicians: 1 },
        { case: '사례2', tag: 'P-3f9a1c', conversations: 2, clinicians: 2 },
      ],
    });
    const b = detailBrief(detail(r));
    expect(b.risk).toContain('사례 1(P-0d0d0d)은 최근 다른 대화 1건에서도 물었습니다.');
    expect(b.risk).toContain('사례 2(P-3f9a1c)는 최근 다른 대화 2건에서도 물었습니다 (물은 의료진 2명).');
    expect(b.todo).toContain('의료진에게 확인 요청');
  });

  it('지난 대화는 메시지를 보낼 수 없다고 적고, 검토했으면 할 일이 없다', () => {
    const r = row({ archived: true, needs_review: true, repeated: ['사례1'], status: 'danger', suppressed: 2, k_if_raw: 2 });
    expect(detailBrief(detail(r, { archived: true })).todo).toContain('메시지는 보낼 수 없습니다');
    const done = row({ archived: true, review: { action: 'reviewed', label: '검토 완료', at: 0, actor: 'privacy1', note: null } });
    expect(detailBrief(detail(done, { archived: true })).todo).toContain('할 일은 없습니다');
  });
});
