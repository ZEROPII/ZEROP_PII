import { LogOut, UserRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../state/AuthContext';

/**
 * 로그인한 계정 표시와 로그아웃 (python -m medicloak). 데모 모드에서는 그리지 않는다.
 * tone='chrome'은 의료진 EMR 머리줄(어두운 바탕), 'console'은 관제 머리줄.
 */
export function UserMenu({ tone }: { tone: 'chrome' | 'console' }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!user) return null;
  const button =
    tone === 'chrome'
      ? 'text-emr-chrome-text hover:bg-emr-chrome-hover'
      : 'text-ink hover:bg-surface-2';
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex h-8 items-center gap-2 rounded-[8px] px-2 text-[13px] font-semibold ${button}`}
      >
        <span className={`grid h-6 w-6 place-items-center rounded-full ${tone === 'chrome' ? 'bg-emr-chrome-hover text-[#9fe6dc]' : 'bg-iris-tint text-iris-text'}`}>
          <UserRound className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span className="hidden max-w-[9em] truncate md:inline">{user.displayName}</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-10 z-50 w-[240px] rounded-control border border-line bg-surface p-1.5 text-ink shadow-overlay">
          <div className="px-2.5 pb-2 pt-1.5">
            <p className="text-[14px] font-bold">{user.displayName}</p>
            <p className="mt-0.5 text-xs text-ink-3">
              {user.roleLabel}
              {user.department ? ` · ${user.department}` : ''} · <span className="font-mono">{user.username}</span>
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left text-[13px] font-semibold hover:bg-surface-2"
          >
            <LogOut className="h-4 w-4 text-ink-3" aria-hidden />
            로그아웃
          </button>
        </div>
      )}
    </div>
  );
}
