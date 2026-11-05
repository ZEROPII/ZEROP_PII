import { MailQuestion } from 'lucide-react';
import { relativeTime, caseLabel } from '../../lib/time';
import type { MonitorRow } from '../../types/monitor';
import { StatusChip, StatusIcon } from '../common/StatusChip';
import { RangeMini } from '../viz/Instruments';

const TONE = { danger: 'danger', caution: 'caution', safe: 'safe' } as const;

interface Props {
  rows: MonitorRow[];
  selected: string | null;
  onSelect(id: string): void;
  kReq: number;
  /** 기준 집단 크기 (로그 눈금의 오른쪽 끝) */
  pRef?: number;
}

export function QueueTable({ rows, selected, onSelect, kReq, pRef = 461 }: Props) {
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead>
        <tr className="text-left text-xs text-ink-3">
          <th className="w-[132px] border-b border-line px-3 py-2.5 font-semibold">상태</th>
          <th className="border-b border-line px-3 py-2.5 font-semibold">대화</th>
          <th className="hidden border-b border-line px-3 py-2.5 font-semibold xl:table-cell">막은 정보</th>
          <th className="border-b border-line px-3 py-2.5 text-right font-semibold">후보 수</th>
          <th className="hidden w-[84px] border-b border-line px-3 py-2.5 text-right font-semibold sm:table-cell">마지막 활동</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const sel = r.id === selected;
          return (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              aria-selected={sel}
              className={`cursor-pointer ${sel ? 'bg-iris-tint' : 'hover:bg-surface-2'}`}
            >
              <td className={`border-b border-line px-3 py-3 align-middle ${sel ? 'shadow-[inset_3px_0_0_var(--zp-iris)]' : ''}`}>
                <StatusChip tone={TONE[r.status]}>{r.status_label}</StatusChip>
              </td>
              <td className="border-b border-line px-3 py-3 align-middle">
                <button type="button" onClick={() => onSelect(r.id)} className="text-left">
                  <span className="font-mono text-[13px] text-ink">{r.trial_id}</span>
                  <span className="ml-2 text-xs text-ink-3">{r.owner ? `${r.source_label} · ${r.owner}` : r.source_label}</span>
                </button>
                <div className="text-xs text-ink-3">
                  {r.qtype_label} {r.turns}턴
                  {r.llm_mode === 'live' && <span className="ml-1.5 rounded-[4px] bg-surface-2 px-1 py-px text-[10.5px] font-semibold text-ink-2">LLM</span>}
                  {r.archived && <span className="ml-1.5 rounded-[4px] bg-surface-2 px-1 py-px text-[10.5px] font-semibold text-ink-2">지난 대화</span>}
                </div>
                {r.flag &&
                  (r.pending_request ? (
                    <div className="mt-1 inline-flex items-center gap-1 rounded-[5px] bg-iris-tint px-1.5 py-px text-[11px] font-semibold text-iris-text">
                      <MailQuestion className="h-3 w-3" aria-hidden />
                      {r.flag}
                      {r.request_case && <span className="font-normal">{caseLabel(r.request_case)}</span>}
                    </div>
                  ) : (
                    <div className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-caution-text">
                      <StatusIcon tone="caution" className="h-2.5 w-2.5" />
                      {r.flag}
                    </div>
                  ))}
                {r.violated.length > 0 && (
                  <div className="mt-1 text-[11px] font-semibold text-danger-text">기준 아래 · {r.violated.map(caseLabel).join(', ')}</div>
                )}
                {(r.approved_low ?? []).length > 0 && (
                  <div className="mt-1 text-[11px] text-ink-2" title="보안 담당자가 승인해 공개해서 후보가 기준 아래가 된 사례 (경보로 세지 않음)">
                    승인 공개로 기준 아래 · {r.approved_low!.map(caseLabel).join(', ')}
                  </div>
                )}
                {r.review && (
                  <div className="mt-1 text-[11px] font-semibold text-ink-3">
                    {r.review.label}
                    {r.awaiting_clinician && <span className="ml-1 font-normal">(의료진 답 기다림)</span>}
                  </div>
                )}
              </td>
              <td className="hidden border-b border-line px-3 py-3 align-middle text-ink-2 xl:table-cell">
                {[r.suppressed ? `가림 ${r.suppressed}` : '', r.generalized ? `일반화 ${r.generalized}` : ''].filter(Boolean).join(' ') || '없음'}
              </td>
              <td className="border-b border-line px-3 py-3 text-right align-middle">
                {r.k_now != null ? (
                  <span
                    className="num inline-flex items-center gap-2 whitespace-nowrap"
                    title={`${r.focus_case ? `${caseLabel(r.focus_case)} 기준. ` : ''}${r.k_if_raw != null && r.k_if_raw !== r.k_now ? `그대로 답했다면 ${r.k_if_raw}명, ` : ''}지금 ${r.k_now}명 (기준 ${kReq}명)`}
                  >
                    {r.k_if_raw != null && r.k_if_raw !== r.k_now && (
                      <>
                        <span className={`font-semibold ${r.k_if_raw < kReq ? 'text-danger-text' : 'text-ink-3'}`}>{r.k_if_raw}</span>
                        <span className="text-ink-3" aria-label="에서">→</span>
                      </>
                    )}
                    <span className="font-bold text-ink">{r.k_now.toLocaleString()}명</span>
                    <span className="hidden sm:inline-flex">
                      <RangeMini raw={r.k_if_raw} now={r.k_now} max={pRef} g={kReq} width={84} />
                    </span>
                  </span>
                ) : (
                  <span className="text-ink-3">–</span>
                )}
              </td>
              <td className="hidden border-b border-line px-3 py-3 text-right align-middle text-ink-3 sm:table-cell">{relativeTime(r.last_active)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
