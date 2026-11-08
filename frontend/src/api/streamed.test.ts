import { describe, expect, it } from 'vitest';
import { streamedFailure } from './types';

describe('streamedFailure: 오래 걸려 200으로 먼저 연 응답의 실패 (ADR-0044)', () => {
  it('본문의 _status가 400 이상이면 실패로 본다', () => {
    expect(streamedFailure({ detail: '질문을 멈췄습니다.', _status: 409, _state: 'stopped' })).toEqual({ status: 409, detail: '질문을 멈췄습니다.', flag: 'stopped' });
    expect(streamedFailure({ detail: 1, _status: 502, _state: null })).toEqual({ status: 502, detail: null, flag: undefined });
  });
  it('보통 응답은 그대로 둔다', () => {
    expect(streamedFailure({ status: 'ok', workspaceId: 'w1' })).toBeNull();
    expect(streamedFailure([1, 2])).toBeNull();
    expect(streamedFailure(null)).toBeNull();
  });
});
