import { KIND_DOT, KIND_TEXT, type ChartKind } from '../../lib/kindStyle';
import type { ChartGroup, ChartItem, EmrChart } from '../../types/domain';
import { VisitHistory } from './VisitHistory';

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

/** 기록 종류 하나 (진단 · 처방 · 시술 · 관리). 제목 앞 띠 · 진행 중 점 · 진행 중 글자는 내원 달력과 같은 기록 종류 색 */
function Section({ kind, title, group, empty, ongoing = true, what = '기록' }: { kind: ChartKind; title: string; group: ChartGroup; empty: string; ongoing?: boolean; what?: string }) {
  const more = group.total - group.items.length;
  return (
    <section className="rounded-control border border-line bg-surface" aria-label={title}>
      <h3 className="flex items-center gap-2 border-b border-line px-3.5 py-2.5 text-[13px] font-bold text-ink">
        <span aria-hidden className={`h-3.5 w-[3px] rounded-full ${KIND_DOT[kind]}`} />
        {title}
        {ongoing && group.active > 0 && <span className={`text-xs font-semibold ${KIND_TEXT[kind]}`}>진행 중 {group.active}</span>}
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
                  className={`mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full ${ongoing && x.active ? KIND_DOT[kind] : 'border border-ink-3'}`}
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
                    <span className={`block text-[11.5px] ${ongoing && x.active ? KIND_TEXT[kind] : 'text-ink-3'}`} title={x.noEnd ? NO_END_HINT : undefined}>
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
 * EMR 차트 요약: 내원 이력(해마다 달력 · 고르면 그때 내원) · 진단 이력 · 처방 · 시술 · 관리 계획. 기록 종류마다 색이 같다.
 * 같은 이름은 한 줄로 묶었고 진행 중인 것이 먼저 온다. 생년 · 거주 지역은 서버가 보내지 않는다.
 * 의료진 환자 화면과 보안 담당자의 사유를 적은 차트 열람이 같이 쓴다.
 */
export function ChartSummary({ chart, wide = true }: { chart: EmrChart; wide?: boolean }) {
  return (
    // grid-cols-1(minmax(0, 1fr))이어야 긴 시술 이름(한 줄로 줄임)이 칸을 밀어 넓히지 않는다
    <div className={`grid grid-cols-1 gap-3 ${wide ? '2xl:grid-cols-2' : ''}`}>
      {/* 환자가 바뀌면 펼친 해를 처음으로 되돌린다 */}
      <VisitHistory key={chart.patient.fhirId} chart={chart} className={wide ? '2xl:col-span-2' : ''} />
      <Section kind="problems" title="진단 이력" group={chart.problems} empty="진단 기록이 없습니다." />
      <Section kind="medications" title="처방" group={chart.medications} empty="처방 기록이 없습니다." what="처방" />
      <Section kind="procedures" title="시술" group={chart.procedures} empty="시술 기록이 없습니다." ongoing={false} what="시행" />
      <Section kind="carePlans" title="관리 계획" group={chart.carePlans} empty="관리 계획이 없습니다." />
    </div>
  );
}
