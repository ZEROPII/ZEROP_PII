import type { ReactNode } from 'react';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}

export function CardHeader({ title, aside, id }: { title: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <header className="flex min-h-[52px] items-center justify-between gap-3 border-b border-line px-4 py-3">
      <h2 id={id} className="text-[15px] font-bold tracking-[-0.01em] text-ink">
        {title}
      </h2>
      {aside && <div className="shrink-0 text-xs text-ink-3">{aside}</div>}
    </header>
  );
}
