import { AlertTriangle, CornerDownLeft } from 'lucide-react';
import type { PreflightRiskAssessment } from '../../types/domain';
import { MockBadge } from '../common/MockBadge';

interface Props {
  assessment: PreflightRiskAssessment;
  onSuggestion(question: string): void;
}

/** 전송 전 경고. 내용은 백엔드 사전 평가 결과 그대로이며, 전송 시 백엔드가 다시 검증한다. */
export function PreflightWarning({ assessment, onSuggestion }: Props) {
  return (
    <div role="status" aria-live="polite" className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
      <p className="flex gap-2">
        <AlertTriangle className="mt-px h-4 w-4 shrink-0 text-amber-600" aria-hidden />
        <span>
          <strong className="font-semibold">보내기 전에 확인하세요.</strong> {assessment.message}
          <MockBadge source={assessment.source} className="ml-1.5 align-middle" />
        </span>
      </p>
      {assessment.suggestions.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-6">
          <span className="text-[11px] text-amber-700">대신 이렇게 물어보세요:</span>
          {assessment.suggestions.map((s) => (
            <button
              key={s.label}
              type="button"
              onClick={() => onSuggestion(s.question)}
              title={s.question}
              className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-500"
            >
              <CornerDownLeft className="h-3 w-3" aria-hidden />
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
