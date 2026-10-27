import { AlertCircle, Inbox, Loader2, RotateCw } from 'lucide-react';

export function LoadingState({ label = '불러오는 중…', compact = false }: { label?: string; compact?: boolean }) {
  return (
    <div role="status" className={`flex items-center justify-center gap-2 text-xs text-slate-500 ${compact ? 'py-3' : 'py-8'}`}>
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-3 flex flex-col items-center gap-2 rounded-lg bg-red-50 px-3 py-4 text-center text-xs text-red-700">
      <AlertCircle className="h-5 w-5" aria-hidden />
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1 font-medium hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500"
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
          다시 시도
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
      <Inbox className="h-5 w-5" aria-hidden />
      <p>{message}</p>
    </div>
  );
}
