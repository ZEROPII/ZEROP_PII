import { describe, expect, it } from 'vitest';
import { periodKo } from './format';

describe('periodKo: 기록 날짜 값을 진료 화면 말로 (ADR-0043)', () => {
  it('해 · 달 · 날 · 분기', () => {
    expect(periodKo('1998')).toBe('1998년');
    expect(periodKo('1998-12')).toBe('1998년 12월');
    expect(periodKo('2020-02-04')).toBe('2020년 2월 4일');
    expect(periodKo('1947-Q4')).toBe('1947년 4분기');
  });
  it('값 전체가 날짜가 아니면 그대로', () => {
    expect(periodKo('30~39세')).toBe('30~39세');
    expect(periodKo('1998년 12월부터 처방')).toBe('1998년 12월부터 처방');
    expect(periodKo('날짜 제약 없음')).toBe('날짜 제약 없음');
    expect(periodKo('19980')).toBe('19980');
  });
});
