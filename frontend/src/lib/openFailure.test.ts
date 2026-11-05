// 진료 지원 AI 열기 실패 안내 (ADR-0031)
import { describe, expect, it } from 'vitest';
import { openFailure } from './openFailure';

describe('열기 실패 안내', () => {
  it('앞단이 끊은 502 · 524는 끊겼다고 알리고 다시 시도를 권한다', () => {
    const f = openFailure(502, '진료 지원 AI를 열지 못했습니다 (HTTP 502).', 58.4);
    expect(f.detail).toBe('응답을 기다리다 연결이 끊겼습니다 (HTTP 502, 58초 지나서).');
    expect(f.hint).toContain('다시 시도할 때 바로 열립니다');
    expect(f.retry).toBe(true);
    expect(openFailure(524, '진료 지원 AI를 열지 못했습니다 (HTTP 524).', null).detail).toBe('응답을 기다리다 연결이 끊겼습니다 (HTTP 524).');
  });

  it('서버가 까닭을 적어 보냈으면 그대로 보인다', () => {
    const f = openFailure(502, '대상 AI 호출에 실패했습니다 (LLMHTTPError). 대화 상태는 바뀌지 않았습니다.', 3);
    expect(f.detail).toContain('LLMHTTPError');
    expect(f.retry).toBe(true);
    expect(openFailure(409, '대화가 바뀌었습니다.', 1).detail).toBe('대화가 바뀌었습니다.');
  });

  it('연결 못 함 · 열 수 없는 진료 목적 · 로그인 끝', () => {
    expect(openFailure(0, '서버에 연결할 수 없습니다.', 0).hint).toContain('서버가 켜져 있는지');
    expect(openFailure(404, '이 환자는 고른 진료 목적으로 진료 지원 AI를 열 수 없습니다.', 1).retry).toBe(false);
    expect(openFailure(401, 'x', 1).retry).toBe(false);
  });
});
