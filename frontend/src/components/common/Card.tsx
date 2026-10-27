import type { ReactNode } from 'react';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-slate-200 bg-white shadow-card ${className}`}>{children}</section>;
}

export function CardHeader({ title, aside, id }: { title: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
      <h2 id={id} className="text-[13px] font-semibold text-slate-800">
        {title}
      </h2>
      {aside && <div className="shrink-0 text-[11px] text-slate-500">{aside}</div>}
    </header>
  );
}
