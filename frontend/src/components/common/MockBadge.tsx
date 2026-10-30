import type { DataSource } from '../../types/domain';

/** Mock 데이터임을 분명히 알리는 표시. 실제 백엔드 데이터면 아무것도 그리지 않는다. */
export function MockBadge({ source, className = '' }: { source: DataSource | undefined; className?: string }) {
  if (source !== 'mock') return null;
  return (
    <span
      title="백엔드 없이 Mock Service가 만든 예시 데이터입니다. 실제 연구 결과가 아닙니다."
      className={`inline-flex items-center rounded border border-dashed border-amber-400 bg-amber-50 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-700 ${className}`}
    >
      Mock
    </span>
  );
}
