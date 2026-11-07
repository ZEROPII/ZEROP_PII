import { useMemo } from 'react';
import { splitByMentions } from '../../lib/termText';
import { useTerms } from '../../state/TermContext';
import type { TermMention } from '../../types/terminology';

/**
 * 글 속 의료 용어에 밑줄을 긋는다. 누르면 옆 패널에 용어 카드가 열리고, 마우스를 올리면 짧은 설명이 뜬다.
 * mentions가 없으면(자동 표시 끔 · 아직 못 받음) 글 그대로.
 */
export function TermText({ text, mentions }: { text: string; mentions: TermMention[] | undefined }) {
  const { openTerm, showHover, hideHover, summaries } = useTerms();
  const parts = useMemo(() => splitByMentions(text, mentions), [text, mentions]);
  if (parts.length === 1 && !parts[0].nodeId) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) => {
        if (!p.nodeId) return <span key={i}>{p.text}</span>;
        const id = p.nodeId;
        const s = summaries.get(id);
        return (
          <button
            key={i}
            type="button"
            className="medterm"
            aria-label={`${p.text}: 의료 용어 설명 보기${s ? ` (${s.attribute_label})` : ''}`}
            onClick={() => {
              hideHover();
              openTerm(id);
            }}
            onMouseEnter={(e) => showHover(id, e.currentTarget)}
            onMouseLeave={hideHover}
            onFocus={(e) => {
              if (e.currentTarget.matches(':focus-visible')) showHover(id, e.currentTarget);   // 키보드로 옮겼을 때만
            }}
            onBlur={hideHover}
          >
            {p.text}
          </button>
        );
      })}
    </>
  );
}
