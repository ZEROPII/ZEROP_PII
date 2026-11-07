import { BookOpen } from 'lucide-react';
import { useTerms } from '../../state/TermContext';
import type { TermMention } from '../../types/terminology';

/** 답변 아래에 자동으로 뜨는 '이 답변의 의료 용어' 칩. 누르면 옆 패널에 카드가 열린다. */
export function AnswerTerms({ mentions, max = 6, label = '이 답변의 의료 용어' }: { mentions: (TermMention[] | undefined)[]; max?: number; label?: string }) {
  const { summaries, openTerm } = useTerms();
  const ids: string[] = [];
  for (const m of mentions.flat()) if (m && !ids.includes(m.node_id) && summaries.has(m.node_id)) ids.push(m.node_id);
  if (!ids.length) return null;
  const shown = ids.slice(0, max);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label={label}>
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-ink-3">
        <BookOpen className="h-3.5 w-3.5" aria-hidden />
        {label}
      </span>
      {shown.map((id) => {
        const s = summaries.get(id)!;
        return (
          <button
            key={id}
            type="button"
            onClick={() => openTerm(id)}
            className="chip max-w-[220px] border border-line bg-surface text-ink-2 hover:border-iris hover:text-ink"
            title={s.plain_explanation ?? s.canonical_label}
          >
            <span className="text-iris-text">{s.attribute_label}</span>
            <span className="truncate font-medium">{s.canonical_label}</span>
          </button>
        );
      })}
      {ids.length > shown.length && <span className="text-[11px] text-ink-3">외 {ids.length - shown.length}개</span>}
    </div>
  );
}
