import { CornerDownLeft } from 'lucide-react';
import type { PreflightRiskAssessment } from '../../types/domain';
import { MockBadge } from '../common/MockBadge';
import { StatusIcon } from '../common/StatusChip';

interface Props {
  assessment: PreflightRiskAssessment;
  onSuggestion(question: string): void;
}

/** 보내기 전 확인. 내용은 백엔드 사전 평가 결과 그대로이며, 보내면 백엔드가 다시 판정한다. 보내기를 막지는 않는다. */
export function PreflightWarning({ assessment, onSuggestion }: Props) {
  return (
    <div role="status" aria-live="polite" className="mb-2 rounded-control bg-caution-tint px-3 py-2.5 text-[13px] text-caution-text">
      <p className="flex gap-2">
        <StatusIcon tone="caution" className="mt-1 h-3 w-3 shrink-0" />
        <span>
          <strong className="font-bold">보내기 전에 확인하세요.</strong> {assessment.message}
          <MockBadge source={assessment.source} className="ml-1.5 align-middle" />
        </span>
      </p>
      {assessment.suggestions.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-5">
          <span className="text-xs">대신 물어볼 수 있는 질문</span>
          {assessment.suggestions.map((s) => (
            <button
              key={s.question}
              type="button"
              onClick={() => onSuggestion(s.question)}
              title={s.question}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-caution bg-surface px-2.5 text-xs font-semibold text-caution-text hover:bg-caution-tint"
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
