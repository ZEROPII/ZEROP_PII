import { useState } from 'react';
import { daysWithinYear, sinceDay } from '../../lib/time';
import type { ChartGroup, ChartItem, EmrChart } from '../../types/domain';

const KIND_KO: Record<EmrChart['visits'][number]['items'][number]['kind'], string> = {
  problems: '진단',
  medications: '처방',
  procedures: '시술',
  carePlans: '관리',
};

/**
 * 한 줄 아래의 작은 글: 몇 번 · 처음 날 · 진행 중이거나 끝난 날.
 * 종료일이 없어도 오래된 처방 · 급성 질환은 '진행 중'이 아니라 '종료일 없음'으로 보인다 (서버가 noEnd로 알려 준다).
 */
function itemNote(x: ChartItem, ongoing: boolean, what: string): string {
  const parts: string[] = [];
  if (x.times > 1) parts.push(`${x.times}회${x.first && x.first !== x.last ? ` · 처음 ${x.first}` : ''}`);
  if (ongoing) parts.push(x.active ? '진행 중' : x.noEnd ? `종료일 없음 · 오래된 ${what}` : x.ended ? `종료 ${x.ended}` : '');
  return parts.filter(Boolean).join(' · ');
}

const NO_END_HINT = '종료일이 기록되지 않았지만, 마지막 기록이 마지막 내원보다 1년 넘게 앞서 진행 중으로 세지 않았습니다.';

function Section({ title, group, empty, ongoing = true, what = '기록' }: { title: string; group: ChartGroup; empty: string; ongoing?: boolean; what?: string }) {
  const more = group.total - group.items.length;
  return (
    <section className="rounded-control border border-line bg-surface" aria-label={title}>
      <h3 className="flex items-baseline gap-2 border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">
        {title}
        {ongoing && group.active > 0 && <span className="text-xs font-semibold text-iris-text">진행 중 {group.active}</span>}
        <span className="num ml-auto text-xs font-normal text-ink-3">{group.total}건</span>
      </h3>
      {group.items.length === 0 ? (
        <p className="px-3.5 py-3 text-[13px] text-ink-3">{empty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {group.items.map((x) => {
            const note = itemNote(x, ongoing, what);
            return (
              <li key={x.label} className="flex gap-2.5 px-3.5 py-2">
                <span
                  aria-hidden
                  className={`mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full ${ongoing && x.active ? 'bg-iris' : 'border border-ink-3'}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-3">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink" title={x.label}>
                      {x.label}
                    </span>
                    <span className="num shrink-0 text-xs text-ink-3" title={`마지막 ${what}`}>
                      {x.last ?? '–'}
                    </span>
                  </span>
                  {note && (
                    <span className={`block text-[11.5px] ${ongoing && x.active ? 'text-iris-text' : 'text-ink-3'}`} title={x.noEnd ? NO_END_HINT : undefined}>
                      {note}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {more > 0 && <p className="border-t border-line px-3.5 py-2 text-xs text-ink-3">이전 기록 {more}건은 줄였습니다</p>}
    </section>
  );
}

/**
 * 내원 흐름: 먼저 숫자 셋(마지막 내원 · 최근 1년 · 전체)으로 '언제 마지막으로 왔고 요즘 얼마나 오는지'를 보이고,
 * 그 아래 해마다 내원한 날 수를 막대로 (마지막 내원 해까지 최근 10년). 막대 위 숫자는 가장 많은 해에만 붙이고,
 * 나머지는 마우스를 올리면 보인다. 화면 읽기 프로그램에는 해마다 날 수를 목록으로 준다.
 */
function VisitFlow({ chart }: { chart: EmrChart }) {
  const [hover, setHover] = useState<number | null>(null);
  const years = chart.yearly;
  const dates = chart.visitDates ?? [];
  const last = chart.visits[0]?.date ?? dates[dates.length - 1] ?? null;
  const recent = daysWithinYear(dates);
  const max = Math.max(1, ...years.map((y) => y.visits));
  const peak = years.reduce<EmrChart['yearly'][number] | null>((a, b) => (b.visits > (a?.visits ?? 0) ? b : a), null);
  const firstYear = chart.firstRecord?.slice(0, 4);
  const stats: [string, string, string][] = [
    ['마지막 내원', last ?? '–', last ? sinceDay(last) : ''],
    ['최근 1년', `${recent}일`, recent ? '지난 1년 동안' : '지난 1년은 내원 없음'],
    ['전체', `${chart.visitDays}일`, firstYear ? `${firstYear}년부터` : ''],
  ];
  return (
    <section className="rounded-control border border-line bg-surface" aria-label="내원 흐름">
      <h3 className="border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">내원 흐름</h3>
      {years.length === 0 ? (
        <p className="px-3.5 py-3 text-[13px] text-ink-3">내원 기록이 없습니다.</p>
      ) : (
        <div className="px-3.5 pb-3 pt-3">
          <dl className="grid grid-cols-3 gap-2">
            {stats.map(([k, v, sub]) => (
              <div key={k} className="min-w-0">
                <dt className="text-[11px] text-ink-3">{k}</dt>
                <dd className="num mt-0.5 truncate text-[14px] font-bold text-ink">{v}</dd>
                <dd className="truncate text-[11px] text-ink-3">{sub}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-[11px] text-ink-3">
            해마다 내원한 날 ({years[0].year}~{years[years.length - 1].year})
          </p>
          <div className="relative mt-1">
            {/* 막대 위 숫자: 가장 많은 해에만, 마우스를 올린 해는 '2024년 12일'. 막대 끝 바로 위에 붙고, 가장 높은 막대 위에도 자리가 남게 칸을 높게 둔다 */}
            <ol className="flex h-[78px] items-end gap-[2px] border-b border-line" aria-hidden onMouseLeave={() => setHover(null)}>
              {years.map((y) => {
                const label = hover === y.year ? `${y.year}년 ${y.visits}일` : hover === null && peak?.year === y.year && y.visits > 0 ? `${y.visits}일` : null;
                const tip = label && (
                  <span className="num pointer-events-none absolute bottom-full left-1/2 mb-0.5 -translate-x-1/2 whitespace-nowrap text-[10.5px] font-semibold text-ink-2">
                    {label}
                  </span>
                );
                return (
                  <li
                    key={y.year}
                    className={`relative flex h-full min-w-0 flex-1 cursor-default flex-col items-center justify-end ${hover === y.year ? 'bg-surface-2' : ''}`}
                    onMouseEnter={() => setHover(y.year)}
                  >
                    {y.visits > 0 ? (
                      <span className="relative block w-full max-w-[24px] rounded-t-[4px] bg-iris" style={{ height: `${Math.max(3, (y.visits / max) * 56)}px` }}>
                        {tip}
                      </span>
                    ) : (
                      <span className="relative block h-0 w-full">{tip}</span>
                    )}
                  </li>
                );
              })}
            </ol>
            <div aria-hidden className="mt-1 flex gap-[2px]">
              {years.map((y, i) => (
                <span key={y.year} className="num min-w-0 flex-1 text-center text-[10.5px] text-ink-3">
                  {years.length <= 10 || i === 0 || i === years.length - 1 ? `'${String(y.year).slice(2)}` : ''}
                </span>
              ))}
            </div>
          </div>
          <ul className="sr-only">
            {years.map((y) => (
              <li key={y.year}>
                {y.year}년 내원 {y.visits}일
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function RecentVisits({ visits }: { visits: EmrChart['visits'] }) {
  return (
    <section className="rounded-control border border-line bg-surface" aria-label="최근 내원">
      <h3 className="border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">최근 내원</h3>
      {visits.length === 0 ? (
        <p className="px-3.5 py-3 text-[13px] text-ink-3">내원 기록이 없습니다.</p>
      ) : (
        <ol className="divide-y divide-line">
          {visits.map((v, i) => (
            <li key={`${v.date}-${i}`} className="grid grid-cols-[84px_minmax(0,1fr)] gap-2 px-3.5 py-2">
              <span className="num pt-px text-xs font-semibold text-ink-2">{v.date}</span>
              <ul className="min-w-0 space-y-0.5">
                {v.items.slice(0, 4).map((x) => (
                  <li key={`${x.kind}:${x.label}`} className="flex min-w-0 items-baseline gap-1.5 text-[12.5px]">
                    <span className="shrink-0 text-[11px] font-semibold text-ink-3">{KIND_KO[x.kind]}</span>
                    <span className="truncate text-ink" title={x.label}>
                      {x.label}
                    </span>
                  </li>
                ))}
                {v.items.length > 4 && <li className="text-[11.5px] text-ink-3">외 {v.items.length - 4}건</li>}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * EMR 차트 요약: 진단 이력 · 처방 · 시술 · 관리 계획 · 최근 내원 · 내원 흐름.
 * 같은 이름은 한 줄로 묶었고 진행 중인 것이 먼저 온다. 생년 · 거주 지역은 서버가 보내지 않는다.
 * 의료진 환자 화면과 보안 담당자의 사유를 적은 차트 열람이 같이 쓴다.
 */
export function ChartSummary({ chart, wide = true }: { chart: EmrChart; wide?: boolean }) {
  return (
    // grid-cols-1(minmax(0, 1fr))이어야 긴 시술 이름(한 줄로 줄임)이 칸을 밀어 넓히지 않는다
    <div className={`grid grid-cols-1 gap-3 ${wide ? '2xl:grid-cols-2' : ''}`}>
      <VisitFlow chart={chart} />
      <Section title="진단 이력" group={chart.problems} empty="진단 기록이 없습니다." />
      <Section title="처방" group={chart.medications} empty="처방 기록이 없습니다." what="처방" />
      <Section title="시술" group={chart.procedures} empty="시술 기록이 없습니다." ongoing={false} what="시행" />
      <Section title="관리 계획" group={chart.carePlans} empty="관리 계획이 없습니다." />
      <RecentVisits visits={chart.visits} />
    </div>
  );
}
