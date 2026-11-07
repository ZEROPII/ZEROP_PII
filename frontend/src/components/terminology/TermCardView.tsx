import { ChevronRight, Info } from 'lucide-react';
import { useEffect, useState } from 'react';
import { terminologyApi } from '../../api/terminologyApi';
import { useTerms } from '../../state/TermContext';
import type { TermCard } from '../../types/terminology';
import { StatusChip } from '../common/StatusChip';
import { ErrorState, LoadingState } from '../common/StatusViews';

/** 용어 카드: 쉬운 설명, 분류와 코드, 넓힌 이름(일반화 체인), 같은 뜻 표현. 보안 담당자 보기에는 기준 집단 환자 수. */
export function TermCardView({ nodeId, onOpen, compact = false }: { nodeId: string; onOpen(nodeId: string): void; compact?: boolean }) {
  const { view } = useTerms();
  const [card, setCard] = useState<TermCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    setCard(null);
    setError(null);
    terminologyApi.card(nodeId, view, ctl.signal).then(setCard, (e: unknown) => {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(e instanceof Error ? e.message : '용어를 불러오지 못했습니다.');
    });
    return () => ctl.abort();
  }, [nodeId, view]);

  if (error) return <ErrorState message={error} />;
  if (!card) return <LoadingState label="용어 카드를 불러오는 중" />;

  const chain = card.generalization_chain.filter((c) => c.node_id !== card.node_id);
  const reviewed = card.review_status === '검토완료';
  return (
    <article className="flex flex-col gap-4" aria-label={`${card.canonical_label} 용어 카드`}>
      <header>
        <p className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-iris-text">
          {card.attribute_label}
          <span className="font-normal text-ink-3">· {card.level_label}</span>
          {card.is_sensitive && <StatusChip tone="caution">민감 항목</StatusChip>}
        </p>
        <h3 className="mt-1 text-[17px] font-bold leading-snug tracking-[-0.01em] text-ink">{card.canonical_label}</h3>
        <p className="mt-1 font-mono text-[11px] text-ink-3">
          {card.source}
          {card.standard_code ? ` ${card.standard_code}` : ''}
        </p>
      </header>

      <section>
        <h4 className="text-xs font-bold text-ink-2">쉬운 설명</h4>
        {card.plain_explanation ? (
          <>
            <p className="mt-1 text-[14px] leading-relaxed text-ink">{card.plain_explanation}</p>
            <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
              <StatusChip tone={reviewed ? 'safe' : 'plain'}>{reviewed ? '검토 완료' : '검토 전 설명'}</StatusChip>
              {card.llm_model ? `설명 생성: ${card.llm_model}` : null}
              {reviewed && card.reviewer ? ` · 검토: ${card.reviewer}` : null}
            </p>
          </>
        ) : (
          <p className="mt-1 rounded-cell bg-surface-2 px-3 py-2 text-[13px] leading-relaxed text-ink-2">
            쉬운 설명이 아직 없습니다. 아래 분류와 넓힌 이름으로 어떤 항목인지 볼 수 있습니다.
            {view === 'security' && (
              <span className="mt-1 block text-xs text-ink-3">
                설명은 용어 DB를 만들 때 채웁니다: <code className="font-mono">python scripts/build_terminology_db.py</code> (LLM에는 용어 이름과 코드만 보냄)
              </span>
            )}
          </p>
        )}
      </section>

      {view === 'security' && card.k_patients != null && (
        <section className="rounded-control border border-line px-3.5 py-3">
          <h4 className="text-xs font-bold text-ink-2">기준 집단에서 이 값을 가진 환자</h4>
          <p className="mt-1 text-[14px] text-ink">
            <b className="num text-xl font-extrabold">{card.k_patients.toLocaleString()}</b>명
            {card.total_patients ? <span className="text-ink-3"> / {card.total_patients.toLocaleString()}명</span> : null}
          </p>
          {!compact && (
            <p className="mt-1 flex items-start gap-1 text-xs leading-relaxed text-ink-3">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              적을수록 이 값이 다른 단서와 겹쳐 환자를 좁히기 쉽습니다. 방어 규칙은 아래 넓힌 이름 쪽으로 바꿔 답합니다.
            </p>
          )}
        </section>
      )}

      {chain.length > 0 && (
        <section>
          <h4 className="text-xs font-bold text-ink-2">넓힌 이름 (일반화 단계)</h4>
          <ol className="mt-1.5 flex flex-col gap-1">
            {chain.map((c, i) => (
              <li key={c.node_id}>
                <button
                  type="button"
                  onClick={() => onOpen(c.node_id)}
                  className="group flex w-full items-start gap-2 rounded-cell px-2 py-1.5 text-left hover:bg-surface-2"
                >
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface-2 text-[10px] font-bold text-ink-2">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium leading-snug text-ink">{c.label}</span>
                    <span className="block text-[11px] text-ink-3">{c.level_label}</span>
                  </span>
                  <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-ink-3 opacity-0 group-hover:opacity-100" aria-hidden />
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {card.aliases.length > 0 && (
        <section>
          <h4 className="text-xs font-bold text-ink-2">같은 항목으로 알아보는 표현</h4>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {card.aliases.map((a) => (
              <span key={a} className="chip max-w-full bg-surface-2 font-medium text-ink-2" title={a}>
                <span className="truncate">{a}</span>
              </span>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}
