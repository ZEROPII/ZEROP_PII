import { describe, expect, it } from 'vitest';
import { dateTime, daysWithinYear, sinceDay, timeLeft } from './time';

describe('예외 열람 시간 표시', () => {
  const now = new Date(2026, 10, 7, 9, 0, 0).getTime() / 1000;
  it('남은 시간은 시간 · 분 (분은 올림), 한 시간 안이면 분만', () => {
    expect(timeLeft(now + 12 * 3600, now)).toBe('12시간 남음');
    expect(timeLeft(now + 12 * 3600 - 5, now)).toBe('12시간 남음');                 // 막 연 열람이 '11시간 59분'으로 보이지 않게
    expect(timeLeft(now + 11 * 3600 + 30 * 60, now)).toBe('11시간 30분 남음');
    expect(timeLeft(now + 25 * 60, now)).toBe('25분 남음');
    expect(timeLeft(now + 10, now)).toBe('1분 남음');
    expect(timeLeft(now - 1, now)).toBe('끝남');
  });
  it('같은 해는 월-일 시:분, 다른 해는 연도까지', () => {
    expect(dateTime(new Date(2026, 0, 3, 7, 5).getTime() / 1000, now)).toBe('01-03 07:05');
    expect(dateTime(new Date(2025, 11, 31, 23, 59).getTime() / 1000, now)).toBe('2025-12-31 23:59');
  });
});

describe('내원 흐름 날짜', () => {
  const now = new Date(2026, 10, 7, 12).getTime();
  it('지난 기간은 달 · 해로 (한 달이 안 되면 한 달 안)', () => {
    expect(sinceDay('2026-10-20', now)).toBe('한 달 안');
    expect(sinceDay('2026-06-08', now)).toBe('5개월 전');
    expect(sinceDay('2026-07-20', now)).toBe('3개월 전');
    expect(sinceDay('2025-09-01', now)).toBe('1년 전');
    expect(sinceDay('1998-09-24', now)).toBe('28년 전');
    expect(sinceDay('없음', now)).toBe('');
  });
  it('최근 1년 내원 날 수는 지난 365일만 센다', () => {
    expect(daysWithinYear(['2025-11-01', '2025-11-08', '2026-06-08', '2026-12-01'], now)).toBe(2);
  });
});
