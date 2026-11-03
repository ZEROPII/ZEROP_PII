import { useTerms } from '../../state/TermContext';

/** 밑줄 친 용어에 마우스를 올리거나 키보드로 옮기면 뜨는 짧은 설명. 누르면 옆 패널에 자세한 카드. */
export function TermHoverCard() {
  const { hover, summaries } = useTerms();
  if (!hover) return null;
  const s = summaries.get(hover.nodeId);
  if (!s) return null;
  const width = 300;
  const left = Math.max(12, Math.min(hover.rect.left + hover.rect.width / 2 - width / 2, window.innerWidth - width - 12));
  const below = hover.rect.top < 180;
  const style = below ? { left, top: hover.rect.bottom + 8, width } : { left, bottom: window.innerHeight - hover.rect.top + 8, width };
  return (
    <div role="tooltip" className="pointer-events-none fixed z-[60] rounded-control border border-line bg-surface px-3.5 py-3 text-left shadow-overlay" style={style}>
      <p className="flex items-center gap-1.5 text-[11px] font-semibold text-iris-text">
        {s.attribute_label}
        <span className="text-ink-3">· {s.level_label}</span>
      </p>
      <p className="mt-0.5 text-[13px] font-semibold leading-snug text-ink">{s.canonical_label}</p>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
        {s.plain_explanation ?? '쉬운 설명이 아직 없습니다. 눌러서 분류와 상위 이름을 보세요.'}
      </p>
      <p className="mt-2 text-[11px] text-ink-3">누르면 옆 패널에서 자세히 봅니다</p>
    </div>
  );
}
