import { ArrowRight, ShieldCheck } from 'lucide-react';
import type { ProtectionResult } from '../../types/domain';
import { ActionBadge } from '../common/ActionBadge';

/** 답변 아래 보호 처리 설명. 문장과 항목 모두 백엔드 ProtectionResult에서 온다. */
export function PrivacyExplanation({ protection }: { protection: ProtectionResult }) {
  const changed = protection.transformations.filter((t) => t.action !== 'allow');
  const kChanged = protection.kBefore !== protection.kAfter;

  if (!changed.length) {
    return (
      <p className="mt-1.5 flex gap-1 text-[11px] text-slate-500">
        <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden />
        <span>
          {protection.explanation}{' '}
          <span className="whitespace-nowrap tabular-nums">
            (k {protection.kBefore}
            {kChanged && <> → {protection.kAfter}</>})
          </span>
        </span>
      </p>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-blue-100 bg-blue-50/70 px-3 py-2 text-xs text-slate-700">
      <p className="flex gap-1.5">
        <ShieldCheck className="mt-px h-4 w-4 shrink-0 text-blue-600" aria-hidden />
        <span>{protection.explanation}</span>
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5 pl-[22px]">
        {protection.transformations.map((t) => (
          <li key={t.id} className="inline-flex items-center gap-1 rounded-md bg-white px-1.5 py-0.5 ring-1 ring-blue-100">
            <span className="font-medium">{t.attributeLabel}</span>
            {t.action === 'generalize' && t.levelDescription && <span className="text-slate-500">{t.levelDescription}</span>}
            <ActionBadge action={t.action} />
          </li>
        ))}
        <li className="inline-flex items-center gap-1 rounded-md bg-white px-1.5 py-0.5 tabular-nums ring-1 ring-blue-100">
          후보 수 k {protection.kBefore}
          {kChanged && (
            <>
              <ArrowRight className="h-3 w-3" aria-hidden /> {protection.kAfter}
            </>
          )}
          {!kChanged && ' 유지'}
        </li>
      </ul>
    </div>
  );
}
