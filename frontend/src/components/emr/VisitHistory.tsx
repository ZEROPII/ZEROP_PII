import { ChevronRight, X } from 'lucide-react';
import { useId, useMemo, useState, type FocusEvent, type KeyboardEvent } from 'react';
import { CELL, CELL_KO, KIND_CHIP, KIND_DOT, KIND_KO, KIND_TEXT, type CellCat } from '../../lib/kindStyle';
import { daysWithinYear } from '../../lib/time';
import { calendarLines, highlightsOf, monthCells, yearRows, type CalendarLine, type Highlight, type MonthCell, type YearRow } from '../../lib/visits';
import type { EmrChart } from '../../types/domain';

type Visit = EmrChart['visits'][number];
type Kind = Visit['items'][number]['kind'];
/** 달력에서 고른 것: 해 하나 또는 그해의 달 하나 (month 0이 1월) */
type Pick = { year: number; month: number | null };

const NEW_KO: Record<Kind, string> = { problems: '새 진단', procedures: '첫 시술', medications: '첫 처방', carePlans: '새 관리 계획' };
const KIND_ORDER: Kind[] = ['problems', 'procedures', 'medications', 'carePlans'];
const LEGEND: CellCat[] = ['problems', 'procedures', 'medications', 'carePlans', 'visit'];
/** 바로 보이는 해 수. 그보다 오래된 해가 둘 이상이면 '이전 기록' 한 줄로 접는다 */
const RECENT_YEARS = 5;
/** 아래 목록: 고른 것이 없을 때 보이는 최근 내원 수 · 해를 골랐을 때 먼저 보이는 내원 수 · 내원 하나에서 먼저 보이는 항목 수 */
const RECENT_VISITS = 5;
const FIRST_VISITS = 8;
const FIRST_ITEMS = 4;

const navKey = (year: number, month: number | null) => `${year}:${month ?? -1}`;

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

/** 그해 눈여겨볼 일: 이름은 세 개까지 (나머지는 '외 n건'), 같은 종류는 한 묶음. 앞말은 기록 종류 색 */
function Highlights({ row }: { row: YearRow }) {
  const list = useMemo(() => highlightsOf(row.visits), [row.visits]);
  if (!list.length)
    return <span className="vcal-note truncate text-[12px] text-ink-3">{row.visits.length ? '기록된 진단 · 처방 없음' : '오래되어 날짜만 남았습니다'}</span>;
  const shown = grouped(list.slice(0, 3));
  const rest = list.length - 3;
  return (
    <span className="vcal-note truncate text-[12.5px]" title={grouped(list).map((g) => `${prefix(g)} ${g.labels.join(', ')}`).join(' · ')}>
      {shown.map((g, i) => (
        <span key={`${g.type}:${g.kind}:${i}`}>
          {i > 0 && <span className="text-ink-3"> · </span>}
          <span className={`${KIND_TEXT[g.kind]} ${g.type === 'new' ? 'font-bold' : 'font-medium'}`}>{prefix(g)} </span>
          <span className="text-ink">{g.labels.join(', ')}</span>
        </span>
      ))}
      {rest > 0 && <span className="text-ink-3"> 외 {rest}건</span>}
    </span>
  );
}

/** 칸 설명 (화면 읽기 · 마우스를 올렸을 때) */
function cellLabel(year: number, c: MonthCell): string {
  const kinds = KIND_ORDER.filter((k) => c.visits.some((v) => v.items.some((x) => x.kind === k))).map((k) => KIND_KO[k]);
  const what = kinds.length ? `${kinds.join(' · ')} 기록` : c.visits.length ? '기록된 진단 · 처방 없음' : '오래되어 날짜만 남음';
  return `${year}년 ${c.month + 1}월 내원 ${c.n}번, ${what}${c.fresh ? ', 새 진단 · 첫 시술 있음' : ''}`;
}

/** 해 한 줄: 연도(누르면 그해 전체) · 내원 수 · 열두 달 칸(누르면 그달) · 그해 눈여겨볼 일 */
function YearLine({
  row,
  pick,
  tabKey,
  listId,
  onPick,
}: {
  row: YearRow;
  pick: Pick | null;
  tabKey: string;
  listId: string;
  onPick: (p: Pick | null) => void;
}) {
  const cells = useMemo(() => monthCells(row), [row]);
  const yearOn = pick?.year === row.year && pick.month === null;
  return (
    <div className="vcal-row py-[3px]">
      <button
        type="button"
        data-nav={navKey(row.year, null)}
        tabIndex={tabKey === navKey(row.year, null) ? 0 : -1}
        aria-pressed={yearOn}
        aria-controls={listId}
        aria-label={`${row.year}년 내원 ${row.days.length}번 모두 보기`}
        onClick={() => onPick(yearOn ? null : { year: row.year, month: null })}
        className="vcal-year num h-[22px] rounded-[5px] px-1 text-left text-[13px] font-bold text-ink hover:bg-surface-2"
      >
        {row.year}
      </button>
      <span className="num text-xs text-ink-2">{row.days.length}회</span>
      <span className="vcal-months">
        {[0, 1, 2, 3].map((q) => (
          <span key={q} className="vcal-q">
            {cells.slice(q * 3, q * 3 + 3).map((c) => {
              if (!c.cat) return <span key={c.month} aria-hidden className="vcal-cell" data-empty="" />;
              const on = pick?.year === row.year && pick.month === c.month;
              const label = cellLabel(row.year, c);
              return (
                <button
                  key={c.month}
                  type="button"
                  data-nav={navKey(row.year, c.month)}
                  tabIndex={tabKey === navKey(row.year, c.month) ? 0 : -1}
                  aria-pressed={on}
                  aria-controls={listId}
                  aria-label={label}
                  title={label}
                  data-fresh={c.fresh ? '' : undefined}
                  onClick={() => onPick(on ? null : { year: row.year, month: c.month })}
                  className={`vcal-cell ${CELL[c.cat]}`}
                >
                  {c.n >= 2 ? c.n : ''}
                </button>
              );
            })}
          </span>
        ))}
      </span>
      <Highlights row={row} />
    </div>
  );
}

/** 해 사이에 내원이 없던 해: 점선과 '2021~2023 내원 없음' */
function GapLine({ from, to }: { from: number; to: number }) {
  return (
    <div className="vcal-row py-[3px] text-[11.5px] text-ink-3">
      <span className="num col-span-2 truncate">{from === to ? from : `${from}~${to}`}</span>
      <span className="flex items-center gap-2">
        <span className="vcal-gap flex-1" />
        <span className="shrink-0">내원 없음</span>
        <span className="vcal-gap flex-1" />
      </span>
    </div>
  );
}

/** 내원 하나: 날짜와 그날 기록된 것 (기록 종류 이름표). 이 환자 기록에 처음 나온 것에는 '처음'이 붙는다 */
function VisitRow({ v, short }: { v: Visit; short: boolean }) {
  const [all, setAll] = useState(false);
  const items = all ? v.items : v.items.slice(0, FIRST_ITEMS);
  const hidden = v.items.length - items.length;
  const more = v.more ?? 0;
  return (
    <li className={`grid ${short ? 'grid-cols-[44px_minmax(0,1fr)]' : 'grid-cols-[82px_minmax(0,1fr)]'} gap-2 py-1.5`}>
      <span className="num pt-px text-xs font-semibold text-ink-2">{short ? v.date.slice(5) : v.date}</span>
      {v.items.length === 0 ? (
        <span className="text-[12px] text-ink-3">기록된 진단 · 처방 없음</span>
      ) : (
        <ul className="min-w-0 space-y-1">
          {items.map((x) => (
            <li key={`${x.kind}:${x.label}`} className="flex min-w-0 items-center gap-1.5 text-[12.5px]">
              <span className={`kind-chip ${KIND_CHIP[x.kind]}`}>{KIND_KO[x.kind]}</span>
              <span className="min-w-0 truncate text-ink" title={x.label}>
                {x.label}
              </span>
              {x.first && (
                <span className={`shrink-0 rounded-[4px] border border-current px-1 text-[10.5px] font-semibold leading-4 ${KIND_TEXT[x.kind]}`} title="이 환자 기록에 처음 나온 것">
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

/** 달력 아래 목록: 고른 해 · 달의 내원, 고른 것이 없으면 최근 내원 */
function VisitList({ rows, pick, listId, onClear }: { rows: YearRow[]; pick: Pick | null; listId: string; onClear: () => void }) {
  const [all, setAll] = useState(false);
  const row = pick ? rows.find((r) => r.year === pick.year) : undefined;
  let title: string;
  let visits: Visit[];
  let days: string[] = [];
  if (!pick || !row) {
    title = '최근 내원';
    visits = rows.flatMap((r) => r.visits).slice(0, RECENT_VISITS);
  } else if (pick.month === null) {
    title = `${row.year}년 내원 ${row.days.length}번`;
    visits = row.visits;
    days = row.days;
  } else {
    const m = String(pick.month + 1).padStart(2, '0');
    days = row.days.filter((d) => d.slice(5, 7) === m);
    visits = row.visits.filter((v) => v.date.slice(5, 7) === m);
    title = `${row.year}년 ${pick.month + 1}월 내원 ${days.length}번`;
  }
  const shown = pick && pick.month === null && !all ? visits.slice(0, FIRST_VISITS) : visits;
  const dateOnly = days.filter((d) => !visits.some((v) => v.date === d));
  return (
    <div id={listId} className="border-t border-line px-3.5 pb-2.5 pt-2" aria-live="polite">
      <div className="flex items-center gap-2">
        <h4 className="text-[12.5px] font-bold text-ink">{title}</h4>
        {pick ? (
          <button type="button" className="btn-ghost btn-sm ml-auto h-6 gap-1 px-1.5 text-[11.5px] text-ink-2" onClick={onClear}>
            <X className="h-3 w-3" aria-hidden />
            최근 내원 보기
          </button>
        ) : (
          <span className="ml-auto text-[11.5px] text-ink-3">달력에서 해나 달을 누르면 그때 내원을 봅니다</span>
        )}
      </div>
      {shown.length > 0 && (
        <ol className="mt-0.5 divide-y divide-line">
          {shown.map((v) => (
            <VisitRow key={v.date} v={v} short={!!pick} />
          ))}
        </ol>
      )}
      {visits.length > shown.length && (
        <button type="button" className="mt-1 text-[11.5px] font-semibold text-iris-text hover:underline" onClick={() => setAll(true)}>
          이 해 내원 {visits.length}번 모두 보기
        </button>
      )}
      {dateOnly.length > 0 && (
        <p className="mt-1 text-[11.5px] text-ink-3">
          {visits.length ? `나머지 ${dateOnly.length}번은` : '이때 내원은'} 오래되어 날짜만 있습니다:{' '}
          <span className="num">
            {dateOnly
              .slice(0, 12)
              .map((d) => d.slice(5))
              .join(', ')}
            {dateOnly.length > 12 ? ` 외 ${dateOnly.length - 12}번` : ''}
          </span>
        </p>
      )}
    </div>
  );
}

/** 칸을 화살표로 옮겨 다닌다: 좌우는 앞뒤 칸, 위아래는 옆 해의 가까운 달, Home · End는 그해 처음 · 끝 */
function moveFocus(e: KeyboardEvent<HTMLDivElement>, setTab: (k: string) => void) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
  const from = e.target as HTMLElement;
  if (!from.dataset.nav) return;
  const all = [...e.currentTarget.querySelectorAll<HTMLElement>('[data-nav]')];
  const pos = (el: HTMLElement) => el.dataset.nav!.split(':').map(Number);
  const [y, m] = pos(from);
  const i = all.indexOf(from);
  let to: HTMLElement | undefined;
  if (e.key === 'ArrowRight') to = all[i + 1];
  else if (e.key === 'ArrowLeft') to = all[i - 1];
  else if (e.key === 'Home') to = all.find((el) => pos(el)[0] === y);
  else if (e.key === 'End') to = [...all].reverse().find((el) => pos(el)[0] === y);
  else {
    const years = [...new Set(all.map((el) => pos(el)[0]))];
    const ny = years[years.indexOf(y) + (e.key === 'ArrowDown' ? 1 : -1)];
    const inRow = ny === undefined ? [] : all.filter((el) => pos(el)[0] === ny);
    to = inRow.reduce<HTMLElement | undefined>((best, el) => (!best || Math.abs(pos(el)[1] - m) < Math.abs(pos(best)[1] - m) ? el : best), undefined);
  }
  if (!to) return;
  e.preventDefault();
  setTab(to.dataset.nav!);
  to.focus();
}

/**
 * 내원 이력 (ADR-0038 · ADR-0040): 해마다 한 줄인 달력. 칸은 그달 가장 중요한 기록의 색(진단 · 시술 · 처방 · 관리 · 내원만),
 * 숫자는 그달 내원 수, 점은 새 진단 · 첫 시술. 내원이 없던 해는 점선 한 줄로 이어 보이고, 최근 5년이 넘는 해는 '이전 기록'으로 접는다.
 * 연도나 칸을 누르면 아래 목록이 그해 · 그달 내원으로 바뀐다. 고른 것이 없으면 최근 내원 5번.
 */
export function VisitHistory({ chart, className = '' }: { chart: EmrChart; className?: string }) {
  const dates = useMemo(() => chart.visitDates ?? chart.visits.map((v) => v.date).sort(), [chart.visitDates, chart.visits]);
  const rows = useMemo(() => yearRows(dates, chart.visits), [dates, chart.visits]);
  const lines = useMemo(() => calendarLines(rows), [rows]);
  const [pick, setPick] = useState<Pick | null>(null);
  const [olderOpen, setOlderOpen] = useState(false);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const listId = useId();
  const year = daysWithinYear(dates);

  // 최근 5년 줄까지 (사이 '내원 없음' 줄 포함). 접을 해가 하나뿐이면 접지 않는다
  const cutAt = rows.length > RECENT_YEARS + 1 ? lines.findIndex((l) => l.type === 'year' && l.row.year === rows[RECENT_YEARS].year) : lines.length;
  const recent = lines.slice(0, cutAt);
  const older = lines.slice(cutAt);
  const olderRows = rows.slice(rows.length > RECENT_YEARS + 1 ? RECENT_YEARS : rows.length);
  const shownLines: CalendarLine[] = olderOpen ? lines : recent;
  // 칸 사이 Tab 멈춤은 하나: 마지막에 머문 칸, 없으면 고른 것, 그것도 없으면 가장 최근 해
  const keys = new Set(
    shownLines.flatMap((l) => (l.type === 'year' ? [navKey(l.row.year, null), ...l.row.months.flatMap((n, m) => (n ? [navKey(l.row.year, m)] : []))] : [])),
  );
  const fallback = pick && keys.has(navKey(pick.year, pick.month)) ? navKey(pick.year, pick.month) : rows[0] ? navKey(rows[0].year, null) : '';
  const tabKey = focusKey && keys.has(focusKey) ? focusKey : fallback;
  const onFocus = (e: FocusEvent<HTMLDivElement>) => {
    const k = (e.target as HTMLElement).dataset.nav;
    if (k) setFocusKey(k);
  };
  const line = (l: CalendarLine) =>
    l.type === 'gap' ? (
      <GapLine key={`gap:${l.from}`} from={l.from} to={l.to} />
    ) : (
      <YearLine key={l.row.year} row={l.row} pick={pick} tabKey={tabKey} listId={listId} onPick={setPick} />
    );

  return (
    <section className={`vcal rounded-control border border-line bg-surface ${className}`} aria-label="내원 이력">
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
          <div className="px-3.5 pb-2 pt-2">
            <div aria-hidden className="vcal-row pb-1 text-[10.5px] text-ink-3">
              <span>연도</span>
              <span>내원</span>
              <span className="vcal-months">
                {[0, 1, 2, 3].map((q) => (
                  <span key={q} className="vcal-q">
                    {[1, 2, 3].map((k) => (
                      <span key={k} className="num text-center">
                        {q * 3 + k}
                      </span>
                    ))}
                  </span>
                ))}
              </span>
            </div>
            <div role="group" aria-label="해마다 달마다 내원 달력. 화살표로 칸을 옮기고 Enter로 고릅니다" onKeyDown={(e) => moveFocus(e, setFocusKey)} onFocus={onFocus}>
              {recent.map(line)}
              {older.length > 0 && (
                <div className="vcal-row py-[3px]">
                  <button
                    type="button"
                    aria-expanded={olderOpen}
                    onClick={() => setOlderOpen((o) => !o)}
                    className="vcal-wide flex items-center gap-1.5 rounded-[5px] py-0.5 text-left text-[12px] text-ink-2 hover:text-ink"
                  >
                    <ChevronRight className={`h-3.5 w-3.5 text-ink-3 transition-transform motion-reduce:transition-none ${olderOpen ? 'rotate-90' : ''}`} aria-hidden />
                    이전 기록{' '}
                    <span className="num">
                      {olderRows[olderRows.length - 1].year}~{olderRows[0].year}
                    </span>
                    <span className="text-ink-3">·</span>
                    <span className="num">{olderRows.reduce((n, r) => n + r.days.length, 0)}회</span>
                    <span className="text-ink-3">{olderOpen ? '접기' : '펼치기'}</span>
                  </button>
                </div>
              )}
              {olderOpen && older.map(line)}
            </div>
            <p aria-hidden className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-2">
              {LEGEND.map((k) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className={`h-2.5 w-2.5 rounded-[3px] ${k === 'visit' ? CELL.visit : KIND_DOT[k]}`} />
                  {CELL_KO[k]}
                </span>
              ))}
              <span className="inline-flex items-center gap-1">
                <span className="relative h-2.5 w-2.5 rounded-[3px] bg-kind-dx">
                  <span className="absolute right-[1.5px] top-[1.5px] h-[3px] w-[3px] rounded-full bg-kind-dx-on" />
                </span>
                새 진단 · 첫 시술
              </span>
              <span className="text-ink-3">숫자는 그달 내원 수, 한 달에 여러 기록이면 진단 · 시술 · 처방 · 관리 순으로 앞선 색</span>
            </p>
          </div>
          <VisitList key={pick ? navKey(pick.year, pick.month) : 'recent'} rows={rows} pick={pick} listId={listId} onClear={() => setPick(null)} />
        </>
      )}
    </section>
  );
}
