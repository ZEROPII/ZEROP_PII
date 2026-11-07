import type { DataSource } from '../../types/domain';

/** Mock 데이터임을 분명히 알리는 표시. 실제 백엔드 데이터면 아무것도 그리지 않는다. */
export function MockBadge({ source, className = '' }: { source: DataSource | undefined; className?: string }) {
  if (source !== 'mock') return null;
  return (
    <span
      title="백엔드 없이 브라우저 안 Mock Service가 만든 예시 데이터입니다. 실제 연구 결과가 아닙니다."
      className={`inline-flex items-center rounded-[5px] border border-dashed border-caution bg-caution-tint px-1.5 py-px text-[11px] font-semibold text-caution-text ${className}`}
    >
      예시 데이터
    </span>
  );
}
