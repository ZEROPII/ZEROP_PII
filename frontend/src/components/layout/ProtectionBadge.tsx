import type { Async } from '../../state/workspaceReducer';
import type { ProtectionPolicy } from '../../types/domain';
import { StatusChip } from '../common/StatusChip';

/** 지금 적용 중인 보호 정책. 값은 백엔드(getProtectionPolicy)에서 받는다. */
export function ProtectionBadge({ policy }: { policy: Async<ProtectionPolicy> }) {
  if (policy.status !== 'success' || !policy.data) {
    return <StatusChip tone="plain">{policy.status === 'error' ? '보호 정책을 확인하지 못했습니다' : '보호 정책 확인 중'}</StatusChip>;
  }
  const p = policy.data;
  const off = p.arm === 'C0';
  return (
    <StatusChip
      tone={off ? 'danger' : 'safe'}
      title={`원래 값으로 후보가 ${p.minK}명 이하면 넓혀서, ${p.suppressK}명 이하면 가리고 답합니다.${p.source === 'mock' ? ' (예시 정책)' : ''}`}
    >
      {off ? '보호 꺼짐 (비교용)' : `보호 켜짐: ${p.stateModeLabel}, 기준 ${p.minK}명`}
    </StatusChip>
  );
}
