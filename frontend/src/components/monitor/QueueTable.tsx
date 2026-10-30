import { relativeTime, caseLabel } from '../../lib/time';
import type { MonitorRow } from '../../types/monitor';
import { StatusChip, StatusIcon } from '../common/StatusChip';
import { MiniCrowd } from '../viz/CrowdLens';

const TONE = { danger: 'danger', caution: 'caution', safe: 'safe' } as const;

interface Props {
  rows: MonitorRow[];
  selected: string | null;
  onSelect(id: string): void;
  kReq: number;
}

export function QueueTable({ rows, selected, onSelect, kReq }: Props) {
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
                  <span className="ml-2 text-xs text-ink-3">{r.source_label}</span>
                </button>
                <div className="text-xs text-ink-3">
                  {r.qtype_label} {r.turns}턴
                </div>
                {r.flag && (
                  <div className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-caution-text">
                    <StatusIcon tone="caution" className="h-2.5 w-2.5" />
                    {r.flag}
                  </div>
                )}
                {r.review && <div className="mt-1 text-[11px] font-semibold text-ink-3">{r.review.label}</div>}
              </td>
              <td className="hidden border-b border-line px-3 py-3 align-middle text-ink-2 xl:table-cell">
                {[r.suppressed ? `가림 ${r.suppressed}` : '', r.generalized ? `일반화 ${r.generalized}` : ''].filter(Boolean).join(' ') || '없음'}
              </td>
              <td className="border-b border-line px-3 py-3 text-right align-middle">
                {r.k_now != null ? (
                  <span className="num inline-flex items-center gap-2 whitespace-nowrap" title={r.focus_case ? `${caseLabel(r.focus_case)} 기준` : undefined}>
                    {r.k_if_raw != null && (
                      <>
                        <span className={`font-semibold ${r.k_if_raw < kReq ? 'text-danger-text' : 'text-ink-3'}`}>{r.k_if_raw}명</span>
                        <span className="text-ink-3" aria-label="에서">→</span>
                      </>
                    )}
                    <span className="hidden sm:inline-flex">
                      <MiniCrowd k={Math.min(r.k_now, 8)} />
                    </span>
                    <span className="font-bold text-ink">{r.k_now > 999 ? '999+' : r.k_now}명</span>
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
