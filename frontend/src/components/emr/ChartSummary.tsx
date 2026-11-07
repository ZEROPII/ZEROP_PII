import type { ChartGroup, ChartItem, EmrChart } from '../../types/domain';

const KIND_KO: Record<EmrChart['visits'][number]['items'][number]['kind'], string> = {
  problems: '진단',
  medications: '처방',
  procedures: '시술',
  carePlans: '관리',
};

/** 한 줄 아래의 작은 글: 몇 번 · 처음 날 · 진행 중이거나 끝난 날 */
function itemNote(x: ChartItem, ongoing: boolean): string {
  const parts: string[] = [];
  if (x.times > 1) parts.push(`${x.times}회${x.first && x.first !== x.last ? ` · 처음 ${x.first}` : ''}`);
  if (ongoing) parts.push(x.active ? '진행 중' : x.ended ? `종료 ${x.ended}` : '');
  return parts.filter(Boolean).join(' · ');
}

function Section({ title, group, empty, ongoing = true }: { title: string; group: ChartGroup; empty: string; ongoing?: boolean }) {
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
            const note = itemNote(x, ongoing);
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
                    <span className="num shrink-0 text-xs text-ink-3">{x.last ?? '–'}</span>
                  </span>
                  {note && <span className={`block text-[11.5px] ${ongoing && x.active ? 'text-iris-text' : 'text-ink-3'}`}>{note}</span>}
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

/** 해마다 내원한 날 수 (막대). 숫자는 막대 위 title과 화면 읽기 프로그램용 글로 함께 준다 */
function VisitFlow({ yearly, days }: { yearly: EmrChart['yearly']; days: number }) {
  const max = Math.max(1, ...yearly.map((y) => y.visits));
  return (
    <section className="rounded-control border border-line bg-surface" aria-label="내원 흐름">
      <h3 className="flex items-baseline gap-2 border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">
        내원 흐름
        <span className="num ml-auto text-xs font-normal text-ink-3">내원 {days}일</span>
      </h3>
      {yearly.length === 0 ? (
        <p className="px-3.5 py-3 text-[13px] text-ink-3">내원 기록이 없습니다.</p>
      ) : (
        <div className="px-3.5 pb-2.5 pt-3">
          <ol className="flex h-[72px] items-end gap-1.5" aria-label="해마다 내원한 날 수">
            {yearly.map((y) => (
              <li key={y.year} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${y.year}년 ${y.visits}일`}>
                <span className="sr-only">
                  {y.year}년 {y.visits}일
                </span>
                {y.visits > 0 && <span aria-hidden className="num mb-0.5 text-center text-[10.5px] text-ink-3">{y.visits}</span>}
                <span
                  aria-hidden
                  className={`block rounded-t-[3px] ${y.visits ? 'bg-iris' : 'bg-line'}`}
                  style={{ height: y.visits ? `${Math.max(8, (y.visits / max) * 52)}px` : '2px' }}
                />
              </li>
            ))}
          </ol>
          <div aria-hidden className="mt-1 flex gap-1.5">
            {yearly.map((y, i) => (
              <span key={y.year} className="num min-w-0 flex-1 text-center text-[10.5px] text-ink-3">
                {i === 0 || i === yearly.length - 1 || y.year % 5 === 0 ? `'${String(y.year).slice(2)}` : ''}
              </span>
            ))}
          </div>
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
 * 같은 이름은 한 줄로 묶었고 끝나지 않은 것이 먼저 온다. 생년 · 거주 지역은 서버가 보내지 않는다.
 * 의료진 환자 화면과 보안 담당자의 사유를 적은 차트 열람이 같이 쓴다.
 */
export function ChartSummary({ chart, wide = true }: { chart: EmrChart; wide?: boolean }) {
  return (
    // grid-cols-1(minmax(0, 1fr))이어야 긴 시술 이름(한 줄로 줄임)이 칸을 밀어 넓히지 않는다
    <div className={`grid grid-cols-1 gap-3 ${wide ? '2xl:grid-cols-2' : ''}`}>
      <Section title="진단 이력" group={chart.problems} empty="진단 기록이 없습니다." />
      <Section title="처방" group={chart.medications} empty="처방 기록이 없습니다." />
      <Section title="시술" group={chart.procedures} empty="시술 기록이 없습니다." ongoing={false} />
      <Section title="관리 계획" group={chart.carePlans} empty="관리 계획이 없습니다." />
      <RecentVisits visits={chart.visits} />
      <VisitFlow yearly={chart.yearly} days={chart.visitDays} />
    </div>
  );
}
