import type { PrivacyTransformation } from '../../types/domain';

/**
 * 답변 속 공개 항목 하나를 백엔드가 준 보호 조치대로 표시한다. 문구를 보고 조치를 추측하지 않는다.
 * 허용은 점선 밑줄, 일반화는 주의색 바탕, 가림은 사선 무늬 막대로 보인다.
 */
export function PrivacyHighlight({ text, transformation }: { text: string; transformation: PrivacyTransformation | undefined }) {
  if (!transformation) return <>{text}</>;
  const label = transformation.attributeLabel;

  switch (transformation.action) {
    case 'allow':
      return (
        <span className="underline decoration-ink-3 decoration-dotted underline-offset-4" title={`${label}: 그대로 답함`}>
          {text}
        </span>
      );
    case 'generalize':
      return (
        <mark className="rounded-[5px] bg-caution-tint px-1 font-semibold text-caution-text" title={`${label}: ${transformation.levelDescription ?? '넓은 범주로 바꿈'}`}>
          {text}
          <span className="sr-only"> (넓은 범주로 바꾼 값)</span>
        </mark>
      );
    case 'suppress':
      return (
        <span className="inline-flex items-center gap-1.5 align-baseline text-[0.92em] font-semibold text-danger-text" title={`${label}: ${transformation.levelDescription ?? '가림'}`}>
          <span className="redact" style={{ minWidth: 44 }} aria-hidden />
          가림
          <span className="sr-only"> ({label} 가림 처리됨)</span>
        </span>
      );
  }
}
