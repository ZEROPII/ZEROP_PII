// 묻는 범위 안내 (ADR-0029): 질문 문장과 묻는 범위가 어긋날 때만 알린다.
import { describe, expect, it } from 'vitest';
import { josa, josaRo } from './korean';
import { caseNoOf, caseNumbers, scopeHint } from './scopeHint';

describe('묻는 범위 안내', () => {
  it('사례 하나 범위에서 여러 사례를 묻으면 전체로 물을지 묻고 Enter를 한 번 붙잡는다', () => {
    for (const q of [
      '이 사례들에서 아세트아미노펜 말고 같이 쓴 기침약이나 항생제 있었어?',
      '찾은 사례 중에 고혈압 환자가 있었나요?',
      '사례마다 처방 기간이 어떻게 달랐나요?',
      '공통으로 쓴 약을 알려 주세요',
      '사례1과 사례3의 처방을 비교해 주세요',
      '사례 1, 2의 처방 기간은?',
      '5개 사례 모두 같은 약을 썼나요?',
    ]) {
      expect(scopeHint(q, 'case', 1, 5), q).toEqual({ kind: 'toAll', hold: true });
    }
  });

  it('사례 하나 범위에서 다른 사례 하나를 묻으면 그 사례로 옮길지 묻는다', () => {
    expect(scopeHint('사례3 환자에게 처방된 약은?', 'case', 1, 5)).toEqual({ kind: 'otherCase', caseNo: 3, hold: true });
    expect(scopeHint('2번 사례의 복용 기간은?', 'case', 1, 5)).toEqual({ kind: 'otherCase', caseNo: 2, hold: true });
  });

  it('질문과 범위가 맞으면 아무것도 보이지 않는다', () => {
    expect(scopeHint('사례1 환자에게 처방된 약과 복용 기간을 알려 주세요.', 'case', 1, 5)).toBeNull();
    expect(scopeHint('처방된 약과 복용 기간을 알려 주세요.', 'case', 1, 5)).toBeNull();
    expect(scopeHint('찾은 사례들에서 공통으로 쓴 약을 정리해 주세요.', 'all', 1, 5)).toBeNull();
    expect(scopeHint('제 환자는 고혈압으로 lisinopril 복용 중입니다. 비슷한 환자가 있었나요?', 'all', 1, 5)).toBeNull();
    // 찾은 사례에 없는 번호 · 짧은 입력 · 사례가 하나뿐이면 판단하지 않는다
    expect(scopeHint('사례9 처방은?', 'case', 1, 5)).toBeNull();
    expect(scopeHint('사례', 'case', 1, 5)).toBeNull();
    expect(scopeHint('이 사례들에서 쓴 약', 'case', 1, 1)).toBeNull();
  });

  it('전체 범위에서 사례 하나만 물으면 그 사례 대화를 권하지만 붙잡지 않는다', () => {
    expect(scopeHint('사례 4는 sodium fluoride를 얼마나 오래 썼나요?', 'all', 1, 5)).toEqual({ kind: 'oneCase', caseNo: 4, hold: false });
  });

  it('사례 번호 읽기', () => {
    expect(caseNumbers('사례1, 사례 03, 4번 사례, 사례12', 5)).toEqual([1, 3, 4]);
    expect(caseNoOf('사례 3')).toBe(3);
    expect(caseNoOf('사례 A')).toBeNull();
  });

  it('숫자 뒤 조사: 사례 1로 · 사례 3으로 · 사례 2가', () => {
    expect(josaRo('사례 1')).toBe('사례 1로');
    expect(josaRo('사례 3')).toBe('사례 3으로');
    expect(josaRo('사례 2')).toBe('사례 2로');
    expect(josaRo('사례 6')).toBe('사례 6으로');
    expect(josa('사례 2', '이', '가')).toBe('사례 2가');
    expect(josa('사례 1', '이라', '라')).toBe('사례 1이라');
  });
});
