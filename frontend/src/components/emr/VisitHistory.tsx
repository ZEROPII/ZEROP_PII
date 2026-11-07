import { ChevronRight } from 'lucide-react';
import { useId, useMemo, useState } from 'react';
import { daysWithinYear } from '../../lib/time';
import { highlightsOf, yearRows, type Highlight, type YearRow } from '../../lib/visits';
import type { EmrChart } from '../../types/domain';

type Visit = EmrChart['visits'][number];
type Kind = Visit['items'][number]['kind'];

const KIND_KO: Record<Kind, string> = { problems: '진단', medications: '처방', procedures: '시술', carePlans: '관리' };
const NEW_KO: Record<Kind, string> = { problems: '새 진단', procedures: '첫 시술', medications: '첫 처방', carePlans: '새 관리 계획' };
/** 바로 보이는 해 수. 그보다 오래된 해가 둘 이상이면 '이전 기록' 한 줄로 접는다 */
const RECENT_YEARS = 5;
/** 펼친 해에서 먼저 보이는 내원 수 · 내원 하나에서 먼저 보이는 항목 수 */
const FIRST_VISITS = 5;
const FIRST_ITEMS = 4;
/** 해 줄의 칸: 펼침 표시 · 해 · 내원 수 · 달력 띠 · 그해 눈여겨볼 일 (좁은 화면에서는 눈여겨볼 일이 둘째 줄로) */
const ROW_GRID = 'grid grid-cols-[14px_38px_34px_minmax(0,1fr)] gap-x-2.5 sm:grid-cols-[14px_38px_34px_auto_minmax(0,1fr)]';
/** 펼친 내용의 왼쪽 여백: 해 칸과 줄을 맞춘다 (px-3.5 + 14px + gap-x-2.5) */
const INDENT = 'pl-[38px]';

/** 달마다 한 칸: 내원한 달은 회색, 새 진단 · 첫 시술이 있던 달은 보라색 */
function MonthStrip({ row }: { row: YearRow }) {
  return (
    <span aria-hidden className="flex gap-[2px]">
      {row.months.map((n, i) => (
        <span
          key={i}
          title={n ? `${i + 1}월 ${n}회${row.fresh[i] ? ' · 새 진단 · 첫 시술' : ''}` : undefined}
          className={`h-3.5 w-2.5 rounded-[2px] ${row.fresh[i] ? 'bg-iris' : n ? 'bg-line-input' : 'bg-line'}`}
        />
      ))}
    </span>
  );
}

interface HighlightGroup {
  type: Highlight['type'];
  kind: Kind;
  labels: string[];
}

/** 같은 종류끼리 묶는다: '새 진단 A, B · 첫 시술 C' */
function grouped(list: Highlight[]): HighlightGroup[] {
  const out: HighlightGroup[] = [];
  for (const h of list) {
    const g = out[out.length - 1];
    if (g && g.type === h.type && g.kind === h.kind) g.labels.push(h.label);
    else out.push({ type: h.type, kind: h.kind, labels: [h.label] });
  }
  return out;
}

function prefix(g: HighlightGroup): string {
  if (g.type === 'new') return NEW_KO[g.kind];
  if (g.type === 'main') return g.kind === 'problems' ? '주로' : `주로 ${KIND_KO[g.kind]}`;
  return KIND_KO[g.kind];
}

/** 그해 눈여겨볼 일: 이름은 세 개까지 (나머지는 '외 n건'), 같은 종류는 한 묶음. 새 진단 · 첫 시술만 색을 쓴다 */
function Highlights({ list, className }: { list: Highlight[]; className: string }) {
  if (!list.length) return null;
  const shown = grouped(list.slice(0, 3));
  const rest = list.length - 3;
  return (
    <span className={`min-w-0 truncate text-[12.5px] ${className}`} title={grouped(list).map((g) => `${prefix(g)} ${g.labels.join(', ')}`).join(' · ')}>
      {shown.map((g, i) => (
        <span key={`${g.type}:${g.kind}:${i}`}>
          {i > 0 && <span className="text-ink-3"> · </span>}
          <span className={g.type === 'new' ? 'font-semibold text-iris-text' : 'text-ink-3'}>{prefix(g)} </span>
          <span className="text-ink">{g.labels.join(', ')}</span>
        </span>
      ))}
      {rest > 0 && <span className="text-ink-3"> 외 {rest}건</span>}
    </span>
  );
}

/** 내원 하나: 날짜(월-일)와 그날 기록된 것. 이 환자 기록에 처음 나온 것에는 '처음'이 붙는다 */
function VisitRow({ v }: { v: Visit }) {
  const [all, setAll] = useState(false);
  const items = all ? v.items : v.items.slice(0, FIRST_ITEMS);
  const hidden = v.items.length - items.length;
  const more = v.more ?? 0;
  return (
    <li className="grid grid-cols-[42px_minmax(0,1fr)] gap-2 py-1">
      <span className="num pt-px text-xs font-semibold text-ink-2">{v.date.slice(5)}</span>
      {v.items.length === 0 ? (
        <span className="text-[12px] text-ink-3">기록된 진단 · 처방 없음</span>
      ) : (
        <ul className="min-w-0 space-y-0.5">
          {items.map((x) => (
            <li key={`${x.kind}:${x.label}`} className="flex min-w-0 items-baseline gap-1.5 text-[12.5px]">
              <span className="w-[26px] shrink-0 text-[11px] font-semibold text-ink-3">{KIND_KO[x.kind]}</span>
              <span className="min-w-0 truncate text-ink" title={x.label}>
                {x.label}
              </span>
              {x.first && (
                <span className="shrink-0 rounded-[3px] bg-iris-tint px-1 text-[10.5px] font-semibold text-iris-text" title="이 환자 기록에 처음 나온 것">
                  처음
                </span>
              )}
            </li>
          ))}
          {hidden > 0 ? (
            <li>
              <button type="button" className="text-[11.5px] font-semibold text-iris-text hover:underline" onClick={() => setAll(true)}>
                외 {hidden + more}건 보기
              </button>
            </li>
          ) : (
            more > 0 && <li className="text-[11.5px] text-ink-3">그 밖에 {more}건</li>
          )}
        </ul>
      )}
    </li>
  );
}

/** 해 한 줄: 누르면 그해 내원이 펼쳐진다 */
function YearSection({ row, open, onToggle }: { row: YearRow; open: boolean; onToggle: () => void }) {
  const id = useId();
  const [allVisits, setAllVisits] = useState(false);
  const hl = useMemo(() => highlightsOf(row.visits), [row.visits]);
  const visits = allVisits ? row.visits : row.visits.slice(0, FIRST_VISITS);
  const dateOnly = row.days.length - row.visits.length;
  const months = row.months.map((n, i) => (n ? `${i + 1}월 ${n}회` : '')).filter(Boolean).join(', ');
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={onToggle}
        className={`${ROW_GRID} w-full items-center gap-y-0.5 px-3.5 py-2 text-left hover:bg-surface-2`}
      >
        <ChevronRight className={`h-3.5 w-3.5 text-ink-3 transition-transform motion-reduce:transition-none ${open ? 'rotate-90' : ''}`} aria-hidden />
        <span className="num text-[13px] font-bold text-ink">{row.year}</span>
        <span className="num text-xs text-ink-2">{row.days.length}회</span>
        <MonthStrip row={row} />
        <span className="sr-only">
          {row.year}년 내원 {row.days.length}회: {months}.
        </span>
        <Highlights list={hl} className="col-span-3 col-start-2 sm:col-span-1 sm:col-start-auto" />
      </button>
      {open && (
        <div id={id} className={`${INDENT} pb-2 pr-3.5`}>
          {visits.length > 0 && (
            <ol className="divide-y divide-line">
              {visits.map((v) => (
                <VisitRow key={v.date} v={v} />
              ))}
            </ol>
          )}
          {row.visits.length > visits.length && (
            <button type="button" className="mt-1 text-[11.5px] font-semibold text-iris-text hover:underline" onClick={() => setAllVisits(true)}>
              이 해 내원 {row.visits.length}번 모두 보기
            </button>
          )}
          {dateOnly > 0 && (
            <p className="mt-1 text-[11.5px] text-ink-3">
              {row.visits.length ? `나머지 ${dateOnly}번은` : '이 해 내원은'} 오래되어 날짜만 있습니다:{' '}
              <span className="num">
                {row.days
                  .filter((d) => !row.visits.some((v) => v.date === d))
                  .slice(0, 12)
                  .map((d) => d.slice(5))
                  .join(', ')}
                {dateOnly > 12 ? ` 외 ${dateOnly - 12}번` : ''}
              </span>
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/** 해 사이에 내원이 없던 해: '2021~2023 내원 없음' */
function Gap({ from, to }: { from: number; to: number }) {
  return (
    <li className={`${INDENT} py-1 pr-3.5 text-[11.5px] text-ink-3`}>
      <span className="num">{from === to ? `${from}년` : `${from}~${to}`}</span> 내원 없음
    </li>
  );
}

function Years({ rows, open, toggle }: { rows: YearRow[]; open: Set<number>; toggle: (y: number) => void }) {
  return (
    <>
      {rows.map((r, i) => {
        const next = rows[i + 1];
        return (
          <YearRowWithGap key={r.year} row={r} gapTo={next && next.year < r.year - 1 ? next.year + 1 : null} open={open.has(r.year)} onToggle={() => toggle(r.year)} />
        );
      })}
    </>
  );
}

function YearRowWithGap({ row, gapTo, open, onToggle }: { row: YearRow; gapTo: number | null; open: boolean; onToggle: () => void }) {
  return (
    <>
      <YearSection row={row} open={open} onToggle={onToggle} />
      {gapTo !== null && <Gap from={gapTo} to={row.year - 1} />}
    </>
  );
}

/** 처음 펼쳐 둘 해: 가장 최근 해. 그해 내원이 3번보다 적으면 그 앞 해도 */
function firstOpen(rows: YearRow[]): Set<number> {
  const open = new Set<number>();
  if (rows[0]) open.add(rows[0].year);
  if (rows[0] && rows[1] && rows[0].visits.length < 3) open.add(rows[1].year);
  return open;
}

/**
 * 내원 이력 (ADR-0038): 해마다 한 줄 (내원 수 · 달력 띠 · 그해 새 진단 · 첫 시술), 누르면 그해 내원이 날짜마다 펼쳐진다.
 * 마지막 내원 · 전체 내원 수는 차트 머리에 있으니 위에는 지난 1년 내원 수만 둔다. 최근 5년이 넘는 해는 '이전 기록'으로 접는다.
 */
export function VisitHistory({ chart, className = '' }: { chart: EmrChart; className?: string }) {
  const dates = useMemo(() => chart.visitDates ?? chart.visits.map((v) => v.date).sort(), [chart.visitDates, chart.visits]);
  const rows = useMemo(() => yearRows(dates, chart.visits), [dates, chart.visits]);
  const [open, setOpen] = useState<Set<number>>(() => firstOpen(rows));
  const [olderOpen, setOlderOpen] = useState(false);
  const olderId = useId();
  // 접을 해가 하나뿐이면 접지 않고 그대로 보인다
  const cut = rows.length > RECENT_YEARS + 1 ? RECENT_YEARS : rows.length;
  const recent = rows.slice(0, cut);
  const older = rows.slice(cut);
  const year = daysWithinYear(dates);
  const toggle = (y: number) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(y)) n.delete(y);
      else n.add(y);
      return n;
    });
  const lastRecent = recent[recent.length - 1];
  const olderGap = older[0] && lastRecent && older[0].year < lastRecent.year - 1 ? older[0].year + 1 : null;

  return (
    <section className={`rounded-control border border-line bg-surface ${className}`} aria-label="내원 이력">
      <h3 className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">
        내원 이력
        {rows.length > 0 && (
          <span className="ml-auto text-xs font-normal text-ink-2">
            {year ? (
              <>
                지난 1년 <span className="num font-semibold text-ink">{year}회</span>
              </>
            ) : (
              '지난 1년 내원 없음'
            )}
          </span>
        )}
      </h3>
      {rows.length === 0 ? (
        <p className="px-3.5 py-3 text-[13px] text-ink-3">내원 기록이 없습니다.</p>
      ) : (
        <>
          <div aria-hidden className={`${ROW_GRID} px-3.5 pt-2 text-[10px] text-ink-3`}>
            <span className="col-start-4 flex w-[142px] justify-between">
              <span>1월</span>
              <span>12월</span>
            </span>
          </div>
          <ol className="pb-1">
            <Years rows={recent} open={open} toggle={toggle} />
            {older.length > 0 && (
              <>
                {olderGap !== null && <Gap from={olderGap} to={lastRecent.year - 1} />}
                <li>
                  <button
                    type="button"
                    aria-expanded={olderOpen}
                    aria-controls={olderOpen ? olderId : undefined}
                    onClick={() => setOlderOpen((o) => !o)}
                    className="grid w-full grid-cols-[14px_minmax(0,1fr)] items-center gap-x-2.5 px-3.5 py-2 text-left text-[12.5px] text-ink-2 hover:bg-surface-2"
                  >
                    <ChevronRight className={`h-3.5 w-3.5 text-ink-3 transition-transform motion-reduce:transition-none ${olderOpen ? 'rotate-90' : ''}`} aria-hidden />
                    <span>
                      이전 기록{' '}
                      <span className="num">
                        {older[older.length - 1].year}~{older[0].year}
                      </span>{' '}
                      · <span className="num">{older.reduce((n, r) => n + r.days.length, 0)}회</span>
                    </span>
                  </button>
                  {olderOpen && (
                    <ol id={olderId}>
                      <Years rows={older} open={open} toggle={toggle} />
                    </ol>
                  )}
                </li>
              </>
            )}
          </ol>
          <p aria-hidden className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-3.5 py-2 text-[11px] text-ink-3">
            <span className="inline-flex items-center gap-1">
              <span className="h-2.5 w-2 rounded-[2px] bg-line-input" />
              내원한 달
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2.5 w-2 rounded-[2px] bg-iris" />
              새 진단 · 첫 시술이 있던 달
            </span>
          </p>
        </>
      )}
    </section>
  );
}
