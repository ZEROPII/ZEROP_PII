import { ArrowLeft, BookOpen, Search, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { terminologyApi } from '../../api/terminologyApi';
import { useTerms } from '../../state/TermContext';
import { TERM_ATTR_LABEL, type TermAttribute, type TermSummary } from '../../types/terminology';
import { ErrorState, LoadingState } from '../common/StatusViews';
import { TermCardView } from './TermCardView';

const FILTERS: (TermAttribute | null)[] = [null, 'DX', 'MED', 'PROC'];

/** 검색 결과 한 줄 */
export function TermRow({ t, onOpen, active = false }: { t: TermSummary; onOpen(id: string): void; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(t.node_id)}
      className={`flex w-full flex-col items-start gap-0.5 rounded-control px-3 py-2 text-left ${active ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}
    >
      <span className="flex w-full items-center gap-1.5 text-[11px] font-semibold text-iris-text">
        {t.attribute_label}
        <span className="truncate font-normal text-ink-3">· {t.level_label}</span>
      </span>
      <span className="w-full truncate text-[13px] font-semibold text-ink">{t.canonical_label}</span>
      {t.plain_explanation && <span className="line-clamp-2 text-xs leading-snug text-ink-2">{t.plain_explanation}</span>}
    </button>
  );
}

/**
 * 의료 용어 옆 패널. 대화 화면을 가리지 않고 오른쪽에 붙어서, LLM 답을 보면서 용어를 찾을 수 있다.
 * 답변 속 밑줄 · 용어 칩 · 상단 '용어' 버튼 · ⌘K 명령 찾기에서 열린다.
 */
export function TermDrawer() {
  const { drawerOpen, closeDrawer, selected, openTerm, openSearch, query, status, auto, setAuto, view } = useTerms();
  const [q, setQ] = useState(query);
  const [attr, setAttr] = useState<TermAttribute | null>(null);
  const [results, setResults] = useState<TermSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setQ(query), [query]);
  useEffect(() => {
    if (drawerOpen && !selected) inputRef.current?.focus();
  }, [drawerOpen, selected]);
  useEffect(() => {
    if (selected) setHistory((h) => (h[h.length - 1] === selected ? h : [...h.slice(-19), selected]));
  }, [selected]);

  useEffect(() => {
    if (!drawerOpen) return;
    const term = q.trim();
    if (!term) {
      setResults(null);
      setError(null);
      return;
    }
    const ctl = new AbortController();
    const timer = window.setTimeout(() => {
      terminologyApi.search(term, { attribute: attr, limit: 30, view }, ctl.signal).then(
        (r) => {
          setResults(r);
          setError(null);
        },
        (e: unknown) => {
          if (e instanceof DOMException && e.name === 'AbortError') return;
          setError(e instanceof Error ? e.message : '검색하지 못했습니다.');
        },
      );
    }, 200);
    return () => {
      window.clearTimeout(timer);
      ctl.abort();
    };
  }, [q, attr, view, drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeDrawer();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawerOpen, closeDrawer]);

  if (!drawerOpen) return null;

  function back() {
    const prev = history[history.length - 2];
    setHistory((h) => h.slice(0, -1));
    if (prev) openTerm(prev);
    else openSearch();
  }

  const noExplain = status?.available && status.explained === 0;

  return (
    <aside
      aria-label="의료 용어"
      className="fixed inset-x-0 bottom-0 top-[var(--drawer-top,4rem)] z-40 flex flex-col border-l border-line bg-surface shadow-overlay sm:left-auto sm:w-[400px]"
    >
      <header className="flex items-center gap-2 border-b border-line px-4 py-3">
        {selected ? (
          <button type="button" onClick={back} className="btn-ghost h-8 w-8 px-0" aria-label="이전으로">
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </button>
        ) : (
          <BookOpen className="h-4 w-4 text-iris-text" aria-hidden />
        )}
        <h2 className="flex-1 text-[15px] font-bold">의료 용어</h2>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-ink-2" title="답변 속 의료 용어에 밑줄을 긋고, 답변 아래에 용어 칩을 띄웁니다">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="h-3.5 w-3.5 accent-[var(--zp-iris)]" />
          답변에 자동 표시
        </label>
        <button type="button" onClick={closeDrawer} className="btn-ghost h-8 w-8 px-0" aria-label="의료 용어 패널 닫기">
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>

      {!selected && (
        <div className="border-b border-line px-4 pb-3 pt-3">
          <div className="flex h-9 items-center gap-2 rounded-control border border-line-input bg-surface px-3">
            <Search className="h-4 w-4 text-ink-3" aria-hidden />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="용어, 일부 글자, 코드 (예: gingiv, amlodipine, K05)"
              className="flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
              aria-label="찾을 의료 용어"
            />
          </div>
          <div role="group" aria-label="분류" className="mt-2 flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f ?? 'all'}
                type="button"
                aria-pressed={attr === f}
                onClick={() => setAttr(f)}
                className={`h-7 rounded-[7px] px-2.5 text-xs font-semibold ${attr === f ? 'bg-iris-tint text-iris-text' : 'text-ink-3 hover:bg-surface-2'}`}
              >
                {f ? TERM_ATTR_LABEL[f] : '전체'}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {status && !status.available ? (
          <ErrorState message={`용어 DB를 열 수 없습니다. 서버 폴더에서 ${status.build_command} 를 실행하세요.`} />
        ) : selected ? (
          <TermCardView nodeId={selected} onOpen={openTerm} />
        ) : error ? (
          <ErrorState message={error} />
        ) : results ? (
          results.length ? (
            <ul className="-mx-1 flex flex-col gap-0.5">
              {results.map((t) => (
                <li key={t.node_id}>
                  <TermRow t={t} onOpen={openTerm} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-8 text-center text-[13px] text-ink-3">
              맞는 용어가 없습니다.
              {noExplain && /[가-힣]/.test(q) && <span className="mt-1 block text-xs">한국어 검색은 쉬운 설명이 채워진 뒤에 됩니다. 영문 이름 일부로 찾아 보세요.</span>}
            </p>
          )
        ) : q.trim() ? (
          <LoadingState compact />
        ) : (
          <div className="flex flex-col gap-3 text-[13px] leading-relaxed text-ink-2">
            <p>답변에 나온 진단 · 약 · 시술 이름을 찾아 쉬운 설명과 넓힌 이름을 봅니다. 답변 속 밑줄 친 용어를 눌러도 여기에 열립니다.</p>
            {status?.available && (
              <p className="rounded-cell bg-surface-2 px-3 py-2 text-xs text-ink-3">
                용어 {status.total?.toLocaleString()}개 · 쉬운 설명 {status.explained?.toLocaleString()}개 · 검토 완료 {status.reviewed?.toLocaleString()}개
                {status.mock ? ' (예시 데이터)' : ''}
                {noExplain && view === 'security' && (
                  <span className="mt-1 block">
                    쉬운 설명은 아직 없습니다. 서버 폴더에서 <code className="font-mono">{status.build_command}</code> 를 실행하면 채워집니다.
                  </span>
                )}
              </p>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
