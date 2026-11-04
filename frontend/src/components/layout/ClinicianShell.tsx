import { Bell, BookOpen, Monitor, Moon, Search, ShieldAlert, ShieldCheck, Sun } from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { apiMode } from '../../api';
import { useTheme } from '../../hooks/useTheme';
import { useClinicMessages } from '../../state/ClinicMessages';
import { useTerms } from '../../state/TermContext';
import { useWorkspace } from '../../state/WorkspaceContext';
import { LogoMark } from '../brand/Logo';
import { PatientBanner } from '../clinic/PatientBanner';
import { NAV, ROLE_HOME, ROLE_LABEL, type Role } from './nav';

const THEME_LABEL = { system: '시스템 설정을 따름', light: '라이트', dark: '다크' } as const;

function ChromeButton({ label, onClick, pressed, children, badge }: { label: string; onClick(): void; pressed?: boolean; children: ReactNode; badge?: number }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={`relative inline-flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-[8px] px-2 text-[13px] font-medium transition-colors ${
        pressed ? 'bg-emr-chrome-hover text-white' : 'text-emr-chrome-muted hover:bg-emr-chrome-hover hover:text-emr-chrome-text'
      }`}
    >
      {children}
      {!!badge && (
        <span className="num absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-[#5fd3c7] px-1 text-[10px] font-bold text-emr-chrome">
          {badge}
        </span>
      )}
    </button>
  );
}

/**
 * 의료진 화면 틀: 병원 EMR 안에 들어간 진료 지원 AI처럼 보이게 한다. MediCloak은 그 AI 앞에서 답을 거르는 보호 계층이라
 * 이름은 머리줄의 'MediCloak 보호 적용' 표시로만 드러낸다.
 * 어두운 앱 머리줄(메뉴 · 찾기 · 용어 · 보호 담당자 메시지 · 보호 적용 표시) → 환자 띠 → 본문.
 * 데모용 화면 전환(의료진 | 보안 담당자)은 머리줄 오른쪽 끝에 따로 둔다.
 */
export function ClinicianShell({ role, onOpenPalette }: { role: Role; onOpenPalette(): void }) {
  const navigate = useNavigate();
  const { theme, cycle } = useTheme();
  const ThemeIcon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor;
  const terms = useTerms();
  const msgs = useClinicMessages();
  const { state } = useWorkspace();
  const off = state.policy.data?.arm === 'C0';
  const items = NAV.clinician;

  return (
    <div className="flex h-dvh flex-col bg-page text-ink">
      <header className="flex h-12 shrink-0 items-center gap-1 bg-emr-chrome px-2 text-emr-chrome-text md:px-3">
        <NavLink to="/" className="mr-2 inline-flex items-center gap-2 rounded-[8px] px-1.5 py-1" aria-label="진료 지원 AI 처음 화면">
          <LogoMark size={22} className="text-[#5fd3c7]" />
          <span className="whitespace-nowrap text-[15px] font-bold tracking-[-0.01em]">진료 지원 AI</span>
        </NavLink>
        <nav aria-label="진료 지원 메뉴" className="hidden h-full items-stretch md:flex">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center border-b-2 px-3 text-[13px] font-semibold transition-colors ${
                  isActive ? 'border-[#5fd3c7] text-white' : 'border-transparent text-emr-chrome-muted hover:text-emr-chrome-text'
                }`
              }
            >
              {item.title}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-0.5">
          <button
            type="button"
            onClick={onOpenPalette}
            className="mr-1 hidden h-8 w-[220px] items-center gap-2 rounded-[8px] border border-emr-chrome-line px-2.5 text-left text-xs text-emr-chrome-muted hover:text-emr-chrome-text xl:flex"
          >
            <Search className="h-3.5 w-3.5" aria-hidden />
            <span className="flex-1">사례, 화면, 의료 용어 찾기</span>
            <span className="font-mono text-[11px]">⌘K</span>
          </button>
          <span className="xl:hidden">
            <ChromeButton label="찾기 열기" onClick={onOpenPalette}>
              <Search className="h-4 w-4" aria-hidden />
            </ChromeButton>
          </span>
          <ChromeButton label="의료 용어 찾기" onClick={terms.toggleDrawer} pressed={terms.drawerOpen}>
            <BookOpen className="h-4 w-4" aria-hidden />
            <span className="hidden lg:inline">용어</span>
          </ChromeButton>
          {msgs.supported && (
            <ChromeButton
              label={msgs.unread ? `개인정보 보호 담당자 메시지 ${msgs.unread}건 새로 옴` : '개인정보 보호 담당자 메시지'}
              badge={msgs.unread}
              onClick={() => {
                navigate('/');
                msgs.requestOpen();
              }}
            >
              <Bell className="h-4 w-4" aria-hidden />
            </ChromeButton>
          )}
          <NavLink
            to="/guide"
            className={`mx-1 hidden h-8 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold sm:inline-flex ${
              off ? 'bg-[#5a1f22] text-[#ffb4ae]' : 'bg-emr-chrome-hover text-[#9fe6dc]'
            }`}
            title={
              off
                ? '비교용 설정: MediCloak 보호 규칙이 꺼져 있습니다'
                : 'MediCloak: 답에서 개인을 알아볼 수 있는 값은 범위로 바꾸거나 비공개로 표시합니다'
            }
          >
            {off ? <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden />}
            {off ? 'MediCloak 보호 꺼짐 (비교용)' : 'MediCloak 보호 적용'}
          </NavLink>
          <div role="group" aria-label="데모 화면 전환" className="ml-1 flex items-center rounded-[8px] border border-emr-chrome-line p-0.5">
            <span className="hidden px-1.5 text-[10.5px] text-emr-chrome-muted lg:inline">데모</span>
            {(['clinician', 'security'] as Role[]).map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={role === r}
                onClick={() => navigate(ROLE_HOME[r])}
                className={`h-6 whitespace-nowrap rounded-[6px] px-2 text-xs font-semibold ${
                  role === r ? 'bg-emr-chrome-hover text-white' : 'text-emr-chrome-muted hover:text-emr-chrome-text'
                }`}
              >
                <span className="sm:hidden">{r === 'security' ? '보안' : '의료진'}</span>
                <span className="hidden sm:inline">{ROLE_LABEL[r]}</span>
              </button>
            ))}
          </div>
          <ChromeButton label={`테마: ${THEME_LABEL[theme]} (눌러서 바꾸기)`} onClick={cycle}>
            <ThemeIcon className="h-4 w-4" aria-hidden />
          </ChromeButton>
        </div>
      </header>
      {apiMode === 'mock' && (
        <p className="shrink-0 border-b border-line bg-caution-tint px-4 py-1 text-center text-xs text-caution-text">
          예시 데이터로 동작 중입니다. 사례와 답은 화면 확인용이며 실제 기록이 아닙니다.
        </p>
      )}
      <PatientBanner />
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <nav aria-label="진료 지원 메뉴" className="flex shrink-0 border-t border-line bg-surface md:hidden">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-semibold ${isActive ? 'text-iris-text' : 'text-ink-3'}`}
          >
            <item.icon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
