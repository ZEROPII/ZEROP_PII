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
