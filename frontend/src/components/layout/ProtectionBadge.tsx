import { ShieldCheck, ShieldOff } from 'lucide-react';
import type { Async } from '../../state/workspaceReducer';
import type { ProtectionPolicy } from '../../types/domain';

/** 현재 시스템 보호 정책 표시. 값은 백엔드(getProtectionPolicy)에서 받는다. */
export function ProtectionBadge({ policy }: { policy: Async<ProtectionPolicy> }) {
  if (policy.status !== 'success' || !policy.data) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 px-3 py-1 text-xs text-slate-300">
        {policy.status === 'error' ? <ShieldOff className="h-3.5 w-3.5" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5 opacity-50" aria-hidden />}
        {policy.status === 'error' ? '보호 정책 확인 불가' : '보호 정책 확인 중…'}
      </span>
    );
  }
  const p = policy.data;
  const unprotected = p.arm === 'C0';
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
        unprotected ? 'bg-red-500/15 text-red-200 ring-red-400/40' : 'bg-emerald-400/10 text-emerald-200 ring-emerald-300/30'
      }`}
      title={`실행 갈래 ${p.arm} · 원래 값 k ≤ ${p.minK}이면 일반화, ≤ ${p.suppressK}이면 비공개${p.source === 'mock' ? ' (Mock 정책)' : ''}`}
    >
      {unprotected ? <ShieldOff className="h-3.5 w-3.5" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden />}
      {p.modeLabel} · {p.stateModeLabel} · k ≥ {p.minK}
    </span>
  );
}
