import { describe, expect, it } from 'vitest';
import { ApiError, isNoConversation } from '../api/types';
import { initialWorkspaceState, workspaceReducer } from './workspaceReducer';

describe('운영 모드: 아직 연 환자가 없음', () => {
  it('409와 no-conversation 머리글일 때만 빈 상태로 본다', () => {
    expect(isNoConversation(new ApiError('x', 409, 'no-conversation'))).toBe(true);
    expect(isNoConversation(new ApiError('x', 409))).toBe(false);
    expect(isNoConversation(new ApiError('x', 404, 'no-conversation'))).toBe(false);
    expect(isNoConversation(new Error('x'))).toBe(false);
  });

  it('workspace/none은 화면 상태를 비우고, 환자를 연 뒤 첫 응답이 오면 풀린다', () => {
    const none = workspaceReducer({ ...initialWorkspaceState, selectedCaseId: 'case-1' }, { type: 'workspace/none' });
    expect(none.noConversation).toBe(true);
    expect(none.selectedCaseId).toBeNull();
    const back = workspaceReducer(none, { type: 'resource/success', key: 'environment', data: { roleLabel: '의료진', locationLabel: 'EMR' } });
    expect(back.noConversation).toBe(false);
  });
});
