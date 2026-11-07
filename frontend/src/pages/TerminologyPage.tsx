import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { terminologyApi } from '../api/terminologyApi';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { TermCardView } from '../components/terminology/TermCardView';
import { TermRow } from '../components/terminology/TermDrawer';
import { useTerms } from '../state/TermContext';
import { TERM_ATTR_LABEL, type TermAttribute, type TermSummary } from '../types/terminology';

const PAGE = 50;
const REVIEW = [
  { v: null, label: '검토 상태 전체' },
  { v: '검토대기', label: '검토 전' },
  { v: '검토완료', label: '검토 완료' },
] as const;

/** 보안 담당자용 의료 용어 사전: 용어 DB 전체를 분류 · 검토 상태로 걸러 보고, 고른 용어의 카드를 옆에 띄운다. */
export function TerminologyPage() {
  const { status, view } = useTerms();
  const [q, setQ] = useState('');
  const [attr, setAttr] = useState<TermAttribute | null>(null);
  const [review, setReview] = useState<string | null>(null);
  const [items, setItems] = useState<TermSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const searching = q.trim().length > 0;

  useEffect(() => {
    setOffset(0);
    setSelected(null);          // 조건이 바뀌면 새 목록의 첫 용어를 보여 준다
  }, [q, attr, review]);

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      const req = searching
        ? terminologyApi.search(q.trim(), { attribute: attr, limit: 100, view }, ctl.signal).then((r) => {
            const rows = review ? r.filter((t) => t.review_status === review) : r;
            return { items: rows, total: rows.length };
          })
        : terminologyApi.list({ attribute: attr, reviewStatus: review, limit: PAGE, offset, view }, ctl.signal);
      req.then(
        (res) => {
          setItems((prev) => (offset > 0 && !searching ? [...prev, ...res.items] : res.items));
          setTotal(res.total);
          setError(null);
          setLoading(false);
        },
        (e: unknown) => {
          if (e instanceof DOMException && e.name === 'AbortError') return;
          setError(e instanceof Error ? e.message : '용어 목록을 불러오지 못했습니다.');
          setLoading(false);
        },
      );
    }, searching ? 200 : 0);
    return () => {
      window.clearTimeout(timer);
      ctl.abort();
    };
  }, [q, attr, review, offset, view, searching]);

  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].node_id);
  }, [items, selected]);

  return (
    <div className="scroll-thin flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <section className="grid gap-4 px-4 pb-4 pt-5 md:px-6 xl:grid-cols-[1fr_auto] xl:items-end">
        <div>
          <p className="max-w-[34em] text-[21px] font-bold leading-[1.42] tracking-[-0.025em] md:text-2xl">
            답변에 나오는 진단 · 약 · 시술 이름을 쉬운 말과 넓힌 이름으로 확인합니다.
          </p>
          <p className="mt-1.5 max-w-[48em] text-[13px] leading-relaxed text-ink-2">
            방어 규칙이 값을 넓힐 때 쓰는 단계(일반화 체인)와 기준 집단에서 그 값을 가진 환자 수를 함께 보여 줍니다. 설명은 용어 DB에 저장된 것만 보여 주며, 화면에서 LLM을 부르지 않습니다.
          </p>
        </div>
        {status?.available && (
          <dl className="flex gap-7">
            {[
              [status.total ?? 0, '용어'],
              [status.explained ?? 0, '쉬운 설명'],
              [status.reviewed ?? 0, '검토 완료'],
            ].map(([v, l]) => (
              <div key={String(l)} className="min-w-[72px]">
                <dd className="num text-3xl font-extrabold leading-tight tracking-[-0.03em]">{Number(v).toLocaleString()}</dd>
                <dt className="text-xs text-ink-2">{l}</dt>
              </div>
            ))}
          </dl>
        )}
      </section>

      {status?.available && status.explained === 0 && (
        <p className="mx-4 mb-3 rounded-control bg-caution-tint px-4 py-2.5 text-[13px] leading-relaxed text-caution-text md:mx-6">
          쉬운 설명이 아직 없습니다{status.generated ? ' (용어 DB 파일이 없어 노드 표로 만든 목록을 보여 주는 중)' : ''}. 서버 폴더에서{' '}
          <code className="font-mono">{status.build_command}</code> 를 한 번 실행하면 채워집니다. LLM에는 용어 이름과 코드만 보냅니다.
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 px-3 pb-3 md:px-6 md:pb-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="panel flex h-[70vh] min-h-0 flex-col lg:h-auto" aria-label="용어 목록">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
            <div className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-control border border-line-input bg-surface px-3">
              <Search className="h-4 w-4 text-ink-3" aria-hidden />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="용어 · 일부 글자 · 코드로 찾기"
                className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-ink-3"
                aria-label="용어 찾기"
              />
            </div>
            <div role="group" aria-label="분류" className="flex gap-1">
              {([null, 'DX', 'MED', 'PROC'] as (TermAttribute | null)[]).map((f) => (
                <button
                  key={f ?? 'all'}
                  type="button"
                  aria-pressed={attr === f}
                  onClick={() => setAttr(f)}
                  className={`h-8 rounded-[7px] px-2.5 text-xs font-semibold ${attr === f ? 'bg-iris-tint text-iris-text' : 'text-ink-3 hover:bg-surface-2'}`}
                >
                  {f ? `${TERM_ATTR_LABEL[f]} ${status?.by_attribute?.[f] ?? ''}` : '전체'}
                </button>
              ))}
            </div>
            <select
              value={review ?? ''}
              onChange={(e) => setReview(e.target.value || null)}
              className="h-8 rounded-[7px] border border-line bg-surface px-2 text-xs text-ink-2"
              aria-label="검토 상태"
            >
              {REVIEW.map((r) => (
                <option key={r.label} value={r.v ?? ''}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-2">
            {error ? (
              <ErrorState message={error} />
            ) : loading && !items.length ? (
              <LoadingState />
            ) : items.length === 0 ? (
              <p className="py-10 text-center text-[13px] text-ink-3">맞는 용어가 없습니다.</p>
            ) : (
              <>
                <p className="px-3 pb-1 text-xs text-ink-3">
                  {searching ? `찾은 용어 ${total}개` : `${total.toLocaleString()}개 중 ${items.length.toLocaleString()}개`}
                </p>
                <ul className="flex flex-col gap-0.5">
                  {items.map((t) => (
                    <li key={t.node_id}>
                      <TermRow t={t} onOpen={setSelected} active={t.node_id === selected} />
                    </li>
                  ))}
                </ul>
                {!searching && items.length < total && (
                  <div className="p-2">
                    <button type="button" className="btn-secondary w-full" disabled={loading} onClick={() => setOffset(items.length)}>
                      더 보기
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
        <section className="panel scroll-thin px-5 py-5 lg:min-h-0 lg:overflow-y-auto" aria-label="고른 용어">
          {selected ? <TermCardView nodeId={selected} onOpen={setSelected} /> : <p className="text-[13px] text-ink-3">왼쪽에서 용어를 고르세요.</p>}
        </section>
      </div>
    </div>
  );
}
