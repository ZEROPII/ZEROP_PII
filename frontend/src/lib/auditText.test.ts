// 감사 기록 화면의 글 (ADR-0030): 환자 기호 · 열람 메모 · 고위험 승인 · 규칙 걸기 실패
import { describe, expect, it } from 'vitest';
import type { AuditEntry } from '../types/monitor';
import { ACTION_KO, detailOf, subjectsOf } from './auditText';

function entry(over: Partial<AuditEntry>): AuditEntry {
  return { id: 'A0001', at: 0, actor: 'privacy1', action: 'reviewed', session: 's1', trial: 'T0014', ...over };
}

describe('감사 기록 글', () => {
  it('원문 열람: 고른 사유와 적은 내용을 함께, 다룬 환자는 기호로', () => {
    const e = entry({
      action: 'reveal', reason: '오탐 확인', note: '사례 2 처방 가림이 오탐인지 확인', patient_tag: 'P-0a1b2c',
      subjects: [{ case: '사례1', tag: 'P-111111' }, { case: '사례2', tag: 'P-222222' }],
    });
    expect(detailOf(e)).toBe('사유: 오탐 확인 · 사례 2 처방 가림이 오탐인지 확인');
    expect(subjectsOf(e)).toBe('지금 환자 P-0a1b2c · 과거 환자 사례 1 P-111111, 사례 2 P-222222');
  });

  it('공개 승인: 공개 뒤 후보 수, 기준 아래면 그렇다고 적는다', () => {
    const items = [{ turn: 1, case: '사례1', attribute: 'PERIOD' }];
    expect(detailOf(entry({ action: 'approve_release', items, k_min: 1, high_risk: true, reason: '약물 조정에 시작 시기가 꼭 필요함' }))).toBe(
      '사례 1 시기 · 공개 뒤 후보 1명 (기준 아래) · 사유: 약물 조정에 시작 시기가 꼭 필요함',
    );
    expect(detailOf(entry({ action: 'approve_release', items, k_min: 9, high_risk: false, reason: '시기 확인 필요' }))).toBe('사례 1 시기 · 공개 뒤 후보 9명 · 사유: 시기 확인 필요');
    // 요청한 사례에서 이번에 공개하지 않은 단서 (ADR-0031)
    expect(detailOf(entry({ action: 'approve_release', items, kept: [{ case: '사례1', attribute: 'AGE' }], k_min: 9, reason: '시기 확인 필요' }))).toBe(
      '사례 1 시기 · 공개하지 않음: 사례 1 나이 · 공개 뒤 후보 9명 · 사유: 시기 확인 필요',
    );
  });

  it('규칙 걸기 실패도 이름과 까닭이 보인다', () => {
    const e = entry({ action: 'add_rule_failed', case: '사례9', attribute: 'MED', why: '이 대화에 없는 사례입니다.' });
    expect(ACTION_KO[e.action]).toBe('규칙 걸기 실패');
    expect(detailOf(e)).toBe('사례 9 처방 약 · 걸지 못한 까닭: 이 대화에 없는 사례입니다.');
  });

  it('기호가 없는 기록(로그인 등)에는 다룬 환자 줄이 없다', () => {
    expect(subjectsOf(entry({ action: 'login', session: null }))).toBeNull();
    expect(subjectsOf(entry({ action: 'clinic_start', patient_tag: 'P-0a1b2c', subjects: [] }))).toBe('지금 환자 P-0a1b2c');
    expect(subjectsOf(entry({ action: 'emr_prefetch', subjects: [{ case: '사례1', tag: null }] }))).toBeNull();
  });
});

describe('질문 미리 세기 기록 (ADR-0032)', () => {
  it('보안 담당자 미리 세기는 질문 본문 없이 사례와 글자 수만', () => {
    expect(ACTION_KO.watch_preflight).toBe('보안 담당자 질문 미리 세기');
    expect(detailOf(entry({ action: 'watch_preflight', case: '사례2', question_chars: 14 }))).toBe('사례 2 · 질문 14자');
  });

  it('의료진 미리 확인 한도 넘음', () => {
    expect(detailOf(entry({ action: 'preflight_limited', case: '사례1' }))).toBe('사례 1 · 짧은 시간에 미리 확인을 많이 써서 판정 없이 돌려줌');
  });
});

describe('EMR 접근 기록 글 (ADR-0034)', () => {
  it('담당 외 거부 · 예외 열람 · 검토 · 보안 담당자 차트 열람: 다룬 환자는 그냥 환자 기호', () => {
    const denied = entry({ action: 'emr_denied', session: null, trial: null, what: 'launch', patient_tag: 'P-0a1b2c' });
    expect(ACTION_KO[denied.action]).toBe('담당 외 환자라 막음');
    expect(detailOf(denied)).toBe('막은 요청: 진료 지원 AI 열기');
    expect(subjectsOf(denied)).toBe('환자 P-0a1b2c');
    expect(detailOf(entry({ action: 'break_glass', reason: '협진', note: '호흡기내과 협진 의뢰 확인', hours: 12 }))).toBe('사유: 협진 · 호흡기내과 협진 의뢰 확인 · 12시간');
    expect(detailOf(entry({ action: 'break_glass_review', review: 'flag', review_label: '확인 필요 (열람 끝냄)', note: '협진 기록 없음', grant: 3 }))).toBe(
      '확인 필요 (열람 끝냄) · 협진 기록 없음 · 예외 열람 3번',
    );
    expect(detailOf(entry({ action: 'emr_reveal', reason: '예외 열람 검토', note: '협진 사유와 차트 대조' }))).toBe('사유: 예외 열람 검토 · 협진 사유와 차트 대조');
  });

  it('협진 의뢰 · 멈춤 (ADR-0035 · ADR-0036)', () => {
    const sent = entry({ action: 'emr_consult', session: null, trial: null, to: '박준호 (의료진 · doctor2)', note: '약 조정 협진 부탁드립니다', patient_tag: 'P-0a1b2c' });
    expect(ACTION_KO[sent.action]).toBe('협진 의뢰 보냄');
    expect(detailOf(sent)).toBe('받는 의료진: 박준호 (의료진 · doctor2) · 약 조정 협진 부탁드립니다');
    expect(subjectsOf(sent)).toBe('환자 P-0a1b2c');
    expect(detailOf(entry({ action: 'emr_consult_open', sender: '김서연', hours: 12 }))).toBe('김서연 선생님의 의뢰 · 12시간');
    expect(detailOf(entry({ action: 'emr_consult_cancel', note: '환자가 전원했습니다' }))).toBe('환자가 전원했습니다');
    expect(ACTION_KO.clinic_stop).toBe('의료진이 질문을 멈춤');
    expect(detailOf(entry({ action: 'clinic_stop', calls: 2 }))).toBe('대상 AI · 확인 호출 2번 뒤 멈춤');
  });

  it('담당 배정: 규칙으로 나눈 수 · 명령으로 바꾼 의료진', () => {
    expect(detailOf(entry({ action: 'emr_assign', assigned: 115, counts: { doctor1: 58, doctor2: 57 } }))).toBe('담당 없는 환자 115명 나눔 · doctor1 58명, doctor2 57명');
    expect(detailOf(entry({ action: 'emr_assign', reset: true, assigned: 115, counts: { doctor1: 39 } }))).toBe('모두 지우고 다시 나눔 · doctor1 39명');
    expect(detailOf(entry({ action: 'emr_assign', change: 'add', clinician: '박준호 (doctor2)', patient_tag: 'P-0a1b2c' }))).toBe('박준호 (doctor2) · 담당으로 더함');
  });
});
