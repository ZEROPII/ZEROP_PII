import { EyeOff, Maximize2 } from 'lucide-react';
import type { PrivacyTransformation } from '../../types/domain';

/**
 * 응답 속 공개 항목 하나를 백엔드가 준 보호 조치(transformation)대로 표시한다.
 * 프론트엔드는 문구를 보고 조치를 추측하지 않는다. transformation이 없으면 일반 텍스트다.
 */
export function PrivacyHighlight({ text, transformation }: { text: string; transformation: PrivacyTransformation | undefined }) {
  if (!transformation) return <>{text}</>;
  const label = transformation.attributeLabel;

  switch (transformation.action) {
    case 'allow':
      return (
        <span className="underline decoration-blue-300 decoration-dotted underline-offset-4" title={`${label}: 그대로 공개`}>
          {text}
        </span>
      );
    case 'generalize':
      return (
        <mark
          className="inline-flex items-baseline gap-0.5 rounded bg-blue-100 px-1 font-semibold text-blue-800 ring-1 ring-inset ring-blue-200"
          title={`${label} 일반화: ${transformation.levelDescription ?? ''}`}
        >
          {text}
          <Maximize2 className="h-2.5 w-2.5 self-center opacity-70" aria-hidden />
          <span className="sr-only"> (일반화된 값: {transformation.levelDescription})</span>
        </mark>
      );
    case 'suppress':
      return (
        <span
          className="inline-flex items-center gap-1 rounded bg-slate-200 px-1.5 py-px align-baseline text-[0.92em] font-medium text-slate-600"
          title={`${label}: 재식별 위험으로 비공개`}
        >
          <EyeOff className="h-3 w-3" aria-hidden />
          비공개
          <span className="sr-only"> ({label} 비공개 처리됨)</span>
        </span>
      );
  }
}
