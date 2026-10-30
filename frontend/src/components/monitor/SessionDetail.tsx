import { ChevronDown, ChevronUp, Eye } from 'lucide-react';
import { useMemo, useState } from 'react';
import { caseLabel, relativeTime } from '../../lib/time';
import type { MonitorDetail, ReviewAction, TurnView } from '../../types/monitor';
import { StatusChip } from '../common/StatusChip';
import { CrowdLens } from '../viz/CrowdLens';

const TONE = { danger: 'danger', caution: 'caution', safe: 'safe' } as const;
const ATTR_KO: Record<string, string> = { AGE: '나이', SEX: '성별', REGION: '거주지', PERIOD: '시점', DX: '진단', PROC: '시술', MED: '약', PLAN: '관리 계획' };
const CHANGE = { suppress: { tone: 'danger', label: '가림' }, generalize: { tone: 'caution', label: '일반화' } } as const;

type Group = { kind: 'turn'; turn: TurnView } | { kind: 'fold'; turns: TurnView[] };

function lastK(series: [number, number][] | undefined): number | null {
  return series && series.length ? series[series.length - 1][1] : null;
}

function summarize(d: MonitorDetail): string {
  const r = d.row;
  const focus = caseLabel(r.focus_case);
  const turns = d.arms[d.live_arm].turns;
  const hits = turns.filter((t) =>
    t.change_notes.some((n) => n.case === r.focus_case && n.changes.some((c) => (r.status === 'danger' ? c.change === 'suppress' : true))),
  ).length;
  if (r.status === 'danger')
    return `${focus} 환자를 좁히는 질문에 값을 가린 답이 ${hits}번 있었습니다. 그대로 답했다면 후보가 ${r.k_if_raw}명으로 줄어 환자가 특정될 수 있었습니다. 방어 규칙이 값을 가려 후보 ${r.k_now}명을 지켰습니다.`;
  if (r.status === 'caution')
    return `${focus} 답에서 넓은 범주로 바꾼 값이 ${hits}번 있었습니다. 그대로였다면 후보가 ${r.k_if_raw}명이었고, 지금은 ${r.k_now}명입니다.`;
  return `모든 답을 그대로 보냈습니다. 후보가 기준 ${d.k_req}명보다 많게 유지되었습니다.`;
}

interface Props {
  detail: MonitorDetail;
  onReveal(): void;
  onReview(action: ReviewAction): void;
  busy: boolean;
}

export function SessionDetail({ detail: d, onReveal, onReview, busy }: Props) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const r = d.row;
  const c1 = d.arms[d.live_arm];
  const focus = r.focus_case;

  const groups = useMemo<Group[]>(() => {
    const out: Group[] = [];
    for (const t of c1.turns) {
      const quiet = t.turn > 0 && t.change_notes.length === 0;
      const prev = out[out.length - 1];
      if (quiet && prev?.kind === 'fold') prev.turns.push(t);
      else if (quiet) out.push({ kind: 'fold', turns: [t] });
      else out.push({ kind: 'turn', turn: t });
    }
    return out.map((g) => (g.kind === 'fold' && g.turns.length === 1 ? { kind: 'turn', turn: g.turns[0] } : g));
  }, [c1.turns]);

  const c0k = focus ? lastK(d.arms.C0?.k_series[focus]) : null;
  const c1sk = focus ? lastK(d.arms.C1S?.k_series[focus]) : null;
  const focusPatient = d.retrieval.find((x) => x.ref === focus)?.patient;

  function turnBlock(t: TurnView) {
    const hit = t.change_notes.some((n) => n.changes.some((c) => c.change === 'suppress'));
    const attrs = [...new Set(t.lines.filter((l) => l.case).map((l) => ATTR_KO[l.attribute ?? ''] ?? l.attribute))].filter(Boolean);
    const rawChanged = d.revealed
      ? t.lines.flatMap((l, i) => {
          const raw = t.raw_lines?.[i];
          return l.change && raw?.case ? [`${caseLabel(raw.case)} ${raw.field}: ${raw.value ?? ''}`] : [];
        })
      : [];
    return (
      <div key={t.turn} className="relative grid grid-cols-[28px_1fr] gap-2.5 pb-3.5">
        <span className={`relative z-[1] grid h-[26px] w-[26px] place-items-center rounded-full border bg-surface text-[11px] font-bold ${hit ? 'border-danger text-danger-text' : 'border-line-input text-ink-2'}`}>
          {t.turn}
        </span>
        <div className="min-w-0">
          <p className="text-[13px] text-ink">{t.turn === 0 ? `사례 검색: ${t.question}` : t.question}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
            {t.change_notes.length === 0 ? (
              <>
                <StatusChip tone="safe">허용</StatusChip>
                <span>{attrs.length ? `${attrs.join(', ')} 그대로` : '새 단서 없음'}</span>
              </>
            ) : (
              t.change_notes.flatMap((n) =>
                n.changes.map((c, i) => {
                  const meta = CHANGE[c.change as keyof typeof CHANGE] ?? CHANGE.generalize;
                  return (
                    <span key={`${n.case}-${i}`} className="inline-flex items-center gap-1.5">
                      <StatusChip tone={meta.tone}>{meta.label}</StatusChip>
                      <span>
                        {caseLabel(n.case)} {c.attribute}
                        {n.k_if_raw != null && <span className="text-ink-3"> (그대로면 {n.k_if_raw}명)</span>}
                      </span>
                    </span>
                  );
                }),
              )
            )}
          </div>
          {rawChanged.length > 0 && (
            <div className="mt-1.5 rounded-cell bg-surface-2 px-2.5 py-1.5 text-xs leading-5 text-ink-2">
              {rawChanged.map((ln) => (
                <div key={ln}>
                  <span className="mr-1.5 font-semibold text-ink">원래 답</span>
                  {ln}
                </div>
              ))}
            </div>
          )}
        </div>
        <span className="absolute bottom-0 left-[13px] top-[26px] w-px bg-line" aria-hidden />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-line px-5 pb-4 pt-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="font-mono text-[15px] font-medium">{d.trial_id}</span>
          <StatusChip tone={TONE[r.status]}>{r.status_label}</StatusChip>
          <span className="text-xs text-ink-3">
            {d.source_label} {r.turns}턴 {relativeTime(r.last_active)}
          </span>
          {r.review && <StatusChip tone="plain">{r.review.label}</StatusChip>}
        </div>
        <p className="mt-3 max-w-[40em] text-[15px] leading-relaxed">{summarize(d)}</p>
      </header>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <div className="grid grid-cols-[140px_1fr] items-center gap-5 border-b border-line px-5 py-4">
          <CrowdLens k={r.k_now ?? d.p_ref} size={140} threshold={d.k_req} ghost={r.status !== 'safe' ? r.k_if_raw : null} label={`${caseLabel(focus)} 후보 ${r.k_now}명`} />
          <div className="min-w-0">
            <p className="num text-[48px] font-extrabold leading-none tracking-[-0.04em]">
              {r.k_now ?? '–'}
              <small className="ml-0.5 text-lg font-bold tracking-normal">명</small>
            </p>
            <p className="mt-1.5 text-[13px] text-ink-2">{caseLabel(focus)}과 조건이 같은 환자</p>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
              {r.k_if_raw != null && r.status !== 'safe' && (
                <>
                  <dt className="text-ink-3">가리지 않았다면</dt>
                  <dd className="font-semibold text-danger-text">{r.k_if_raw}명</dd>
                </>
              )}
              {(c0k != null || c1sk != null) && (
                <>
                  <dt className="text-ink-3">다른 방식이었다면</dt>
                  <dd className="text-ink-2">
                    {c0k != null && `방어 없음 ${c0k}명`}
                    {c0k != null && c1sk != null && ', '}
                    {c1sk != null && `턴별 방어 ${c1sk}명`}
                  </dd>
                </>
              )}
              <dt className="text-ink-3">기준</dt>
              <dd>{d.k_req}명 아래로 줄지 않게</dd>
              <dt className="text-ink-3">환자</dt>
              <dd className="flex items-center gap-2">
                {d.revealed ? (
                  <span className="font-mono text-xs">{focusPatient ?? '–'}</span>
                ) : (
                  <>
                    <span className="redact" style={{ width: 88 }} aria-label="가려진 환자 번호" />
                    <button type="button" onClick={onReveal} className="btn-ghost btn-sm h-6 px-1.5">
                      <Eye className="h-3.5 w-3.5" aria-hidden />
                      사유 적고 보기
                    </button>
                  </>
                )}
              </dd>
            </dl>
          </div>
        </div>

        <div className="px-5 pt-4">
          <h3 className="mb-2.5 text-[13px] font-bold text-ink-2">질문 흐름</h3>
          {groups.map((g, gi) =>
            g.kind === 'turn' ? (
              turnBlock(g.turn)
            ) : open.has(gi) ? (
              <div key={`f${gi}`}>
                {g.turns.map(turnBlock)}
                <button type="button" className="btn-ghost btn-sm mb-3 ml-9 h-6 px-1.5" onClick={() => setOpen((s) => new Set([...s].filter((x) => x !== gi)))}>
                  <ChevronUp className="h-3.5 w-3.5" aria-hidden /> 접기
                </button>
              </div>
            ) : (
              <div key={`f${gi}`} className="relative grid grid-cols-[28px_1fr] gap-2.5 pb-3.5">
                <span className="relative z-[1] grid h-[26px] w-[26px] place-items-center rounded-full border border-dashed border-line-input bg-surface text-[10px] font-bold text-ink-2">
                  {g.turns[0].turn}–{g.turns[g.turns.length - 1].turn}
                </span>
                <p className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
                  {g.turns.length}턴 모두 그대로 답했습니다.
                  <button type="button" className="btn-ghost btn-sm h-6 px-1.5" onClick={() => setOpen((s) => new Set(s).add(gi))}>
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden /> 펼치기
                  </button>
                </p>
                <span className="absolute bottom-0 left-[13px] top-[26px] w-px bg-line" aria-hidden />
              </div>
            ),
          )}
        </div>
      </div>

      <footer className="flex flex-wrap gap-2 border-t border-line px-5 py-3.5">
        <button type="button" className="btn-primary" disabled={busy} onClick={() => onReview('reviewed')}>
          검토 완료
        </button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => onReview('ask_clinician')}>
          의료진에게 확인 요청
        </button>
        <span className="flex-1" />
        <button type="button" className="btn-ghost" disabled={busy} onClick={() => onReview('add_rule')}>
          질문 패턴을 규칙에 추가
        </button>
      </footer>
    </div>
  );
}
