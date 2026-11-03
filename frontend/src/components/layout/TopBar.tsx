import { BookOpen, Monitor, Moon, Search, Sun } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useBackendInfo } from '../../hooks/useBackendInfo';
import { useTheme } from '../../hooks/useTheme';
import { useTerms } from '../../state/TermContext';
import { LogoMark } from '../brand/Logo';
import { ROLE_HOME, ROLE_LABEL, type Role } from './nav';

const THEME_LABEL = { system: '시스템 설정을 따름', light: '라이트', dark: '다크' } as const;

export function TopBar({ role, title, onOpenPalette }: { role: Role; title: string; onOpenPalette(): void }) {
  const navigate = useNavigate();
  const backend = useBackendInfo();
  const { theme, cycle } = useTheme();
  const ThemeIcon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor;
  const live = backend && backend.kind !== 'offline';
  const terms = useTerms();

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-page px-4 md:px-6">
      <span className="md:hidden">
        <LogoMark size={28} />
      </span>
      <h1 className="truncate text-lg font-bold tracking-[-0.02em]">{title}</h1>
      {backend && (
        <span className="hidden items-center gap-1.5 text-xs text-ink-2 lg:inline-flex" title={backend.detail}>
          <i className={`block h-[7px] w-[7px] rounded-full ${live ? 'bg-safe' : 'bg-danger'}`} style={{ boxShadow: `0 0 0 3px var(--zp-${live ? 'safe' : 'danger'}-tint)` }} />
          {backend.kind === 'webdemo' ? '방어 규칙 작동 중' : backend.label}
        </span>
      )}

      <div role="group" aria-label="화면 전환" className="ml-auto flex rounded-control bg-surface-2 p-1">
        {(['clinician', 'security'] as Role[]).map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={role === r}
            onClick={() => navigate(ROLE_HOME[r])}
            className={`h-7 whitespace-nowrap rounded-[7px] px-2.5 text-[13px] font-semibold transition-colors sm:px-3 ${role === r ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink'}`}
          >
            <span className="sm:hidden">{r === 'security' ? '보안' : '의료진'}</span>
            <span className="hidden sm:inline">{ROLE_LABEL[r]}</span>
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={onOpenPalette}
        className="hidden h-9 w-[260px] items-center gap-2 rounded-control border border-line-input bg-surface px-3 text-left text-[13px] text-ink-3 xl:flex"
      >
        <Search className="h-4 w-4" aria-hidden />
        <span className="flex-1">화면, 대화 번호, 명령 찾기</span>
        <span className="kbd">⌘</span>
        <span className="kbd">K</span>
      </button>
      <button type="button" onClick={onOpenPalette} className="btn-ghost h-9 w-9 px-0 xl:hidden" aria-label="명령 찾기 열기">
        <Search className="h-4 w-4" aria-hidden />
      </button>
      <button
        type="button"
        onClick={terms.toggleDrawer}
        aria-pressed={terms.drawerOpen}
        className={`btn-ghost h-9 px-2.5 ${terms.drawerOpen ? 'bg-iris-tint text-iris-text' : ''}`}
        title="의료 용어 찾기 (답변 옆에 패널로 열림)"
      >
        <BookOpen className="h-4 w-4" aria-hidden />
        <span className="hidden text-[13px] sm:inline">용어</span>
      </button>
      <button type="button" onClick={cycle} className="btn-ghost h-9 w-9 px-0" aria-label={`테마: ${THEME_LABEL[theme]} (눌러서 바꾸기)`} title={`테마: ${THEME_LABEL[theme]}`}>
        <ThemeIcon className="h-4 w-4" aria-hidden />
      </button>
    </header>
  );
}
