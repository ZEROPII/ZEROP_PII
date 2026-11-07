import { AlertCircle, Inbox, Loader2, RotateCw } from 'lucide-react';
import type { ReactNode } from 'react';

export function LoadingState({ label = '불러오는 중', compact = false }: { label?: string; compact?: boolean }) {
  return (
    <div role="status" className={`flex items-center justify-center gap-2 text-[13px] text-ink-3 ${compact ? 'py-4' : 'py-10'}`}>
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-3 flex flex-col items-center gap-2 rounded-control bg-danger-tint px-4 py-4 text-center text-[13px] text-danger-text">
      <AlertCircle className="h-5 w-5" aria-hidden />
      <p>{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary btn-sm">
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
          다시 불러오기
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-[13px] text-ink-3">
      <Inbox className="h-5 w-5" aria-hidden />
      <p className="max-w-[34em]">{message}</p>
      {children}
    </div>
  );
}
